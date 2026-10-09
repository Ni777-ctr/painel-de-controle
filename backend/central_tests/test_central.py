from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException
import pytest
from app.central.main import UserInput, save_user_transaction
from app.central.models import ContaCentral, Setor, Limite, Vinculo, Regra, Excecao, Sessao
from app.central.policy import mutation, effective, validate_links
from app.models.usuario import Usuario
from app.models.auditoria import AuditLog

REASON = {'confirmar': True, 'justificativa': 'Alteração de teste isolado'}

def limit(client, cargo, maximum, delegate=False, sid=0):
    return client.put(f'/api/limites/{cargo}/{sid}',json={**REASON,'maximo':maximum,'habilitado':True,'alerta_percentual':80,'pode_cadastrar':delegate})

def payload(name='novo_teste',cargo='dono',links=None,uid=False):
    return {**REASON,'nome':'Pessoa de teste','usuario':name,'email':None,'perfil_id':'programacao','cargo':cargo,'estado':'ativo' if uid else 'pendente','vinculos':links or []}

def test_common_user_denied_and_audited(setup):
    client, main, factory = setup
    result=client.post('/api/login',json={'usuario':'operador_teste','senha':'SenhaTeste123!'})
    assert result.status_code==403
    with factory() as db:
        assert db.query(AuditLog).filter_by(acao='central_acesso_negado').count()==1

def test_unauthenticated_denied(setup):
    client, main, factory=setup
    client.cookies.clear()
    assert client.get('/api/dados').status_code==401

def test_csrf_origin_host_and_confirmation(setup):
    client, main, factory=setup
    assert client.put('/api/limites/dono/0',json={**REASON,'maximo':5,'habilitado':True,'alerta_percentual':80},headers={'X-CSRF-Token':'errado'}).status_code==403
    assert client.post('/api/logout',json={},headers={'Origin':'https://outro.site'}).status_code==403
    assert client.get('/',headers={'Host':'evil.example'}).status_code==400
    assert client.put('/api/limites/dono/0',json={**REASON,'confirmar':False,'maximo':5,'habilitado':True,'alerta_percentual':80}).status_code==422

def test_limits_persist_invitation_reserves_and_activation(setup):
    client, main, factory=setup
    assert limit(client,'dono',1).status_code==200
    created=client.put('/api/usuarios/0',json=payload())
    assert created.status_code==200,created.text
    assert client.put('/api/usuarios/0',json=payload('outro_teste')).status_code==409
    assert main.post('/auth/definir-senha',json={'convite_token':created.json()['convite'],'senha':'SenhaConvite123!'}).status_code==200
    with factory() as db:
        assert db.get(Limite,('dono',0)).maximo==1
        assert db.get(ContaCentral,created.json()['id']).estado=='ativo'
        assert db.query(AuditLog).filter_by(acao='central_usuario_salvo').count()==1

def test_unconfigured_limits_deny(setup):
    client, main, factory=setup
    assert client.put('/api/usuarios/0',json=payload()).status_code==409

def test_reduced_limit_preserves_accounts(setup):
    client, main, factory=setup
    limit(client,'dono',2)
    client.put('/api/usuarios/0',json=payload())
    result=limit(client,'dono',0)
    assert result.json()['excedido'] is True
    with factory() as db:
        assert db.query(Usuario).filter_by(usuario='novo_teste',ativo=True).count()==1

def test_last_admin_protected(setup):
    client, main, factory=setup
    data=payload('admin_teste',uid=True);data.update(perfil_id='administrador',estado='desativado')
    assert client.put('/api/usuarios/1',json=data).status_code==409

def test_revoke_existing_access_token_and_refresh(setup):
    client, main, factory=setup
    login=main.post('/auth/login',json={'usuario':'operador_teste','senha':'SenhaTeste123!'}).json()
    headers={'Authorization':'Bearer '+login['access_token']}
    assert main.get('/auth/me',headers=headers).status_code==200
    assert client.post('/api/usuarios/2/sessoes',json=REASON).status_code==200
    assert main.get('/auth/me',headers=headers).status_code==401
    assert main.post('/auth/refresh',json={'refresh_token':login['refresh_token']}).status_code==401

