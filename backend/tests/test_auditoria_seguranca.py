"""Auditoria visivel (categorias, filtros, IP/UA) e endurecimento para publicacao."""
import pyotp
import pytest

from app.config import Settings
from app.models.usuario import Usuario
from tests.conftest import criar_perfil, criar_usuario


def _login(client, cred):
    r = client.post("/auth/login", json=cred)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------- auditoria ----------------
def test_classificacao_de_acoes():
    from app.auditoria_utils import classificar_acao as c

    assert c("login_sucesso") == "login" and c("mfa_habilitado") == "login" and c("senha_trocada_voluntariamente") == "login"
    assert c("login_falhou") == "falha_acesso" and c("usuario_bloqueado") == "falha_acesso" and c("acesso_negado") == "falha_acesso"
    assert c("exportacao_obras") == "exportacao"
    assert c("usuario_desativado") == "exclusao" and c("veiculo_excluido") == "exclusao" and c("sessoes_revogadas") == "exclusao"
    assert c("obra_status_alterado") == "alteracao" and c("fatura_emitida") == "alteracao"
    assert c("notificacoes_processadas") == "sistema"


def test_registra_ip_e_user_agent(client, usuario_admin):
    r = client.post("/auth/login", json=usuario_admin, headers={"User-Agent": "Mozilla/5.0 PWA-Teste"})
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    logs = client.get("/auditoria", params={"categoria": "login"}, headers=h).json()
    assert logs and logs[0]["user_agent"] == "Mozilla/5.0 PWA-Teste"
    assert logs[0]["ip"] == "testclient"
    assert logs[0]["usuario_nome"] == "Admin"
    assert r.headers["x-request-id"]


def test_login_com_usuario_inexistente_e_auditado_sem_vazar_ao_cliente(client, admin_headers):
    r = client.post("/auth/login", json={"usuario": "fantasma", "senha": "x"})
    assert r.status_code == 401 and r.json()["detail"] == "Usuario ou senha invalidos."
    logs = client.get("/auditoria", params={"acao": "login_usuario_inexistente"}, headers=admin_headers).json()
    assert len(logs) == 1 and logs[0]["categoria"] == "falha_acesso" and logs[0]["usuario_id"] is None
    assert logs[0]["depois"]["usuario_tentado"] == "fantasma"


def test_senha_incorreta_e_bloqueio_viram_falha_de_acesso(client, admin_headers, db_session):
    criar_usuario(db_session, usuario="vitima", perfil_id="administrador", senha="certa")
    for _ in range(5):
        client.post("/auth/login", json={"usuario": "vitima", "senha": "errada"})
    falhas = client.get("/auditoria", params={"categoria": "falha_acesso"}, headers=admin_headers).json()
    assert {l["acao"] for l in falhas} >= {"login_falhou", "usuario_bloqueado"}


def test_filtros_e_paginacao(client, admin_headers, db_session):
    for i in range(7):
        client.post("/auth/login", json={"usuario": f"nao{i}", "senha": "x"})
    pag = client.get("/auditoria/pagina", params={"categoria": "falha_acesso", "limite": 3}, headers=admin_headers).json()
    assert pag["total"] == 7 and len(pag["itens"]) == 3 and pag["limite"] == 3
    prox = client.get("/auditoria/pagina", params={"categoria": "falha_acesso", "limite": 3, "offset": 6}, headers=admin_headers).json()
    assert len(prox["itens"]) == 1
    # filtros por ip, acao e data
    assert client.get("/auditoria/pagina", params={"ip": "1.2.3.4"}, headers=admin_headers).json()["total"] == 0
    assert client.get("/auditoria/pagina", params={"ip": "testclient", "acao": "inexistente"}, headers=admin_headers).json()["total"] == 7
    assert client.get("/auditoria/pagina", params={"data_inicio": "2999-01-01"}, headers=admin_headers).json()["total"] == 0
    assert client.get("/auditoria/pagina", params={"data_inicio": "2000-01-01", "data_fim": "2999-01-01", "categoria": "falha_acesso"}, headers=admin_headers).json()["total"] == 7
    assert client.get("/auditoria", params={"categoria": "bogus"}, headers=admin_headers).status_code == 422


