"""Site administrativo separado. Inicie somente em 127.0.0.1."""
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.database import get_db
import app.models
from app.models.usuario import Usuario, Perfil, RefreshToken
from app.models.auditoria import AuditLog
from app.routers import auth
from app.schemas.auth import LoginRequest, MfaValidarRequest, TrocarSenhaObrigatoriaRequest
from app.security import gerar_token_opaco, hash_token_opaco, hash_senha
from app.central.models import *
from app.central.policy import *

app = FastAPI(title='Nithicom · Central de acessos', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
STATIC = Path(__file__).parent / 'static'
challenges = {}

def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

@app.middleware('http')
async def local_security(request: Request, call_next):
    host = request.headers.get('host', '')
    if host not in {'localhost:8765', '127.0.0.1:8765', 'testserver'}:
        return JSONResponse({'detail': 'Host não autorizado. Use localhost:8765.'}, 400)
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')
        expected = f'{request.url.scheme}://{host}'
        if origin != expected:
            return JSONResponse({'detail': 'Origem da operação não autorizada.'}, 403)
    result = await call_next(request)
    result.headers['Cache-Control'] = 'no-store'
    result.headers['X-Content-Type-Options'] = 'nosniff'
    result.headers['X-Frame-Options'] = 'DENY'
    result.headers['Referrer-Policy'] = 'no-referrer'
    result.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return result

def authenticated(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get('central_session', '')
    session = db.get(Sessao, hash_token_opaco(token)) if token else None
    if not session or aware(session.expira_em) <= datetime.now(timezone.utc):
        raise HTTPException(401, 'Entre com sua conta de administrador central.')
    user = db.get(Usuario, session.usuario_id)
    account = db.get(ContaCentral, session.usuario_id)
    if not user or not central_admin(user) or session.versao != epoch(db, session.usuario_id) or (account and account.estado != 'ativo'):
        raise HTTPException(401, 'Sessão encerrada ou conta sem acesso.')
    if user.bloqueado_ate and aware(user.bloqueado_ate) > datetime.now(timezone.utc):
        raise HTTPException(401, 'Conta bloqueada.')
    if request.method not in {'GET', 'HEAD'} and not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session.csrf):
        deny(db, user, 'Confirmação CSRF inválida.')
    return user

def finish_login(result, response, db):
    if getattr(result, 'mfa_configuracao_pendente', False):
        raise HTTPException(409, 'Configure o segundo fator no site principal e retorne ao painel.')
    if getattr(result, 'mfa_pendente', False) or getattr(result, 'senha_pendente', False):
        now = time.time()
        for key in list(challenges):
            if challenges[key]['expires'] < now:
                challenges.pop(key, None)
        challenge_id = secrets.token_urlsafe(32)
        challenges[challenge_id] = {'expires': now + 300, 'result': result}
        response.set_cookie('central_challenge', challenge_id, httponly=True, samesite='strict', max_age=300, path='/api/login')
        return {'etapa': 'mfa' if getattr(result, 'mfa_pendente', False) else 'senha', 'mensagem': 'Informe o código do autenticador.' if getattr(result, 'mfa_pendente', False) else 'Defina uma nova senha para continuar.'}
    user = db.get(Usuario, result.usuario.id)
    if not central_admin(user):
        deny(db, user, 'Acesso exclusivo do administrador central autorizado.')
    # Os JWTs originais nunca saem para o navegador deste painel.
    db.query(RefreshToken).filter_by(token_hash=hash_token_opaco(result.refresh_token)).update({'revogado': True})
    token = gerar_token_opaco()
    account = db.get(ContaCentral, user.id)
    session = Sessao(token_hash=hash_token_opaco(token), usuario_id=user.id, csrf=secrets.token_hex(32),
                    versao=epoch(db, user.id), expira_em=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(session)
    db.commit()
    response.set_cookie('central_session', token, httponly=True, samesite='strict', max_age=3600, path='/')
    response.delete_cookie('central_challenge', path='/api/login')
    return {'etapa': 'concluido', 'csrf': session.csrf, 'nome': user.nome}

@app.post('/api/login')
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    from app.config import get_settings
    from app.security import limitador_login, verificar_senha
    settings = get_settings()
    if settings.CENTRAL_PASSWORD_HASH:
        # Credencial exclusiva deste painel; nunca altera senha_hash em usuarios.
        if limitador_login.excedeu('central-exclusive-login', 5, 60):
            raise HTTPException(429, 'Muitas tentativas. Aguarde um minuto.')
        user = db.get(Usuario, settings.CENTRAL_LOGIN_USER_ID)
        password_ok = verificar_senha(data.senha, settings.CENTRAL_PASSWORD_HASH)
        if not user or not central_admin(user) or data.usuario != user.usuario or not password_ok:
            deny(db, None, 'Usuário ou senha inválidos para a central.')
        if user.bloqueado_ate and aware(user.bloqueado_ate) > datetime.now(timezone.utc):
            raise HTTPException(423, 'Conta de administrador bloqueada.')
        audit(db, user, 'login_exclusivo', 'usuarios', user.id, {}, {}, 'Credencial exclusiva do painel central.')
        result = auth._finalizar_login(db, user, datetime.now(timezone.utc), 'central_login_sucesso')
        return finish_login(result, response, db)
    user = db.query(Usuario).filter_by(usuario=data.usuario).first()
    # Previne que contas comuns obtenham tokens temporários administrativos.
    if not user or not central_admin(user):
        from app.security import limitador_login
        if limitador_login.excedeu('central-login', 20, 60):
            raise HTTPException(429, 'Muitas tentativas. Aguarde um minuto.')
        deny(db, user, 'Usuário ou senha inválidos para a central.')
    result = auth.login(data, db)
    return finish_login(result, response, db)

class ChallengeInput(BaseModel):
    codigo: str = Field(default='', max_length=10)
    nova_senha: str = Field(default='', max_length=72)

@app.post('/api/login/continuar')
def continue_login(data: ChallengeInput, request: Request, response: Response, db: Session = Depends(get_db)):
    key = request.cookies.get('central_challenge')
    challenge = challenges.pop(key, None)
    if not challenge or challenge['expires'] < time.time():
        raise HTTPException(401, 'Etapa de autenticação expirada. Entre novamente.')
    result = challenge['result']
    if result.mfa_pendente:
        result = auth.validar_mfa(MfaValidarRequest(mfa_token=result.mfa_token, codigo=data.codigo), db)
    else:
        if len(data.nova_senha) < 12:
            raise HTTPException(422, 'Utilize uma senha com pelo menos 12 caracteres.')
        result = auth.trocar_senha_obrigatoria(TrocarSenhaObrigatoriaRequest(senha_pendente_token=result.senha_pendente_token, nova_senha=data.nova_senha), db)
    return finish_login(result, response, db)

@app.get('/api/session')
def current(request: Request, actor=Depends(authenticated), db: Session = Depends(get_db)):
    record = db.get(Sessao, hash_token_opaco(request.cookies['central_session']))
    return {'nome': actor.nome, 'id': actor.id, 'csrf': record.csrf}

@app.post('/api/logout')
def logout(request: Request, response: Response, actor=Depends(authenticated), db: Session = Depends(get_db)):
    with mutation(db):
        db.query(Sessao).filter_by(token_hash=hash_token_opaco(request.cookies['central_session'])).delete()
        audit(db, actor, 'logout', 'usuarios', actor.id, None, None, 'Saída do painel')
    response.delete_cookie('central_session')
    return {'ok': True}

def public_user(db, user):
    account = db.get(ContaCentral, user.id)
    state = account.estado if account else ('desativado' if not user.ativo else 'pendente' if not user.senha_definida else 'bloqueado' if user.bloqueado_ate and aware(user.bloqueado_ate) > datetime.now(timezone.utc) else 'ativo')
    if state == 'ativo' and user.bloqueado_ate and aware(user.bloqueado_ate) > datetime.now(timezone.utc):
        state = 'bloqueado'
    if not user.ativo and state not in {'bloqueado', 'desativado'}:
        state = 'desativado'
    return {'id': user.id, 'nome': user.nome, 'usuario': user.usuario, 'email': user.email,
            'perfil_id': user.perfil_id, 'cargo': account.cargo if account else None, 'estado': state,
            'gerenciado': bool(account), 'criado_por': account.criado_por if account else None,
            'mfa': user.mfa_habilitado, 'ultimo_login': aware(user.ultimo_login_em).isoformat() if user.ultimo_login_em else None,
            'vinculos': [{'setor_id': v.setor_id, 'cargo': v.cargo, 'responsavel_id': v.responsavel_id} for v in db.query(Vinculo).filter_by(usuario_id=user.id)]}

def catalog(db):
    keys = set()
    for profile in db.query(Perfil):
        keys.update(p for p in profile.permissoes if p != '*')
    for path in (Path(__file__).parent.parent / 'routers').glob('*.py'):
        keys.update(re.findall(r'[\"\']([a-z_]+:[a-z_]+)[\"\']', path.read_text(encoding='utf-8')))
    return sorted(keys)

def asdict(obj, fields):
    return {f: aware(getattr(obj, f)).isoformat() if isinstance(getattr(obj, f), datetime) else getattr(obj, f) for f in fields}

@app.get('/api/dados')
def data(actor=Depends(authenticated), db: Session = Depends(get_db)):
    users = [public_user(db, u) for u in db.query(Usuario).order_by(Usuario.nome)]
    limits = []
    for limit in db.query(Limite):
        row = asdict(limit, ['cargo', 'setor_id', 'maximo', 'habilitado', 'alerta_percentual', 'pode_cadastrar'])
        row['utilizado'] = occupancy(db, limit.cargo, limit.setor_id)
        row['disponivel'] = max(0, limit.maximo - row['utilizado'])
        row['alerta'] = row['utilizado'] >= limit.maximo * limit.alerta_percentual / 100
        limits.append(row)
    from app.config import get_settings
    return {'modo_teste': get_settings().ENVIRONMENT == 'test', 'usuarios': users, 'perfis': [asdict(p, ['id', 'nome', 'permissoes']) for p in db.query(Perfil)],
            'setores': [asdict(s, ['id', 'nome', 'descricao', 'ativo', 'modulos', 'cargos']) for s in db.query(Setor)],
            'limites': limits, 'cargos': CARGOS, 'catalogo': catalog(db),
            'regras': [asdict(r, ['setor_id', 'cargo', 'permissao', 'permitido']) for r in db.query(Regra)],
            'excecoes': [asdict(e, ['usuario_id', 'setor_id', 'permissao', 'permitido']) for e in db.query(Excecao)],
            'administradores': sorted(admins()), 'total': len(users),
            'estados': {s: sum(u['estado'] == s for u in users) for s in ['ativo', 'bloqueado', 'desativado', 'pendente']}}

class Confirmed(BaseModel):
    model_config = ConfigDict(extra='forbid')
    justificativa: str = Field(min_length=5, max_length=500)
    confirmar: bool

def confirmed(data):
    if not data.confirmar:
        raise HTTPException(422, 'Confirme explicitamente a operação.')

class SectorInput(Confirmed):
    nome: str = Field(min_length=2, max_length=100)
    descricao: str = Field(default='', max_length=500)
    ativo: bool = True
    modulos: list[str]
    cargos: list[str]

@app.put('/api/setores/{sid}')
def save_sector(sid: int, data: SectorInput, actor=Depends(authenticated), db: Session = Depends(get_db)):
    confirmed(data)
    if any(c not in CARGOS for c in data.cargos) or any(m not in {k.split(':')[0] for k in catalog(db)} for m in data.modulos):
        raise HTTPException(422, 'Cargo ou módulo não encontrado no sistema.')
    with mutation(db):
        sector = db.get(Setor, sid) if sid else Setor()
        if not sector:
            raise HTTPException(404, 'Setor não encontrado.')
        before = asdict(sector, ['nome', 'descricao', 'ativo', 'modulos', 'cargos']) if sid else None
        if sid:
            assigned = {v.cargo for v in db.query(Vinculo).filter_by(setor_id=sid)}
            if not assigned.issubset(set(data.cargos)):
                raise HTTPException(409, 'Existem usuários com cargos que seriam removidos do setor.')
        for field in ['nome', 'descricao', 'ativo', 'modulos', 'cargos']:
            setattr(sector, field, getattr(data, field))
        db.add(sector)
        db.flush()
        audit(db, actor, 'setor_salvo', 'central_setores', sector.id, before, asdict(sector, ['nome', 'descricao', 'ativo', 'modulos', 'cargos']), data.justificativa)
    return {'id': sector.id}

class LimitInput(Confirmed):
    maximo: int = Field(ge=0, le=1000000)
    habilitado: bool
    alerta_percentual: int = Field(ge=1, le=100)
    pode_cadastrar: bool = False

@app.put('/api/limites/{cargo}/{sid}')
def save_limit(cargo: str, sid: int, data: LimitInput, actor=Depends(authenticated), db: Session = Depends(get_db)):
    confirmed(data)
    check_cargo(cargo)
    if sid < 0 or (sid and not db.get(Setor, sid)):
        raise HTTPException(422, 'Setor inválido.')
    with mutation(db):
        limit = db.get(Limite, (cargo, sid))
        before = asdict(limit, ['maximo', 'habilitado', 'alerta_percentual', 'pode_cadastrar']) if limit else None
        if not limit:
            limit = Limite(cargo=cargo, setor_id=sid)
            db.add(limit)
        for f in ['maximo', 'habilitado', 'alerta_percentual', 'pode_cadastrar']:
            setattr(limit, f, getattr(data, f))
        audit(db, actor, 'limite_alterado', 'central_limites', f'{cargo}/{sid}', before, data.model_dump(exclude={'confirmar', 'justificativa'}), data.justificativa)
    used = occupancy(db, cargo, sid)
    return {'utilizado': used, 'excedido': used > data.maximo}

class LinkInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    setor_id: int = Field(gt=0)
    cargo: str
    responsavel_id: int | None = None

class UserInput(Confirmed):
    nome: str = Field(min_length=2, max_length=120)
    usuario: str = Field(min_length=2, max_length=60, pattern=r'^[a-zA-Z0-9_.@-]+$')
    email: str | None = Field(default=None, max_length=160)
    perfil_id: str
    cargo: str
    estado: str
    vinculos: list[LinkInput]

def save_user_transaction(db, actor, uid, data):
    confirmed(data)
    check_cargo(data.cargo)
    if data.email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', data.email):
        raise HTTPException(422, 'E-mail inválido.')
    if data.estado not in {'ativo', 'bloqueado', 'desativado', 'pendente'} or not db.get(Perfil, data.perfil_id):
        raise HTTPException(422, 'Estado ou perfil inválido.')
    user = db.get(Usuario, uid) if uid else None
    if uid and not user:
        raise HTTPException(404, 'Usuário não encontrado.')
    if uid == actor.id and (data.perfil_id != user.perfil_id or data.cargo != (db.get(ContaCentral, uid).cargo if db.get(ContaCentral, uid) else data.cargo)):
        raise HTTPException(403, 'Não é permitido alterar o próprio cargo ou perfil.')
    if user and (data.estado != 'ativo' or data.perfil_id != 'administrador'):
        protect_admin(db, uid)
    if user and not user.senha_definida and data.estado == 'ativo':
        raise HTTPException(409, 'Usuário precisa aceitar o convite antes da ativação.')
    if data.estado == 'pendente' and user and user.senha_definida:
        raise HTTPException(422, 'Use redefinição de senha para iniciar um novo convite.')
    links = [v.model_dump() for v in data.vinculos]
    for link in links:
        check_cargo(link['cargo'])
    if links and min(RANK[link['cargo']] for link in links) != RANK[data.cargo]:
        raise HTTPException(422, 'O cargo central deve ser o cargo de maior autoridade entre os vínculos de setor.')
    validate_links(db, uid, links)
    if user and data.estado in {'bloqueado', 'desativado'} and db.query(Vinculo).filter_by(responsavel_id=uid).count():
        raise HTTPException(409, 'Transfira os subordinados antes de bloquear ou desativar o responsável.')
    for child in db.query(Vinculo).filter_by(responsavel_id=uid).all() if uid else []:
        if RANK[data.cargo] >= RANK[child.cargo]:
            raise HTTPException(409, 'Cargo incompatível com os subordinados existentes.')
    if data.estado in {'ativo', 'pendente'}:
        previous_account = db.get(ContaCentral, uid) if uid else None
        occupying = bool(user and user.ativo and previous_account and previous_account.estado in {'ativo', 'pendente'})
        if not occupying or previous_account.cargo != data.cargo:
            check_limit(db, data.cargo, exclude=uid)
        for link in links:
            previous_link = db.query(Vinculo).filter_by(usuario_id=uid, setor_id=link['setor_id']).first() if uid else None
            if not occupying or not previous_link or previous_link.cargo != link['cargo']:
                check_limit(db, link['cargo'], link['setor_id'], exclude=uid)
    before = public_user(db, user) if user else None
    invitation = None
    if not user:
        invitation = gerar_token_opaco()
        user = Usuario(nome=data.nome, usuario=data.usuario, email=data.email, perfil_id=data.perfil_id,
                       senha_hash=hash_senha(gerar_token_opaco()), ativo=True, senha_definida=False,
                       convite_token_hash=hash_token_opaco(invitation), convite_expira_em=datetime.now(timezone.utc) + timedelta(hours=72))
        db.add(user)
        db.flush()
        uid = user.id
        state = 'pendente'
    else:
        state = data.estado
    user.nome, user.email, user.perfil_id = data.nome, data.email, data.perfil_id
    if data.usuario != user.usuario:
        raise HTTPException(422, 'O identificador de login existente não pode ser alterado pelo painel.')
    user.ativo = state in {'ativo', 'pendente'}
    account = db.get(ContaCentral, uid)
    if not account:
        account = ContaCentral(usuario_id=uid, cargo=data.cargo, estado=state, criado_por=actor.id if invitation else None)
        db.add(account)
    account.cargo, account.estado = data.cargo, state
    db.query(Vinculo).filter_by(usuario_id=uid).delete()
    for link in links:
        db.add(Vinculo(usuario_id=uid, **link))
    db.flush()
    revoke(db, uid)
    audit(db, actor, 'usuario_salvo', 'usuarios', uid, before, public_user(db, user), data.justificativa)
    return {'id': uid, 'convite': invitation}

@app.put('/api/usuarios/{uid}')
def save_user(uid: int, data: UserInput, actor=Depends(authenticated), db: Session = Depends(get_db)):
    try:
        with mutation(db):
            result = save_user_transaction(db, actor, uid, data)
        return result
    except HTTPException as error:
        audit(db, actor, 'operacao_negada', 'usuarios', uid, None, {'motivo': error.detail}, data.justificativa)
        db.commit()
        raise
    except IntegrityError:
        raise HTTPException(409, 'Nome de usuário ou e-mail já utilizado.')

@app.post('/api/usuarios/{uid}/sessoes')
def end_sessions(uid: int, data: Confirmed, actor=Depends(authenticated), db: Session = Depends(get_db)):
    confirmed(data)
    if not db.get(Usuario, uid):
        raise HTTPException(404, 'Usuário não encontrado.')
    with mutation(db):
        revoke(db, uid)
        audit(db, actor, 'sessoes_revogadas', 'usuarios', uid, None, None, data.justificativa)
    return {'ok': True}

@app.post('/api/usuarios/{uid}/senha')
def reset_password(uid: int, data: Confirmed, actor=Depends(authenticated), db: Session = Depends(get_db)):
    confirmed(data)
    user = db.get(Usuario, uid)
    if not user:
        raise HTTPException(404, 'Usuário não encontrado.')
    protect_admin(db, uid)
    if not user.ativo:
        raise HTTPException(409, 'Reative a conta antes de iniciar a redefinição.')
    with mutation(db):
        token = gerar_token_opaco()
        user.senha_definida = False
        user.convite_token_hash = hash_token_opaco(token)
        user.convite_expira_em = datetime.now(timezone.utc) + timedelta(hours=72)
        account = db.get(ContaCentral, uid)
        if account:
            account.estado = 'pendente'
        revoke(db, uid)
        audit(db, actor, 'senha_redefinicao_iniciada', 'usuarios', uid, None, {'expira_em': user.convite_expira_em.isoformat()}, data.justificativa)
    return {'convite': token}

class PermissionInput(Confirmed):
    setor_id: int = Field(gt=0)
    cargo: str = ''
    usuario_id: int | None = None
    permissao: str
    estado: str

@app.put('/api/permissoes')
def save_permission(data: PermissionInput, actor=Depends(authenticated), db: Session = Depends(get_db)):
    confirmed(data)
    sector = db.get(Setor, data.setor_id)
    if not sector or data.permissao not in catalog(db) or data.permissao.split(':')[0] not in sector.modulos:
        raise HTTPException(422, 'Permissão fora dos módulos autorizados do setor.')
    if data.estado not in {'herdar', 'permitido', 'negado'}:
        raise HTTPException(422, 'Estado inválido.')
    if data.usuario_id:
        if data.usuario_id == actor.id:
            deny(db, actor, 'Não é permitido ampliar ou alterar as próprias permissões.')
        if not db.query(Vinculo).filter_by(usuario_id=data.usuario_id, setor_id=data.setor_id).first():
            raise HTTPException(422, 'Usuário não vinculado ao setor.')
        model, key = Excecao, (data.usuario_id, data.setor_id, data.permissao)
    else:
        check_cargo(data.cargo)
        if data.cargo not in sector.cargos:
            raise HTTPException(422, 'Cargo não autorizado no setor.')
        model, key = Regra, (data.setor_id, data.cargo, data.permissao)
    with mutation(db):
        obj = db.get(model, key)
        before = obj.permitido if obj else None
        if data.estado == 'herdar':
            if obj:
                db.delete(obj)
        else:
            if not obj:
                obj = model(**({'usuario_id': data.usuario_id, 'setor_id': data.setor_id, 'permissao': data.permissao} if data.usuario_id else {'setor_id': data.setor_id, 'cargo': data.cargo, 'permissao': data.permissao}))
                db.add(obj)
            obj.permitido = data.estado == 'permitido'
        audit(db, actor, 'permissao_alterada', model.__tablename__, '/'.join(map(str, key)), before, {'estado': data.estado}, data.justificativa)
        if data.usuario_id:
            revoke(db, data.usuario_id)
    return {'ok': True}

@app.get('/api/permissoes/{uid}/{sid}')
def get_permissions(uid: int, sid: int, actor=Depends(authenticated), db: Session = Depends(get_db)):
    user = db.get(Usuario, uid)
    if not user:
        raise HTTPException(404, 'Usuário não encontrado.')
    return [{'permissao': key, 'permitido': effective(db, user, sid, key)[0], 'origem': effective(db, user, sid, key)[1]} for key in catalog(db)]

@app.get('/api/historico')
def history(pagina: int = 1, actor=Depends(authenticated), db: Session = Depends(get_db)):
    if pagina < 1:
        raise HTTPException(422, 'Página inválida.')
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    return {'total': query.count(), 'itens': [asdict(log, ['id', 'usuario_id', 'acao', 'entidade', 'entidade_id', 'antes', 'depois', 'criado_em', 'categoria']) for log in query.offset((pagina - 1) * 50).limit(50)]}

@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')

app.mount('/assets', StaticFiles(directory=STATIC), name='assets')
