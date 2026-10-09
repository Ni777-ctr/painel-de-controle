"""Etapas 1 e 5: login/JWT, refresh token, bloqueio por tentativas, convite
de senha e 2FA (TOTP)."""
import pyotp

from tests.conftest import criar_usuario


def test_login_sucesso(client, admin_headers):
    r = client.get("/auth/me", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["usuario"] == "admin"


def test_login_senha_errada(client, usuario_admin):
    r = client.post("/auth/login", json={"usuario": "admin", "senha": "errada"})
    assert r.status_code == 401


def test_rota_protegida_sem_token(client, usuario_admin):
    r = client.get("/usuarios")
    assert r.status_code == 401


def test_bloqueio_apos_5_tentativas_e_desbloqueio_manual(client, usuario_admin, admin_headers):
    for _ in range(4):
        r = client.post("/auth/login", json={"usuario": "admin", "senha": "errada"})
        assert r.status_code == 401

    # A 5a tentativa cruza o limite e ja informa o bloqueio (423), nao 401.
    r = client.post("/auth/login", json={"usuario": "admin", "senha": "errada"})
    assert r.status_code == 423

    # Mesmo com a senha certa, continua bloqueado.
    r = client.post("/auth/login", json={"usuario": "admin", "senha": "123456"})
    assert r.status_code == 423

    r = client.post("/auth/usuarios/1/desbloquear", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["bloqueado_ate"] is None

    r = client.post("/auth/login", json={"usuario": "admin", "senha": "123456"})
    assert r.status_code == 200


def test_refresh_token_rotaciona_e_revoga(client, usuario_admin):
    r = client.post("/auth/login", json={"usuario": "admin", "senha": "123456"})
    tokens = r.json()

    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    novo_refresh = r.json()["refresh_token"]
    assert novo_refresh != tokens["refresh_token"]

    # O refresh antigo foi revogado (rotacao).
    r = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401

    # Logout revoga o novo.
    r = client.post("/auth/logout", json={"refresh_token": novo_refresh})
    assert r.status_code == 204
    r = client.post("/auth/refresh", json={"refresh_token": novo_refresh})
    assert r.status_code == 401


def test_convite_e_definicao_de_senha(client, admin_headers):
    r = client.post(
        "/auth/convite",
        json={"nome": "Fulano", "usuario": "fulano", "perfil_id": "administrador"},
        headers=admin_headers,
    )
    assert r.status_code == 201
    convite_token = r.json()["convite_token"]

    # Nao pode logar antes de definir a senha.
    r = client.post("/auth/login", json={"usuario": "fulano", "senha": "qualquer"})
    assert r.status_code == 403

    r = client.post("/auth/definir-senha", json={"convite_token": convite_token, "senha": "novaSenha123"})
    assert r.status_code == 200
    assert r.json()["senha_definida"] is True

    r = client.post("/auth/login", json={"usuario": "fulano", "senha": "novaSenha123"})
    assert r.status_code == 200

    # Convite ja usado nao funciona de novo.
    r = client.post("/auth/definir-senha", json={"convite_token": convite_token, "senha": "outraSenha"})
    assert r.status_code == 400


def test_mfa_setup_login_e_desabilitar(client, admin_headers, db_session):
    r = client.post("/auth/mfa/iniciar", headers=admin_headers)
    assert r.status_code == 200
    secret = r.json()["secret"]
    assert "otpauth://" in r.json()["otpauth_uri"]

    r = client.post("/auth/mfa/confirmar", json={"codigo": "000000"}, headers=admin_headers)
    assert r.status_code == 401

    r = client.post("/auth/mfa/confirmar", json={"codigo": pyotp.TOTP(secret).now()}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["mfa_habilitado"] is True

    # Login agora exige 2a etapa.
    r = client.post("/auth/login", json={"usuario": "admin", "senha": "123456"})
    assert r.status_code == 200
    assert r.json()["mfa_pendente"] is True
    assert r.json().get("access_token") is None
    mfa_token = r.json()["mfa_token"]

    # mfa_token nao pode ser usado como access_token em rota protegida.
    r = client.get("/usuarios", headers={"Authorization": f"Bearer {mfa_token}"})
    assert r.status_code == 401

    r = client.post("/auth/mfa/validar", json={"mfa_token": mfa_token, "codigo": "000000"})
    assert r.status_code == 401

    r = client.post("/auth/mfa/validar", json={"mfa_token": mfa_token, "codigo": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    headers2 = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/auth/mfa/desabilitar", json={"senha": "errada"}, headers=headers2)
    assert r.status_code == 401
    r = client.post("/auth/mfa/desabilitar", json={"senha": "123456"}, headers=headers2)
    assert r.status_code == 200
    assert r.json()["mfa_habilitado"] is False

    r = client.post("/auth/login", json={"usuario": "admin", "senha": "123456"})
    assert r.json()["mfa_pendente"] is False
