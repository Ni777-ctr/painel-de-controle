"""Regras transacionais; não cria tabelas nem dados automaticamente."""
import os
from contextlib import contextmanager
from threading import RLock
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import inspect, text
from app.models.usuario import Usuario, RefreshToken
from app.auditoria_utils import registrar
from app.central.models import CARGOS, ContaCentral, Setor, Vinculo, Limite, Regra, Excecao, Sessao, VersaoAutenticacao

_lock = RLock()
RANK = {cargo: i for i, cargo in enumerate(CARGOS)}

def admins():
    from app.config import get_settings
    return {int(x.strip()) for x in get_settings().CENTRAL_ADMIN_IDS.split(',') if x.strip().isdigit()}

def central_admin(user):
    return user.id in admins() and user.perfil_id == 'administrador' and user.ativo

def installed(db):
    # Inspeciona a conexão da própria sessão, sem abrir/fechar outra conexão
    # que poderia afetar uma transação em um pool de conexão única de teste.
    return inspect(db.connection()).has_table('central_contas')

def deny(db, actor, message):
    # Desfaz a tentativa; grava somente a negativa, sem valores secretos.
    db.rollback()
    log = registrar(db, usuario_id=actor.id if actor else None, acao='central_acesso_negado', entidade='central', depois={'motivo': message, 'resultado': 'negado'})
    log.categoria = 'falha_acesso'
    db.commit()
    raise HTTPException(403, message)

def audit(db, actor, action, entity, ident, before, after, reason):
    denied = 'negad' in action
    log = registrar(db, usuario_id=actor.id, acao='central_' + action, entidade=entity,
                    entidade_id=str(ident), antes=before, depois={'valores': after, 'justificativa': reason, 'resultado': 'negado' if denied else 'sucesso'})
    if denied:
        log.categoria = 'falha_acesso'

@contextmanager
def mutation(db):
    # Um mutex transacional global também serializa alterações de vínculos/limites.
    # PostgreSQL: vale entre processos e entre os dois serviços.
    with _lock:
        if db.get_bind().dialect.name == 'postgresql':
            db.execute(text('SELECT pg_advisory_xact_lock(7349102301)'))
        elif db.get_bind().dialect.name == 'sqlite':
            if not db.connection().connection.driver_connection.in_transaction:
                db.execute(text('BEGIN IMMEDIATE'))
        try:
            yield
            db.commit()
        except Exception:
            db.rollback()
            raise

def check_cargo(cargo):
    if cargo not in CARGOS:
        raise HTTPException(422, 'Cargo inválido.')

def occupancy(db, cargo, setor_id=0, exclude=None):
    q = db.query(ContaCentral).join(Usuario, Usuario.id == ContaCentral.usuario_id).filter(
        Usuario.ativo.is_(True), ContaCentral.estado.in_(['ativo', 'pendente']))
    if exclude:
        q = q.filter(ContaCentral.usuario_id != exclude)
    if setor_id:
        q = q.join(Vinculo, Vinculo.usuario_id == ContaCentral.usuario_id).filter(Vinculo.setor_id == setor_id, Vinculo.cargo == cargo)
    else:
        q = q.filter(ContaCentral.cargo == cargo)
    return q.count()

def check_limit(db, cargo, setor_id=0, exclude=None):
    rule = db.get(Limite, (cargo, setor_id))
    if not rule and setor_id:
        return  # específico opcional; global é obrigatório
    if not rule or not rule.habilitado:
        raise HTTPException(409, f'Cadastro de {cargo} não liberado. Configure o limite global.')
    if occupancy(db, cargo, setor_id, exclude) >= rule.maximo:
        raise HTTPException(409, f'Limite de {cargo} atingido no contexto {setor_id or "empresa"}.')

