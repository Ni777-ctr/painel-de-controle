import importlib.util
from pathlib import Path
import pytest
import pyotp
from fastapi import HTTPException
from sqlalchemy import inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.central.models import ContaCentral, Setor, Limite, Vinculo, Regra, Excecao, Sessao
from app.models.usuario import Usuario
from app.central.policy import mutation
from .test_central import REASON, limit, payload

def test_sector_limit_and_inactive_sector(setup):
    client, main, factory=setup
    s=client.put('/api/setores/0',json={**REASON,'nome':'Operação teste','descricao':'Dados sintéticos','ativo':True,'modulos':['programacao'],'cargos':['dono']}).json()['id']
    limit(client,'dono',5)
    limit(client,'dono',1,sid=s)
    data=payload(links=[{'setor_id':s,'cargo':'dono','responsavel_id':None}])
    assert client.put('/api/usuarios/0',json=data).status_code==200
    data['usuario']='segundo_teste'
    assert client.put('/api/usuarios/0',json=data).status_code==409
    assert client.put('/api/setores/'+str(s),json={**REASON,'nome':'Operação teste','descricao':'Dados sintéticos','ativo':False,'modulos':['programacao'],'cargos':['dono']}).status_code==200
    assert client.put('/api/usuarios/0',json=data).status_code==422
    with factory() as db:
        assert db.query(Vinculo).filter_by(setor_id=s).count()==1

def test_permission_three_states_over_http(setup):
    client, main, factory=setup
    with factory() as db:
        sector=Setor(nome='Setor de teste',ativo=True,modulos=['programacao'],cargos=['colaborador']);db.add(sector);db.flush();sid=sector.id
        db.add_all([ContaCentral(usuario_id=2,cargo='colaborador',estado='ativo'),Vinculo(usuario_id=2,setor_id=sid,cargo='colaborador')]);db.commit()
    base={**REASON,'setor_id':sid,'cargo':'colaborador','permissao':'programacao:read','estado':'permitido'}
    assert client.put('/api/permissoes',json=base).status_code==200
    base['usuario_id']=2;base['estado']='negado'
    assert client.put('/api/permissoes',json=base).status_code==200
    result=client.get(f'/api/permissoes/2/{sid}').json()
    assert next(p for p in result if p['permissao']=='programacao:read')=={'permissao':'programacao:read','permitido':False,'origem':'personalizado'}
    base['estado']='herdar'
    assert client.put('/api/permissoes',json=base).status_code==200
    result=client.get(f'/api/permissoes/2/{sid}').json()
    assert next(p for p in result if p['permissao']=='programacao:read')['permitido'] is True

def test_delegated_registration_hierarchy_and_no_escalation(setup):
    client, main, factory=setup
    with factory() as db:
        sector=Setor(nome='Setor de teste',ativo=True,modulos=['programacao'],cargos=['dono','gerente','coordenador','colaborador']);db.add(sector);db.flush();sid=sector.id
        db.add_all([ContaCentral(usuario_id=2,cargo='dono',estado='ativo'),Vinculo(usuario_id=2,setor_id=sid,cargo='dono')]);db.commit()
    limit(client,'dono',5,delegate=True);limit(client,'gerente',5)
    login=main.post('/auth/login',json={'usuario':'operador_teste','senha':'SenhaTeste123!'}).json();headers={'Authorization':'Bearer '+login['access_token']}
    data=payload('gerente_teste','gerente',[{'setor_id':sid,'cargo':'gerente','responsavel_id':2}])
    result=main.post('/governanca/convites',json=data,headers=headers)
    assert result.status_code==201,result.text
    data.update(usuario='outro_dono',cargo='dono');data['vinculos'][0]['cargo']='dono';data['vinculos'][0]['responsavel_id']=None
    assert main.post('/governanca/convites',json=data,headers=headers).status_code==403
    data=payload('admin_indevido','gerente',[{'setor_id':sid,'cargo':'gerente','responsavel_id':2}]);data['perfil_id']='administrador'
    assert main.post('/governanca/convites',json=data,headers=headers).status_code==403
    assert main.get('/governanca/contextos/999/permissoes',headers=headers).status_code==403

def test_scoped_users_cannot_access_legacy_global_endpoints(setup):
    client, main, factory=setup
    with factory() as db:
        db.add(ContaCentral(usuario_id=2,cargo='colaborador',estado='ativo'));db.commit()
    login=main.post('/auth/login',json={'usuario':'operador_teste','senha':'SenhaTeste123!'}).json();headers={'Authorization':'Bearer '+login['access_token']}
    assert main.get('/programacao',headers=headers).status_code==403
    result=main.get('/busca?q=teste',headers=headers)
    assert result.status_code==200
    assert result.json()['resultados']==[]

def test_mfa_admin_login_and_revoked_pending_token(setup):
    client, main, factory=setup
    secret=pyotp.random_base32()
    with factory() as db:
        user=db.get(Usuario,1);user.mfa_habilitado=True;user.mfa_secret=secret;db.commit()
    result=client.post('/api/login',json={'usuario':'admin_teste','senha':'SenhaTeste123!'})
    assert result.json()['etapa']=='mfa'
    result=client.post('/api/login/continuar',json={'codigo':pyotp.TOTP(secret).now()})
    assert result.status_code==200,result.text
    pending=main.post('/auth/login',json={'usuario':'admin_teste','senha':'SenhaTeste123!'}).json()['mfa_token']
    client.headers['X-CSRF-Token']=result.json()['csrf']
    assert client.post('/api/usuarios/1/sessoes',json=REASON).status_code==200
    assert main.post('/auth/mfa/validar',json={'mfa_token':pending,'codigo':pyotp.TOTP(secret).now()}).status_code==401
    assert client.get('/api/session').status_code==401

def test_edit_name_allowed_after_limit_reduction(setup):
    client, main, factory=setup
    limit(client,'dono',1)
    made=client.put('/api/usuarios/0',json=payload()).json()
    main.post('/auth/definir-senha',json={'convite_token':made['convite'],'senha':'SenhaConvite123!'})
    limit(client,'dono',0)
    data=payload(uid=True);data['nome']='Nome revisado de teste'
    assert client.put('/api/usuarios/'+str(made['id']),json=data).status_code==200

def test_migration_upgrade_downgrade_preserves_users(setup):
    client, main, factory=setup
    path=Path(__file__).parents[1]/'alembic/versions/0011_central_local.py'
    spec=importlib.util.spec_from_file_location('central_migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with factory().get_bind().begin() as connection:
        module.op=Operations(MigrationContext.configure(connection))
        module.downgrade()
        assert 'central_contas' not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql('SELECT count(*) FROM usuarios').scalar()==2
        module.upgrade()
        assert 'central_contas' in inspect(connection).get_table_names()

def test_user_audit_serializes_existing_login_timestamp(setup):
    client, main, factory=setup
    limit(client,'dono',3)
    data=payload('admin_teste',uid=True)
    data.update(nome='Administrador revisado de teste',perfil_id='administrador')
    result=client.put('/api/usuarios/1',json=data)
    assert result.status_code==200,result.text

def test_global_cargo_cannot_hide_higher_sector_role(setup):
    client, main, factory=setup
    sector=client.put('/api/setores/0',json={**REASON,'nome':'Setor teste','descricao':'Isolado','ativo':True,'modulos':['programacao'],'cargos':['dono','colaborador']}).json()['id']
    limit(client,'colaborador',5)
    data=payload('cargo_inconsistente','colaborador',[{'setor_id':sector,'cargo':'dono','responsavel_id':None}])
    assert client.put('/api/usuarios/0',json=data).status_code==422