def test_resumo_da_auditoria(client, admin_headers):
    for i in range(3):
        client.post("/auth/login", json={"usuario": f"nope{i}", "senha": "x"})
    r = client.get("/auditoria/resumo", params={"dias": 1}, headers=admin_headers).json()
    assert r["por_categoria"]["falha_acesso"] == 3 and r["por_categoria"]["login"] >= 1
    assert r["falhas_acesso_por_ip"][0] == {"ip": "testclient", "total": 3}
    assert r["top_acoes"][0]["acao"] == "login_usuario_inexistente"


def test_historico_exige_permissao_e_acesso_negado_e_registrado(client, db_session, admin_headers):
    criar_perfil(db_session, perfil_id="curioso", permissoes=["obras:read"])
    h = _login(client, criar_usuario(db_session, usuario="curioso", perfil_id="curioso"))
    for rota in ("/auditoria", "/auditoria/pagina", "/auditoria/resumo"):
        assert client.get(rota, headers=h).status_code == 403
    logs = client.get("/auditoria", params={"acao": "acesso_negado"}, headers=admin_headers).json()
    assert len(logs) == 3 and logs[0]["categoria"] == "falha_acesso" and logs[0]["usuario_nome"] == "curioso"
    assert "auditoria:read" in logs[0]["depois"]["necessarias"]


def test_nao_existe_edicao_nem_exclusao_de_log(client, admin_headers):
    assert client.delete("/auditoria/1", headers=admin_headers).status_code in (404, 405)
    assert client.patch("/auditoria/1", json={}, headers=admin_headers).status_code in (404, 405)
    assert client.put("/auditoria/1", json={}, headers=admin_headers).status_code in (404, 405)


def test_log_manual_do_usuario_e_classificado(client, admin_headers):
    r = client.post("/auditoria", json={"acao": "exportacao_manual_csv", "entidade": "frota"}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["categoria"] == "exportacao"


# ---------------- rate limit ----------------
def test_rate_limit_de_login_por_ip(client, monkeypatch):
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router.settings, "LOGIN_RATE_LIMIT_MAX", 3)
    codigos = [client.post("/auth/login", json={"usuario": "x", "senha": "y"}).status_code for _ in range(5)]
    assert codigos == [401, 401, 401, 429, 429]
    r = client.post("/auth/login", json={"usuario": "x", "senha": "y"})
    assert r.headers["retry-after"]


# ---------------- 2FA obrigatorio ----------------
def test_mfa_obrigatorio_bloqueia_sessao_ate_configurar(client, db_session, monkeypatch):
    from app.routers import auth as auth_router

    monkeypatch.setattr(auth_router.settings, "MFA_OBRIGATORIO_ENFORCE", True)
    criar_perfil(db_session, perfil_id="administrador", permissoes=["*"], categoria="GESTAO") if False else None
    cred = {"usuario": "admin", "senha": "123456"}
    criar_perfil(db_session, perfil_id="administrador", permissoes=["*"])
    db = db_session()
    db.add(Usuario(nome="A", usuario="admin", senha_hash=__import__("app.security", fromlist=["x"]).hash_senha("123456"), perfil_id="administrador"))
    db.commit()
    db.close()

    r = client.post("/auth/login", json=cred).json()
    assert r["mfa_configuracao_pendente"] is True and r["access_token"] is None
    setup = {"Authorization": f"Bearer {r['mfa_setup_token']}"}

    # O token restrito NAO abre rotas normais...
    assert client.get("/auth/me", headers=setup).status_code == 401
    assert client.get("/obras", headers=setup).status_code == 401
    # ...mas permite configurar o 2FA.
    seg = client.post("/auth/mfa/iniciar", headers=setup).json()["secret"]
    assert client.post("/auth/mfa/confirmar", json={"codigo": "000000"}, headers=setup).status_code == 401
    assert client.post("/auth/mfa/confirmar", json={"codigo": pyotp.TOTP(seg).now()}, headers=setup).status_code == 200

    # Proximo login ja exige o codigo e entao emite sessao normal.
    r2 = client.post("/auth/login", json=cred).json()
    assert r2["mfa_pendente"] is True
    ok = client.post("/auth/mfa/validar", json={"mfa_token": r2["mfa_token"], "codigo": pyotp.TOTP(seg).now()})
    assert ok.status_code == 200 and ok.json()["access_token"]


def test_mfa_nao_obrigatorio_por_padrao(client, usuario_admin):
    r = client.post("/auth/login", json=usuario_admin).json()
    assert r["access_token"] and not r["mfa_configuracao_pendente"]