def validate_links(db, uid, links):
    seen = set()
    for link in links:
        sid, cargo, parent = link['setor_id'], link['cargo'], link.get('responsavel_id')
        check_cargo(cargo)
        if sid in seen:
            raise HTTPException(422, 'Setor repetido.')
        seen.add(sid)
        sector = db.get(Setor, sid)
        previous = db.query(Vinculo).filter_by(usuario_id=uid, setor_id=sid).first() if uid else None
        unchanged = bool(previous and previous.cargo == cargo and previous.responsavel_id == parent)
        if not sector or (not sector.ativo and not unchanged) or cargo not in sector.cargos:
            raise HTTPException(422, 'Setor inativo ou cargo não autorizado no setor.')
        if cargo == 'dono':
            if parent:
                raise HTTPException(422, 'Dono não possui responsável hierárquico.')
            continue
        if not parent or parent == uid:
            raise HTTPException(422, 'Informe um responsável válido.')
        pv = db.query(Vinculo).filter_by(usuario_id=parent, setor_id=sid).first()
        pu = db.get(Usuario, parent)
        parent_account = db.get(ContaCentral, parent)
        if not pv or not pu or not pu.ativo or not pu.senha_definida or (parent_account and parent_account.estado != 'ativo') or RANK[pv.cargo] >= RANK[cargo]:
            raise HTTPException(422, 'Responsável deve estar ativo e possuir cargo superior no mesmo setor.')
        visited = {uid} if uid else set()
        current = parent
        while current:
            if current in visited:
                raise HTTPException(422, 'Vínculo criaria um ciclo na hierarquia.')
            visited.add(current)
            v = db.query(Vinculo).filter_by(usuario_id=current, setor_id=sid).first()
            current = v.responsavel_id if v else None
    # Também verifica subordinados após uma mudança do cargo do responsável.
    if uid:
        by_sector = {v['setor_id']: v for v in links}
        for child in db.query(Vinculo).filter_by(responsavel_id=uid):
            parent = by_sector.get(child.setor_id)
            if not parent or RANK[parent['cargo']] >= RANK[child.cargo]:
                raise HTTPException(409, 'Transfira os subordinados antes de remover ou reduzir o cargo do responsável.')

def effective(db, user, sid, permission):
    account = db.get(ContaCentral, user.id)
    if not user.ativo or not account or account.estado != 'ativo':
        return False, 'negado'
    sector = db.get(Setor, sid)
    member = db.query(Vinculo).filter_by(usuario_id=user.id, setor_id=sid).first()
    if not sector or not sector.ativo or not member or member.cargo not in sector.cargos or permission.split(':')[0] not in sector.modulos:
        return False, 'fora do escopo'
    exception = db.get(Excecao, (user.id, sid, permission))
    if exception:
        return exception.permitido, 'personalizado'
    rule = db.get(Regra, (sid, member.cargo, permission))
    return bool(rule and rule.permitido), 'herdado'

def revoke(db, uid):
    db.query(RefreshToken).filter_by(usuario_id=uid).update({'revogado': True})
    db.query(Sessao).filter_by(usuario_id=uid).delete()
    account = db.get(ContaCentral, uid)
    if account:
        account.versao_sessao += 1
    version = db.get(VersaoAutenticacao, uid)
    if not version:
        version = VersaoAutenticacao(usuario_id=uid, versao=0)
        db.add(version)
    version.versao += 1

def epoch(db, uid):
    version = db.get(VersaoAutenticacao, uid)
    return version.versao if version else 0

def protect_admin(db, uid):
    if uid in admins() and db.query(Usuario).filter(Usuario.id.in_(admins()), Usuario.perfil_id == 'administrador', Usuario.ativo.is_(True)).count() <= 1:
        raise HTTPException(409, 'Não é permitido desativar ou remover o último administrador central.')

def legacy_guard(db, user, permissions):
    """O legado não tem setor nos registros operacionais. Nega o escopo ambíguo.

    Usuários ainda não vinculados ao controle central mantêm o RBAC original.
    Usuários gerenciados não recebem acesso global por acidente.
    """
    if not installed(db):
        return
    if any(p == 'usuarios:write' for p in permissions):
        deny(db, user, 'Administre usuários pelo painel central ou pela API /governanca/convites.')
    account = db.get(ContaCentral, user.id)
    if not account:
        return
    if account.estado != 'ativo':
        deny(db, user, 'Conta bloqueada, desativada ou pendente.')
    if central_admin(user):
        return
    deny(db, user, 'Este endpoint legado não possui isolamento por setor. Acesso negado até integração do módulo.')
