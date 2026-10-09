from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.contexto import obter_contexto
from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, get_current_user_ou_mfa_setup, requer_permissao
from app.models.parametro import ParametroGlobal
from app.models.usuario import RefreshToken, Usuario
from app.schemas.auth import (
    ConviteCreate,
    ConviteResponse,
    DefinirSenhaConvite,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MfaConfirmarRequest,
    MfaDesabilitarRequest,
    MfaIniciarResponse,
    MfaValidarRequest,
    RefreshRequest,
    TokenResponse,
    TrocarSenhaObrigatoriaRequest,
    TrocarSenhaRequest,
    UsuarioPublico,
)
from app.schemas.usuario import UsuarioOut
from app.services import notificacao_service
from app.services.pendencias_service import Pendencia
from app.security import (
    PERFIS_COM_2FA_OBRIGATORIO,
    criar_access_token,
    criar_token_temporario,
    decodificar_token,
    gerar_mfa_secret,
    gerar_provisioning_uri,
    gerar_token_opaco,
    hash_senha,
    hash_token_opaco,
    limitador_login,
    verificar_codigo_totp,
    verificar_senha,
)

router = APIRouter(prefix="/auth", tags=["Autenticacao"])
settings = get_settings()


def _central_lock(db: Session):
    from app.central.policy import installed
    if installed(db) and db.get_bind().dialect.name == 'postgresql':
        from sqlalchemy import text
        db.execute(text('SELECT pg_advisory_xact_lock(7349102301)'))


def _central_claims(db: Session, usuario: Usuario, tipo: str):
    from app.central.policy import installed, epoch
    claims = {'tipo': tipo}
    if installed(db):
        claims['central_versao'] = epoch(db, usuario.id)
    return claims


def _central_temporario_valido(db: Session, usuario: Usuario, payload: dict):
    from app.central.policy import installed, epoch
    return not installed(db) or payload.get('central_versao', 0) == epoch(db, usuario.id)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Normaliza datetimes vindos do banco para timezone-aware (UTC).
    Necessario porque alguns backends (ex.: SQLite, usado em testes) nao
    preservam o tzinfo mesmo em colunas DateTime(timezone=True)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _serializar_usuario_publico(usuario: Usuario) -> UsuarioPublico:
    return UsuarioPublico(
        id=usuario.id,
        nome=usuario.nome,
        usuario=usuario.usuario,
        email=usuario.email,
        ativo=usuario.ativo,
        perfil_id=usuario.perfil_id,
        mfa_habilitado=usuario.mfa_habilitado,
        mfa_obrigatorio=(usuario.perfil_id in PERFIS_COM_2FA_OBRIGATORIO) and not usuario.mfa_habilitado,
    )


def _gerar_par_tokens(db: Session, usuario: Usuario) -> dict:
    claims = {"perfil_id": usuario.perfil_id}
    from app.central.policy import installed, epoch
    from app.central.models import ContaCentral
    if installed(db):
        claims['central_versao'] = epoch(db, usuario.id)
    access_token = criar_access_token(subject=usuario.usuario, extra_claims=claims)

    refresh_bruto = gerar_token_opaco()
    db.add(
        RefreshToken(
            usuario_id=usuario.id,
            token_hash=hash_token_opaco(refresh_bruto),
            expira_em=_agora() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DIAS),
        )
    )
    return {"access_token": access_token, "refresh_token": refresh_bruto}


SENHA_VALIDADE_DIAS_PADRAO = 180  # usado so se o parametro global nao existir ainda


def _validade_senha_dias(db: Session) -> int:
    """Le o parametro global 'senha_validade_dias' (regra dos 6 meses).
    Ajustavel pelo Administrador via PUT /parametros/senha_validade_dias,
    sem alterar codigo. 0 ou negativo desativa a expiracao."""
    parametro = db.get(ParametroGlobal, "senha_validade_dias")
    if not parametro or not isinstance(parametro.valor, (int, float)):
        return SENHA_VALIDADE_DIAS_PADRAO
    return int(parametro.valor)


def _senha_expirada(db: Session, usuario: Usuario, agora: datetime) -> bool:
    validade_dias = _validade_senha_dias(db)
    if validade_dias <= 0:
        return False
    base = _aware(usuario.senha_alterada_em) or _aware(usuario.criado_em)
    if base is None:
        return False
    return (agora - base) > timedelta(days=validade_dias)


