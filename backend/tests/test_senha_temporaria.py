"""Senha temporaria (primeiro acesso) e regra dos 6 meses (expiracao por
parametro global 'senha_validade_dias')."""
from datetime import datetime, timedelta, timezone

from app.models.parametro import ParametroGlobal
from app.models.usuario import Usuario
from app.security import hash_senha
from tests.conftest import criar_perfil, criar_usuario


def test_senha_temporaria_bloqueia_login_normal_e_forca_troca(client, db_session, perfil_admin):
    creds = criar_usuario(db_session, usuario="novato", perfil_id=perfil_admin)
    db = db_session()
    db.query(Usuario).filter(Usuario.usuario == "novato").update({"deve_trocar_senha": True})
    db.commit()
    db.close()

    r = client.post("/auth/login", json=creds)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["senha_pendente"] is True
    assert corpo["senha_pendente_motivo"] == "primeiro_acesso"
    assert corpo.get("access_token") is None
    token = corpo["senha_pendente_token"]

    # O token de senha pendente nao funciona como access_token normal.
    r = client.get("/usuarios", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401

    # Troca a senha e ja recebe os tokens finais (sem precisar logar de novo).
    r = client.post("/auth/trocar-senha-obrigatoria", json={"senha_pendente_token": token, "nova_senha": "novaSenha123"})
    assert r.status_code == 200
    assert r.json()["senha_pendente"] is False
    assert r.json().get("access_token") is not None

    # Login seguinte com a nova senha: sem pendencia.
    r = client.post("/auth/login", json={"usuario": "novato", "senha": "novaSenha123"})
    assert r.status_code == 200
    assert r.json()["senha_pendente"] is False


def test_senha_expirada_pela_regra_dos_6_meses(client, db_session, perfil_admin):
    creds = criar_usuario(db_session, usuario="antigo", perfil_id=perfil_admin)
    db = db_session()
    db.add(ParametroGlobal(chave="senha_validade_dias", valor=180, descricao="teste"))
    ha_1_ano = datetime.now(timezone.utc) - timedelta(days=365)
    db.query(Usuario).filter(Usuario.usuario == "antigo").update({"senha_alterada_em": ha_1_ano})
    db.commit()
    db.close()

    r = client.post("/auth/login", json=creds)
    assert r.status_code == 200
    assert r.json()["senha_pendente"] is True
    assert r.json()["senha_pendente_motivo"] == "expirada"


def test_senha_validade_desativada_por_parametro(client, db_session, perfil_admin):
    creds = criar_usuario(db_session, usuario="antigo2", perfil_id=perfil_admin)
    db = db_session()
    db.add(ParametroGlobal(chave="senha_validade_dias", valor=0, descricao="desativado"))
    ha_2_anos = datetime.now(timezone.utc) - timedelta(days=730)
    db.query(Usuario).filter(Usuario.usuario == "antigo2").update({"senha_alterada_em": ha_2_anos})
    db.commit()
    db.close()

    r = client.post("/auth/login", json=creds)
    assert r.status_code == 200
    assert r.json()["senha_pendente"] is False  # validade=0 desativa a expiracao


def test_troca_de_senha_voluntaria(client, admin_headers):
    r = client.post("/auth/trocar-senha", json={"senha_atual": "senhaErrada", "nova_senha": "outra123"}, headers=admin_headers)
    assert r.status_code == 401

    r = client.post("/auth/trocar-senha", json={"senha_atual": "123456", "nova_senha": "outra123"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["deve_trocar_senha"] is False

    r = client.post("/auth/login", json={"usuario": "admin", "senha": "outra123"})
    assert r.status_code == 200


def test_admin_redefine_senha_forca_troca_no_proximo_login(client, admin_headers, db_session):
    r = client.post("/auth/convite", json={"nome": "Fulano", "usuario": "fulano2", "perfil_id": "administrador"}, headers=admin_headers)
    convite = r.json()["convite_token"]
    client.post("/auth/definir-senha", json={"convite_token": convite, "senha": "senhaFulano123"})
    fulano_id = r.json()["usuario_id"]

    r = client.patch(f"/usuarios/{fulano_id}", json={"senha": "senhaTemporariaAdmin"}, headers=admin_headers)
    assert r.status_code == 200

    r = client.post("/auth/login", json={"usuario": "fulano2", "senha": "senhaTemporariaAdmin"})
    assert r.status_code == 200
    assert r.json()["senha_pendente"] is True
    assert r.json()["senha_pendente_motivo"] == "primeiro_acesso"


def test_desligamento_revoga_sessoes_ativas(client, admin_headers, db_session):
    creds = criar_usuario(db_session, usuario="demitido", perfil_id="administrador")
    r = client.post("/auth/login", json=creds)
    tokens = r.json()
    headers_demitido = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.get("/usuarios", headers=headers_demitido)
    assert r.status_code == 200

    db = db_session()
    usuario_id = db.query(Usuario).filter(Usuario.usuario == "demitido").first().id
    db.close()

    r = client.delete(f"/usuarios/{usuario_id}", headers=admin_headers)
    assert r.status_code == 204

    # Access token antigo (ainda nao expirado) deixa de funcionar.
    r = client.get("/usuarios", headers=headers_demitido)
    assert r.status_code == 401

    # Refresh tambem deixa de funcionar (revogado explicitamente).
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401
