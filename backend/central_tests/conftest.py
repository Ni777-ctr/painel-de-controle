import os
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['JWT_SECRET_KEY'] = 'chave-isolada-de-teste-nao-utilizar-em-producao'
os.environ['CENTRAL_ADMIN_IDS'] = '1'
os.environ['MFA_OBRIGATORIO_ENFORCE'] = 'false'
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.central.main import app as central
from app.main import app as original
from app.models.usuario import Perfil, Usuario
from app.security import hash_senha, limitador_login

@pytest.fixture
def setup():
    limitador_login.resetar()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([Perfil(id='administrador', nome='Administrador', categoria='GESTAO', permissoes=['*']),
                    Perfil(id='programacao', nome='Programação', categoria='OPERACAO', permissoes=['programacao:read','programacao:write'])])
        db.flush()
        db.add_all([Usuario(id=1,nome='Admin de teste',usuario='admin_teste',senha_hash=hash_senha('SenhaTeste123!'),perfil_id='administrador'),
                    Usuario(id=2,nome='Operador de teste',usuario='operador_teste',senha_hash=hash_senha('SenhaTeste123!'),perfil_id='programacao')])
        db.commit()
    def override():
        with factory() as db:
            yield db
    central.dependency_overrides[get_db] = override
    original.dependency_overrides[get_db] = override
    client = TestClient(central, headers={'Origin':'http://testserver'})
    main_client = TestClient(original)
    result = client.post('/api/login',json={'usuario':'admin_teste','senha':'SenhaTeste123!'})
    assert result.status_code == 200, result.text
    client.headers['X-CSRF-Token'] = result.json()['csrf']
    yield client, main_client, factory
    central.dependency_overrides.clear()
    original.dependency_overrides.clear()
    engine.dispose()
