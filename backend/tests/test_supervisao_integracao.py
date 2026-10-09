"""Integracao do modulo Supervisao ao backend principal (v1.3): migration, seed/RBAC por perfil,
validacao de CNPJ, unicidade, corrida (409) e regressao das rotas existentes do v1.2."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models.supervisao import Empreiteira
from app.models.usuario import Perfil
from app.routers.supervisao import _commit_ou_409
from app.schemas.supervisao import FotoRelatorio, cnpj_valido
from seeds.seed import PERFIS_SEED, PERMISSOES_SUPERVISAO, PERMISSOES_SUPERVISAO_POR_PERFIL
from seeds.seed_supervisao import aplicar
from tests.conftest import criar_perfil, criar_usuario

RAIZ = Path(__file__).resolve().parent.parent  # pasta backend/


def _login(client, cred):
    r = client.post("/auth/login", json=cred)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Regressao: nenhuma rota do v1.2 sumiu; so entraram as de Supervisao
# ---------------------------------------------------------------------------
def _rotas_atuais():
    return {f"{m} {r.path}" for r in app.routes if hasattr(r, "methods") for m in r.methods if m not in ("HEAD", "OPTIONS")}


def test_rotas_do_v12_preservadas_e_adicoes_conhecidas():
    esperadas_v12 = set(json.loads((RAIZ / "tests" / "rotas_v12.json").read_text()))
    atuais = _rotas_atuais()
    assert esperadas_v12 <= atuais, f"rotas removidas: {sorted(esperadas_v12 - atuais)}"
    novas = atuais - esperadas_v12
    governanca = {'POST /governanca/convites', 'GET /governanca/contextos/{sid}/permissoes'}
    assert governanca <= novas
    novas = novas - governanca
    assert novas and all(r.split(" ", 1)[1].startswith("/supervisao/") for r in novas), sorted(novas)
    assert {
        "GET /supervisao/empreiteiras", "POST /supervisao/empreiteiras", "GET /supervisao/empreiteiras/{empreiteira_id}",
        "PATCH /supervisao/empreiteiras/{empreiteira_id}", "DELETE /supervisao/empreiteiras/{empreiteira_id}",
        "GET /supervisao/relatorios", "POST /supervisao/relatorios", "GET /supervisao/relatorios/{relatorio_id}",
        "PUT /supervisao/relatorios/{relatorio_id}",
    } == novas


def test_saude_e_cors_do_main_preservados(client):
    assert client.get("/saude").json() == {"status": "ok"}
    assert client.get("/saude/pronto").json()["banco"] == "ok"
    r = client.options(
        "/supervisao/relatorios",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.get("/supervisao/empreiteiras").status_code == 401  # JWT obrigatorio


# ---------------------------------------------------------------------------
# Migration 0010 (SQLite descartavel via subprocesso; nao toca em nenhum outro banco)
# ---------------------------------------------------------------------------
def _alembic(db_path, *args):
    test_pythonpath = os.pathsep.join(filter(None, [str(RAIZ), os.environ.get('PYTHONPATH', '')]))
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path}", "PYTHONPATH": test_pythonpath, "ENVIRONMENT": "development"}
    r = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=RAIZ, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout + r.stderr


def _tabelas(db_path):
    con = sqlite3.connect(db_path)
    try:
        return {n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_alembic_tem_uma_unica_head_central_sobre_0010():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0011_central_local"]
    assert script.get_revision('0011_central_local').down_revision == '0010'
    assert script.get_revision("0010").down_revision == "0009"
    ids = [r.revision for r in script.walk_revisions()]
    assert len(ids) == len(set(ids)) == 11  # 0001..0010 + central, sem ID duplicado


def test_migration_0010_upgrade_downgrade_upgrade_sem_afetar_outras_tabelas(tmp_path):
    db = tmp_path / "migracao.db"
    _alembic(db, "upgrade", "0009")
    antes = _tabelas(db)
    assert "empreiteiras" not in antes and "usuarios" in antes

    _alembic(db, "upgrade", "0010")
    depois = _tabelas(db)
    assert depois - antes == {"empreiteiras", "relatorios_supervisao"}  # so cria as 2 tabelas

    # downgrade de UMA revisao remove somente as 2 tabelas novas
    _alembic(db, "downgrade", "0009")
    assert _tabelas(db) == antes

    _alembic(db, "upgrade", "0010")
    assert _tabelas(db) == depois
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT version_num FROM alembic_version").fetchall() == [("0010",)]
        idx = {n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        con.close()
    assert "uq_empreiteiras_cnpj" in idx and "ix_relatorios_supervisao_data_municipio" in idx


def test_models_e_migration_sem_drift(tmp_path):
    """O que a migration cria deve ser igual ao que os models declaram."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app.database import Base

    db = tmp_path / "drift.db"
    _alembic(db, "upgrade", "head")
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as con:
        diffs = compare_metadata(MigrationContext.configure(con), Base.metadata)
    engine.dispose()
    sup = [d for d in diffs if "empreiteiras" in repr(d) or "relatorios_supervisao" in repr(d)]
    assert sup == [], sup