def _finalizar_login(db: Session, usuario: Usuario, agora: datetime, acao_sucesso: str) -> LoginResponse:
    """Chamado quando a senha (ou a troca de senha obrigatoria, ou o convite)
    acabou de ser validada com sucesso. Decide entre exigir 2FA ou emitir os
    tokens finais direto."""
    from app.central.policy import installed
    from app.central.models import ContaCentral
    if installed(db):
        conta = db.get(ContaCentral, usuario.id)
        if conta and conta.estado != 'ativo':
            raise HTTPException(403, 'Conta bloqueada, desativada ou com convite pendente.')
    if (
        not usuario.mfa_habilitado
        and settings.MFA_OBRIGATORIO_ENFORCE
        and usuario.perfil_id in PERFIS_COM_2FA_OBRIGATORIO
    ):
        # Perfil sensivel sem 2FA: nao emite sessao; so um token restrito para configurar o 2FA.
        registrar(db, usuario_id=usuario.id, acao="login_bloqueado_mfa_obrigatorio", entidade="usuarios", entidade_id=str(usuario.id))
        db.commit()
        setup_token = criar_token_temporario(usuario.usuario, 15, _central_claims(db, usuario, 'mfa_setup'))
        return LoginResponse(mfa_configuracao_pendente=True, mfa_setup_token=setup_token)

    if usuario.mfa_habilitado:
        mfa_token = criar_token_temporario(
            usuario.usuario, settings.MFA_TOKEN_EXPIRE_MINUTOS, _central_claims(db, usuario, 'mfa_pendente')
        )
        registrar(db, usuario_id=usuario.id, acao="login_senha_ok_aguardando_mfa", entidade="usuarios", entidade_id=str(usuario.id))
        db.commit()
        return LoginResponse(mfa_pendente=True, mfa_token=mfa_token)

    usuario.ultimo_login_em = agora
    registrar(db, usuario_id=usuario.id, acao=acao_sucesso, entidade="usuarios", entidade_id=str(usuario.id))
    tokens = _gerar_par_tokens(db, usuario)
    db.commit()
    db.refresh(usuario)
    return LoginResponse(usuario=_serializar_usuario_publico(usuario), **tokens)


