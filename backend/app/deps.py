"""Dependencies de autenticacao (usuario logado) e autorizacao (RBAC por permissao)."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.models.usuario import Usuario
from app.security import decodificar_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _usuario_do_token(token: str | None, db: Session, tipos_aceitos_extra: tuple[str, ...] = ()) -> Usuario:
    credenciais_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais invalidas ou expiradas.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credenciais_invalidas

    payload = decodificar_token(token)
    if not payload or "sub" not in payload:
        raise credenciais_invalidas
    tipo = payload.get("tipo")
    if tipo in ("mfa_pendente", "senha_pendente", "mfa_setup") and tipo not in tipos_aceitos_extra:
        # Tokens temporarios emitidos antes da etapa final do login (2FA, troca
        # de senha obrigatoria ou configuracao obrigatoria de 2FA) -- nao
        # concedem acesso a rotas protegidas (salvo o tipo explicitamente aceito).
        raise credenciais_invalidas

    usuario = db.query(Usuario).filter(Usuario.usuario == payload["sub"]).first()
    if not usuario or not usuario.ativo:
        raise credenciais_invalidas
    from app.central.policy import installed, epoch
    from app.central.models import ContaCentral
    if installed(db):
        conta = db.get(ContaCentral, usuario.id)
        if payload.get('central_versao', 0) != epoch(db, usuario.id) or (conta and conta.estado != 'ativo'):
            raise credenciais_invalidas
    return usuario


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    return _usuario_do_token(token, db)


def get_current_user_ou_mfa_setup(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    """Igual a get_current_user, mas tambem aceita o token restrito de
    configuracao de 2FA (usado so em /auth/mfa/iniciar e /auth/mfa/confirmar)."""
    return _usuario_do_token(token, db, tipos_aceitos_extra=("mfa_setup",))


def tem_permissao(usuario: Usuario, chave: str) -> bool:
    """Checagem pontual de permissao (fora do padrao Depends), usada quando a
    permissao necessaria so e conhecida em tempo de execucao -- ex.: qual
    transicao de status especifica esta sendo tentada."""
    from sqlalchemy.orm import object_session
    from app.central.policy import installed, central_admin
    from app.central.models import ContaCentral
    db = object_session(usuario)
    if db is not None and installed(db) and db.get(ContaCentral, usuario.id) and not central_admin(usuario):
        return False  # busca global também não pode vazar o escopo de setores
    permissoes = set(usuario.perfil.permissoes or [])
    return "*" in permissoes or chave in permissoes


def requer_permissao(*permissoes_necessarias: str):
    """Dependency factory: bloqueia o endpoint se o perfil do usuario nao tiver
    nenhuma das permissoes informadas (nem o coringa "*")."""

    def checador(usuario: Usuario = Depends(get_current_user), db: Session = Depends(get_db)) -> Usuario:
        from app.central.policy import legacy_guard
        legacy_guard(db, usuario, permissoes_necessarias)
        permissoes_usuario = set(usuario.perfil.permissoes or [])
        if "*" in permissoes_usuario:
            return usuario
        if not permissoes_usuario.intersection(permissoes_necessarias):
            # Falha de acesso: fica na trilha de auditoria (visivel ao administrador).
            registrar(
                db, usuario_id=usuario.id, acao="acesso_negado", entidade="permissoes",
                depois={"necessarias": sorted(permissoes_necessarias)},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu perfil nao tem permissao para esta acao.",
            )
        return usuario

    return checador