# ---------------- configuracao / publicacao ----------------
def _cfg(**kw):
    base = dict(ENVIRONMENT="production", JWT_SECRET_KEY="x" * 40, DATABASE_URL="postgresql://u:p@ep-x.neon.tech/db?sslmode=require",
                CORS_ORIGINS="https://app.eletrogestor.com.br")
    return Settings(_env_file=None, **{**base, **kw})


def test_producao_aceita_configuracao_segura():
    assert _cfg().validar_para_producao() == []


@pytest.mark.parametrize("kw,trecho", [
    (dict(JWT_SECRET_KEY="troque-esta-chave-antes-de-ir-para-producao"), "JWT_SECRET_KEY"),
    (dict(JWT_SECRET_KEY="curta"), "JWT_SECRET_KEY"),
    (dict(DATABASE_URL="sqlite:///./dev.db"), "DATABASE_URL"),
    (dict(DATABASE_URL="postgresql+psycopg2://eletrogestor:eletrogestor@localhost:5432/eletrogestor"), "DATABASE_URL"),
    (dict(CORS_ORIGINS="http://localhost:3000"), "CORS_ORIGINS"),
    (dict(CORS_ORIGINS=""), "CORS_ORIGINS"),
])
def test_producao_recusa_configuracao_insegura(kw, trecho):
    problemas = _cfg(**kw).validar_para_producao()
    assert any(trecho in p for p in problemas)


def test_desenvolvimento_nao_valida():
    assert Settings(_env_file=None, ENVIRONMENT="development").validar_para_producao() == []


@pytest.mark.parametrize("entrada,esperado", [
    ("postgres://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
    ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg2://u:p@h/db?sslmode=require"),
    ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
    ("sqlite:///./dev.db", "sqlite:///./dev.db"),
])
def test_url_do_banco_e_normalizada_para_o_driver(entrada, esperado):
    assert Settings(_env_file=None, DATABASE_URL=entrada).database_url_normalizada == esperado


def test_cabecalhos_de_seguranca_e_saude(client):
    r = client.get("/saude")
    assert r.status_code == 200
    h = r.headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "no-referrer" and "frame-ancestors 'none'" in h["content-security-policy"]
    assert client.get("/docs").headers.get("content-security-policy") is None  # swagger precisa de CDN
    assert client.get("/saude/pronto").json() == {"status": "ok", "banco": "ok"}
    assert client.post("/auth/login", json={"usuario": "a", "senha": "b"}).headers["cache-control"] == "no-store"


def test_redirect_https_atras_de_proxy(client, monkeypatch):
    from app import middleware

    s = middleware.get_settings()
    monkeypatch.setattr(s, "FORCE_HTTPS", True)
    monkeypatch.setattr(s, "TRUST_PROXY", True)
    r = client.get("/obras", headers={"X-Forwarded-Proto": "http"}, follow_redirects=False)
    assert r.status_code == 308 and r.headers["location"].startswith("https://")
    # health check da plataforma nunca e' redirecionado; https via proxy passa
    assert client.get("/saude", headers={"X-Forwarded-Proto": "http"}, follow_redirects=False).status_code == 200
    assert client.get("/saude", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False).headers["strict-transport-security"]
    assert client.get("/obras", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False).status_code == 401


def test_ip_real_vem_do_proxy_somente_quando_confiavel(client, monkeypatch, usuario_admin):
    from app import middleware

    s = middleware.get_settings()
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
    monkeypatch.setattr(s, "TRUST_PROXY", False)
    r = client.post("/auth/login", json=usuario_admin, headers=headers)
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auditoria", params={"acao": "login_sucesso"}, headers=h).json()[0]["ip"] == "testclient"
    monkeypatch.setattr(s, "TRUST_PROXY", True)
    client.post("/auth/login", json=usuario_admin, headers=headers)
    assert client.get("/auditoria", params={"acao": "login_sucesso"}, headers=h).json()[0]["ip"] == "203.0.113.9"


def test_saude_pronto_devolve_503_quando_banco_cai(client):
    from app.database import get_db
    from app.main import app

    class SessaoQuebrada:
        def execute(self, *a, **k):
            raise RuntimeError("conexao recusada")

        def close(self):
            pass

    app.dependency_overrides[get_db] = lambda: SessaoQuebrada()
    r = client.get("/saude/pronto")
    assert r.status_code == 503 and r.json()["detail"] == "Banco de dados indisponivel."
    assert client.get("/saude").status_code == 200  # liveness independe do banco