@router.post("/login", response_model=LoginResponse)
def login(dados: LoginRequest, db: Session = Depends(get_db)):
    _central_lock(db)
    ip = obter_contexto().ip or "desconhecido"
    if limitador_login.excedeu(ip, settings.LOGIN_RATE_LIMIT_MAX, settings.LOGIN_RATE_LIMIT_JANELA_SEGUNDOS):
        registrar(db, usuario_id=None, acao="login_rate_limit", entidade="usuarios", depois={"usuario_tentado": dados.usuario[:60]})
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas de login deste endereco. Aguarde um instante e tente novamente.",
            headers={"Retry-After": str(settings.LOGIN_RATE_LIMIT_JANELA_SEGUNDOS)},
        )

    usuario = db.query(Usuario).filter(Usuario.usuario == dados.usuario).first()

    if not usuario:
        # Nao revela ao cliente se o usuario existe, mas a tentativa fica na auditoria.
        registrar(db, usuario_id=None, acao="login_usuario_inexistente", entidade="usuarios", depois={"usuario_tentado": dados.usuario[:60]})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario ou senha invalidos.")

    agora = _agora()

    # Desbloqueio automatico apos o tempo configurado.
    if _aware(usuario.bloqueado_ate) and _aware(usuario.bloqueado_ate) <= agora:
        usuario.bloqueado_ate = None
        usuario.tentativas_login_falhas = 0
        registrar(db, usuario_id=usuario.id, acao="usuario_desbloqueado_automatico", entidade="usuarios", entidade_id=str(usuario.id))

    if _aware(usuario.bloqueado_ate) and _aware(usuario.bloqueado_ate) > agora:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Usuario bloqueado ate {usuario.bloqueado_ate.isoformat()} por excesso de tentativas invalidas.",
        )

    if not usuario.senha_definida:
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este usuario ainda nao definiu a senha (convite pendente).",
        )

    if not usuario.ativo:
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inativo.")

    if not verificar_senha(dados.senha, usuario.senha_hash):
        usuario.tentativas_login_falhas += 1
        registrar(
            db,
            usuario_id=usuario.id,
            acao="login_falhou",
            entidade="usuarios",
            entidade_id=str(usuario.id),
            depois={"tentativas_login_falhas": usuario.tentativas_login_falhas},
        )
        acabou_de_bloquear = False
        if usuario.tentativas_login_falhas >= settings.MAX_TENTATIVAS_LOGIN:
            usuario.bloqueado_ate = agora + timedelta(minutes=settings.BLOQUEIO_MINUTOS)
            acabou_de_bloquear = True
            registrar(
                db,
                usuario_id=usuario.id,
                acao="usuario_bloqueado",
                entidade="usuarios",
                entidade_id=str(usuario.id),
                depois={"bloqueado_ate": usuario.bloqueado_ate.isoformat()},
            )
        if acabou_de_bloquear:
            notificacao_service.notificar_evento(db, Pendencia(
                tipo="conta_bloqueada", modulo="seguranca", nivel="critico", permissao="usuarios:write",
                titulo=f"Conta bloqueada: {usuario.usuario}",
                mensagem=f"{settings.MAX_TENTATIVAS_LOGIN} tentativas invalidas; bloqueada ate {usuario.bloqueado_ate.isoformat()}.",
                chave_dedup=f"conta_bloqueada:{usuario.id}:{usuario.bloqueado_ate.isoformat()}",
                entidade="usuarios", entidade_id=str(usuario.id),
            ))
        db.commit()
        if acabou_de_bloquear:
            # A propria tentativa que cruzou o limite ja informa o bloqueio,
            # em vez de deixar o usuario descobrir isso so na proxima tentativa.
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Usuario bloqueado ate {usuario.bloqueado_ate.isoformat()} por excesso de tentativas invalidas.",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario ou senha invalidos.")

    # Senha correta.
    usuario.tentativas_login_falhas = 0

    motivo_troca = None
    if usuario.deve_trocar_senha:
        motivo_troca = "primeiro_acesso"
    elif _senha_expirada(db, usuario, agora):
        motivo_troca = "expirada"

    if motivo_troca:
        senha_pendente_token = criar_token_temporario(
            usuario.usuario, settings.SENHA_PENDENTE_TOKEN_EXPIRE_MINUTOS, _central_claims(db, usuario, 'senha_pendente')
        )
        registrar(
            db,
            usuario_id=usuario.id,
            acao="login_bloqueado_senha_pendente",
            entidade="usuarios",
            entidade_id=str(usuario.id),
            depois={"motivo": motivo_troca},
        )
        db.commit()
        return LoginResponse(senha_pendente=True, senha_pendente_token=senha_pendente_token, senha_pendente_motivo=motivo_troca)

    return _finalizar_login(db, usuario, agora, acao_sucesso="login_sucesso")


@router.post("/trocar-senha-obrigatoria", response_model=LoginResponse)
def trocar_senha_obrigatoria(dados: TrocarSenhaObrigatoriaRequest, db: Session = Depends(get_db)):
    """Completa a troca de senha exigida (primeiro acesso com senha temporaria
    ou expiracao pela regra dos 6 meses) e, na sequencia, finaliza o login
    (emite tokens, ou pede 2FA se o usuario tiver habilitado)."""
    _central_lock(db)
    payload = decodificar_token(dados.senha_pendente_token)
    invalido = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido ou expirado.")
    if not payload or payload.get("tipo") != "senha_pendente" or "sub" not in payload:
        raise invalido

    usuario = db.query(Usuario).filter(Usuario.usuario == payload["sub"]).first()
    if not usuario or not usuario.ativo or not _central_temporario_valido(db, usuario, payload):
        raise invalido

    agora = _agora()
    usuario.senha_hash = hash_senha(dados.nova_senha)
    usuario.senha_alterada_em = agora
    usuario.deve_trocar_senha = False
    registrar(db, usuario_id=usuario.id, acao="senha_trocada_obrigatoria", entidade="usuarios", entidade_id=str(usuario.id))

    return _finalizar_login(db, usuario, agora, acao_sucesso="login_sucesso")