def test_hierarchy_cycles_and_sector_boundaries(setup):
    client, main, factory=setup
    with factory() as db:
        s=Setor(nome='Setor teste',ativo=True,modulos=['programacao'],cargos=['dono','gerente','coordenador','colaborador']);db.add(s);db.flush()
        sid=s.id
        db.add(Vinculo(usuario_id=1,setor_id=sid,cargo='dono'));db.commit()
        with pytest.raises(HTTPException):
            validate_links(db,2,[{'setor_id':sid,'cargo':'gerente','responsavel_id':2}])
        with pytest.raises(HTTPException):
            validate_links(db,2,[{'setor_id':sid+1,'cargo':'gerente','responsavel_id':1}])
        validate_links(db,2,[{'setor_id':sid,'cargo':'gerente','responsavel_id':1}])
        db.add(Vinculo(usuario_id=2,setor_id=sid,cargo='gerente',responsavel_id=1));db.commit()
        with pytest.raises(HTTPException):
            validate_links(db,1,[{'setor_id':sid,'cargo':'colaborador','responsavel_id':2}])

def test_permission_inheritance_exceptions_and_default_deny(setup):
    client, main, factory=setup
    with factory() as db:
        s=Setor(nome='Setor teste',ativo=True,modulos=['programacao'],cargos=['colaborador']);db.add(s);db.flush()
        sid=s.id
        db.add_all([ContaCentral(usuario_id=2,cargo='colaborador',estado='ativo'),Vinculo(usuario_id=2,setor_id=sid,cargo='colaborador'),Regra(setor_id=sid,cargo='colaborador',permissao='programacao:read',permitido=True)]);db.commit()
        user=db.get(Usuario,2)
        assert effective(db,user,sid,'programacao:read')==(True,'herdado')
        assert effective(db,user,sid,'programacao:write')==(False,'herdado')
        assert effective(db,user,sid+1,'programacao:read')[0] is False
        db.add(Excecao(usuario_id=2,setor_id=sid,permissao='programacao:read',permitido=False));db.commit()
        assert effective(db,user,sid,'programacao:read')==(False,'personalizado')
        db.get(Excecao,(2,sid,'programacao:read')).permitido=True;db.commit()
        assert effective(db,user,sid,'programacao:read')==(True,'personalizado')
        s.ativo=False;db.commit()
        assert not effective(db,user,sid,'programacao:read')[0]

def test_block_stops_login_and_preserves_history(setup):
    client, main, factory=setup
    limit(client,'colaborador',10)
    data=payload('operador_teste','colaborador',uid=True);data['estado']='bloqueado'
    assert client.put('/api/usuarios/2',json=data).status_code==200
    assert main.post('/auth/login',json={'usuario':'operador_teste','senha':'SenhaTeste123!'}).status_code==401
    with factory() as db:
        assert db.get(Usuario,2) is not None
        assert db.query(AuditLog).filter_by(entidade_id='2',acao='central_usuario_salvo').count()==1

def test_permission_http_rejects_outside_scope_and_self(setup):
    client, main, factory=setup
    data={**REASON,'setor_id':999,'usuario_id':2,'permissao':'programacao:read','estado':'permitido'}
    assert client.put('/api/permissoes',json=data).status_code==422

def test_concurrent_invites_do_not_exceed_limit(setup):
    client, main, factory=setup
    limit(client,'dono',1)
    def create(n):
        with factory() as db:
            try:
                with mutation(db):
                    save_user_transaction(db,db.get(Usuario,1),0,UserInput(**payload(f'concorrente_{n}')))
                return True
            except HTTPException:
                return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(create,range(2)))
    assert sum(results)==1
    with factory() as db:
        assert db.query(ContaCentral).filter_by(cargo='dono').count()==1

def test_html_assets_and_no_audit_mutation(setup):
    client, main, factory=setup
    assert client.get('/').status_code==200
    assert 'Nithicom' in client.get('/').text
    assert client.get('/assets/app.js').status_code==200
    assert client.delete('/api/historico').status_code==405

def test_legacy_cannot_bypass_creation_controls(setup):
    client, main, factory=setup
    login=main.post('/auth/login',json={'usuario':'admin_teste','senha':'SenhaTeste123!'}).json()
    headers={'Authorization':'Bearer '+login['access_token']}
    assert main.post('/auth/convite',json={'nome':'Teste','usuario':'bypass','perfil_id':'programacao'},headers=headers).status_code==403