# ---------------------------------------------------------------------------
# CNPJ, URL de foto, unicidade e corrida
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cnpj,ok", [
    ("11222333000181", True), ("11444777000161", True), ("00000000000191", True),
    ("12345678000190", False), ("11111111111111", False), ("1144477700016", False), ("abc", False),
])
def test_cnpj_valido(cnpj, ok):
    assert cnpj_valido(cnpj) is ok


def test_endpoint_rejeita_cnpj_com_digito_verificador_errado(client, admin_headers):
    r = client.post("/supervisao/empreiteiras", json={"nome_razao_social": "X", "cnpj": "12.345.678/0001-90"}, headers=admin_headers)
    assert r.status_code == 422
    r = client.post("/supervisao/empreiteiras", json={"nome_razao_social": "X", "cnpj": "11.444.777/0001-61"}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["cnpj"] == "11.444.777/0001-61"


@pytest.mark.parametrize("url", ["//evil.example/x.jpg", "/\\evil.example", "javascript:alert(1)", "data:text/html,x", "ftp://x/a", "/ok\n.jpg"])
def test_url_de_foto_perigosa_rejeitada(url):
    with pytest.raises(ValueError):
        FotoRelatorio(url=url)


@pytest.mark.parametrize("url", ["https://x.com/a.jpg", "http://x.com/a.jpg", "/uploads/a.jpg"])
def test_url_de_foto_valida_aceita(url):
    assert FotoRelatorio(url=url).url == url


def test_cnpj_unico_no_banco_mas_nulls_repetem(db_session):
    db = db_session()
    db.add_all([Empreiteira(nome_razao_social="A"), Empreiteira(nome_razao_social="B")])  # 2 NULL: ok
    db.commit()
    db.add_all([Empreiteira(nome_razao_social="C", cnpj="11.444.777/0001-61")])
    db.commit()
    db.add(Empreiteira(nome_razao_social="D", cnpj="11.444.777/0001-61"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.close()


def test_integrity_error_vira_409_e_faz_rollback():
    class FakeDb:
        rolled = False

        def commit(self):
            raise IntegrityError("x", {}, Exception("dup"))

        def rollback(self):
            self.rolled = True

    db = FakeDb()
    with pytest.raises(HTTPException) as exc:
        _commit_ou_409(db, "conflito")
    assert exc.value.status_code == 409 and exc.value.detail == "conflito" and db.rolled


# ---------------------------------------------------------------------------
# Seed idempotente e RBAC por perfil
# ---------------------------------------------------------------------------
def test_seed_py_e_mapa_por_perfil_sao_consistentes():
    por_perfil = {pid: set(perms) for pid, _n, _d, _c, perms in PERFIS_SEED}
    for pid, perms in por_perfil.items():
        esperado = set(PERMISSOES_SUPERVISAO_POR_PERFIL.get(pid, []))
        if "*" in perms:
            continue
        assert perms & set(PERMISSOES_SUPERVISAO) == esperado, pid
    assert set(PERMISSOES_SUPERVISAO_POR_PERFIL) == {"supervisor", "gerencia-geral", "qualidade"}


def _perfis(db_session, **kw):
    for pid, perms in kw.items():
        criar_perfil(db_session, perfil_id=pid.replace("_", "-"), permissoes=perms)


def test_seed_supervisao_soma_sem_remover_e_e_idempotente(db_session):
    _perfis(db_session, supervisor=["obras:read", "customizada:x"], gerencia_geral=["obras:read"],
            qualidade=["auditoria:read"], administrador=["*"])
    db = db_session()
    try:
        m1 = aplicar(db)
        assert len(m1) == 3 and not any(l.startswith("AVISO") for l in m1)
        p = {x.id: x.permissoes for x in db.query(Perfil).all()}
        assert p["supervisor"] == ["obras:read", "customizada:x", "supervisao:read", "supervisao:write"]
        assert p["gerencia-geral"] == ["obras:read", "supervisao:read"]
        assert p["qualidade"] == ["auditoria:read", "supervisao:read"]
        assert p["administrador"] == ["*"]  # intacto
        assert aplicar(db) == []  # 2a execucao: nada muda
        assert {x.id: x.permissoes for x in db.query(Perfil).all()} == p
    finally:
        db.close()


def test_seed_supervisao_dry_run_reverter_e_perfil_ausente(db_session):
    _perfis(db_session, supervisor=["obras:read"])
    db = db_session()
    try:
        m = aplicar(db, dry_run=True)
        assert any("supervisor" in l for l in m) and any(l.startswith("AVISO perfil 'qualidade'") for l in m)
        assert db.get(Perfil, "supervisor").permissoes == ["obras:read"]  # dry-run nao grava
        aplicar(db)
        assert "supervisao:write" in db.get(Perfil, "supervisor").permissoes
        aplicar(db, reverter=True)
        assert db.get(Perfil, "supervisor").permissoes == ["obras:read"]  # volta ao original
        assert aplicar(db, reverter=True) == [l for l in aplicar(db, reverter=True) if l.startswith('AVISO')]  # idempotente (so avisos)
    finally:
        db.close()


def test_rbac_por_perfil_conforme_tabela(client, db_session, admin_headers):
    """supervisor le+escreve; gerencia-geral e qualidade so leem; encarregado/programacao nao acessam."""
    for pid, perms in PERMISSOES_SUPERVISAO_POR_PERFIL.items():
        criar_perfil(db_session, perfil_id=pid, permissoes=["obras:read", *perms])
    for pid in ("encarregado", "programacao", "visualizador"):
        criar_perfil(db_session, perfil_id=pid, permissoes=["obras:read"])
    hs = {pid: _login(client, criar_usuario(db_session, usuario=f"u-{pid}", perfil_id=pid))
          for pid in ("supervisor", "gerencia-geral", "qualidade", "encarregado", "programacao", "visualizador")}

    emp = client.post("/supervisao/empreiteiras", json={"nome_razao_social": "Alfa"}, headers=hs["supervisor"])
    assert emp.status_code == 201
    rel = client.post("/supervisao/relatorios", json={"data_relatorio": "2026-10-05"}, headers=hs["supervisor"])
    assert rel.status_code == 201

    for pid in ("gerencia-geral", "qualidade"):
        assert client.get("/supervisao/relatorios", headers=hs[pid]).status_code == 200
        assert client.get("/supervisao/empreiteiras", headers=hs[pid]).status_code == 200
        assert client.post("/supervisao/empreiteiras", json={"nome_razao_social": "Z"}, headers=hs[pid]).status_code == 403
        assert client.post("/supervisao/relatorios", json={"data_relatorio": "2026-10-05"}, headers=hs[pid]).status_code == 403
        assert client.put(f"/supervisao/relatorios/{rel.json()['id']}", json={"data_relatorio": "2026-10-06"}, headers=hs[pid]).status_code == 403
        assert client.delete(f"/supervisao/empreiteiras/{emp.json()['id']}", headers=hs[pid]).status_code == 403
    for pid in ("encarregado", "programacao", "visualizador"):
        assert client.get("/supervisao/relatorios", headers=hs[pid]).status_code == 403
        assert client.get("/supervisao/empreiteiras", headers=hs[pid]).status_code == 403