@router.post("/trocar-senha", response_model=UsuarioOut)
def trocar_senha(dados: TrocarSenhaRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    """Troca de senha voluntaria (usuario ja autenticado). Tambem zera a
    contagem da regra dos 6 meses (senha_alterada_em)."""
    if not verificar_senha(dados.senha_atual, usuario.senha_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha atual incorreta.")

    usuario.senha_hash = hash_senha(dados.nova_senha)
    usuario.senha_alterada_em = _agora()
    usuario.deve_trocar_senha = False
    registrar(db, usuario_id=usuario.id, acao="senha_trocada_voluntariamente", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/mfa/validar", response_model=TokenResponse)
def validar_mfa(dados: MfaValidarRequest, db: Session = Depends(get_db)):
    _central_lock(db)
    payload = decodificar_token(dados.mfa_token)
    invalido = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="mfa_token invalido ou expirado.")
    if not payload or payload.get("tipo") != "mfa_pendente" or "sub" not in payload:
        raise invalido

    usuario = db.query(Usuario).filter(Usuario.usuario == payload["sub"]).first()
    if not usuario or not usuario.ativo or not usuario.mfa_habilitado or not _central_temporario_valido(db, usuario, payload):
        raise invalido

    if not verificar_codigo_totp(usuario.mfa_secret, dados.codigo):
        registrar(db, usuario_id=usuario.id, acao="mfa_codigo_invalido", entidade="usuarios", entidade_id=str(usuario.id))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Codigo de verificacao invalido.")

    usuario.ultimo_login_em = _agora()
    registrar(db, usuario_id=usuario.id, acao="login_sucesso_mfa", entidade="usuarios", entidade_id=str(usuario.id))
    tokens = _gerar_par_tokens(db, usuario)
    db.commit()
    db.refresh(usuario)
    return TokenResponse(usuario=_serializar_usuario_publico(usuario), **tokens)


@router.post("/refresh", response_model=TokenResponse)
def refresh(dados: RefreshRequest, db: Session = Depends(get_db)):
    _central_lock(db)
    token_hash = hash_token_opaco(dados.refresh_token)
    registro = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    invalido = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token invalido ou expirado.")
    if not registro or registro.revogado or _aware(registro.expira_em) <= _agora():
        raise invalido

    usuario = db.get(Usuario, registro.usuario_id)
    if not usuario or not usuario.ativo:
        raise invalido

    # Rotaciona: revoga o token usado e emite um par novo.
    from app.central.policy import installed
    from app.central.models import ContaCentral
    if installed(db):
        conta = db.get(ContaCentral, usuario.id)
        if conta and conta.estado != 'ativo':
            raise invalido
    registro.revogado = True
    tokens = _gerar_par_tokens(db, usuario)
    db.commit()
    return TokenResponse(usuario=_serializar_usuario_publico(usuario), **tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(dados: LogoutRequest, db: Session = Depends(get_db)):
    token_hash = hash_token_opaco(dados.refresh_token)
    registro = db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()
    if registro:
        registro.revogado = True
        db.commit()


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(get_current_user)):
    return usuario


# ---------- Convite de senha (Administrador convida, usuario define a propria senha) ----------
@router.post("/convite", response_model=ConviteResponse, status_code=status.HTTP_201_CREATED)
def convidar_usuario(
    dados: ConviteCreate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("usuarios:write")),
):
    if db.query(Usuario).filter(Usuario.usuario == dados.usuario).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Nome de usuario ja existe.")

    convite_bruto = gerar_token_opaco()
    expira_em = _agora() + timedelta(hours=settings.CONVITE_EXPIRA_HORAS)

    novo = Usuario(
        nome=dados.nome,
        usuario=dados.usuario,
        email=dados.email,
        # Hash de um valor aleatorio e inutilizavel ate o convite ser aceito.
        senha_hash=hash_senha(gerar_token_opaco()),
        perfil_id=dados.perfil_id,
        ativo=True,
        senha_definida=False,
        convite_token_hash=hash_token_opaco(convite_bruto),
        convite_expira_em=expira_em,
    )
    db.add(novo)
    db.flush()  # obtem novo.id
    registrar(db, usuario_id=ator.id, acao="usuario_convidado", entidade="usuarios", entidade_id=str(novo.id))
    db.commit()
    db.refresh(novo)

    return ConviteResponse(usuario_id=novo.id, convite_token=convite_bruto, expira_em=expira_em)


@router.post("/definir-senha", response_model=UsuarioOut)
def definir_senha_por_convite(dados: DefinirSenhaConvite, db: Session = Depends(get_db)):
    _central_lock(db)
    token_hash = hash_token_opaco(dados.convite_token)
    usuario = db.query(Usuario).filter(Usuario.convite_token_hash == token_hash).first()

    invalido = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Convite invalido ou expirado.")
    if not usuario or usuario.senha_definida:
        raise invalido
    if not usuario.convite_expira_em or _aware(usuario.convite_expira_em) <= _agora():
        raise invalido

    usuario.senha_hash = hash_senha(dados.senha)
    from app.central.policy import installed, mutation, check_limit
    from app.central.models import ContaCentral, Vinculo
    if installed(db):
        conta = db.get(ContaCentral, usuario.id)
        if conta:
            if not usuario.ativo or conta.estado != 'pendente':
                raise invalido
            # A ativação disputa o mesmo lock dos cadastros e reativações.
            if db.get_bind().dialect.name == 'postgresql':
                from sqlalchemy import text
                db.execute(text('SELECT pg_advisory_xact_lock(7349102301)'))
            check_limit(db, conta.cargo, exclude=usuario.id)
            for vinculo in db.query(Vinculo).filter_by(usuario_id=usuario.id):
                check_limit(db, vinculo.cargo, vinculo.setor_id, exclude=usuario.id)
            conta.estado = 'ativo'
    usuario.senha_definida = True
    usuario.senha_alterada_em = _agora()
    usuario.convite_token_hash = None
    usuario.convite_expira_em = None
    registrar(db, usuario_id=usuario.id, acao="senha_definida_por_convite", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario


# ---------- Desbloqueio manual (Administrador) ----------
@router.post("/usuarios/{usuario_id}/desbloquear", response_model=UsuarioOut)
def desbloquear_usuario(
    usuario_id: int,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("usuarios:write")),
):
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado.")

    usuario.bloqueado_ate = None
    usuario.tentativas_login_falhas = 0
    registrar(db, usuario_id=ator.id, acao="usuario_desbloqueado_manual", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario


# ---------- 2FA (TOTP) ----------
@router.post("/mfa/iniciar", response_model=MfaIniciarResponse)
def iniciar_mfa(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user_ou_mfa_setup)):
    """Gera um novo segredo TOTP (ainda nao habilitado -- so apos /mfa/confirmar)."""
    secret = gerar_mfa_secret()
    usuario.mfa_secret = secret
    usuario.mfa_habilitado = False
    registrar(db, usuario_id=usuario.id, acao="mfa_setup_iniciado", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    return MfaIniciarResponse(secret=secret, otpauth_uri=gerar_provisioning_uri(secret, usuario.usuario))


@router.post("/mfa/confirmar", response_model=UsuarioOut)
def confirmar_mfa(
    dados: MfaConfirmarRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user_ou_mfa_setup)
):
    if not usuario.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum setup de 2FA em andamento. Chame /auth/mfa/iniciar primeiro.")
    if not verificar_codigo_totp(usuario.mfa_secret, dados.codigo):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Codigo de verificacao invalido.")

    usuario.mfa_habilitado = True
    registrar(db, usuario_id=usuario.id, acao="mfa_habilitado", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/mfa/desabilitar", response_model=UsuarioOut)
def desabilitar_mfa(
    dados: MfaDesabilitarRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
):
    """O proprio usuario desabilita o 2FA, confirmando a senha."""
    if not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Senha incorreta.")

    usuario.mfa_habilitado = False
    usuario.mfa_secret = None
    registrar(db, usuario_id=usuario.id, acao="mfa_desabilitado", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario


@router.post("/usuarios/{usuario_id}/mfa/desabilitar", response_model=UsuarioOut)
def desabilitar_mfa_admin(
    usuario_id: int,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("usuarios:write")),
):
    """Recuperacao de acesso: Administrador desabilita o 2FA de outro usuario
    (ex.: perdeu o celular com o app autenticador)."""
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado.")

    usuario.mfa_habilitado = False
    usuario.mfa_secret = None
    registrar(db, usuario_id=ator.id, acao="mfa_desabilitado_por_admin", entidade="usuarios", entidade_id=str(usuario.id))
    db.commit()
    db.refresh(usuario)
    return usuario
