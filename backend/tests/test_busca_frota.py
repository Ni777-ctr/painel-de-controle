from datetime import date, timedelta

from app.models.cliente import Cliente
from app.models.financeiro import Fatura
from app.models.obra import Obra
from tests.conftest import criar_perfil, criar_usuario


def _login(client, cred):
    r = client.post("/auth/login", json=cred)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _dados(db_session):
    db = db_session()
    c = Cliente(nome="TEES Engenharia", documento="12.345.678/0001-90")
    db.add(c)
    db.flush()
    o = Obra(wl="DMP/A.SUL.25.00419", descricao="Rede MT Trecho A", regional="A.SUL", cliente_id=c.id, status="em_execucao")
    o2 = Obra(wl="CTM/A.NORTE.25.00118", descricao="Extensao Rural", regional="A.NORTE", status="contratada")
    db.add_all([o, o2])
    db.flush()
    db.add(Fatura(obra_id=o.id, valor=100, vencimento=date.today() + timedelta(days=30)))
    db.commit()
    db.close()


def test_busca_encontra_obra_cliente_e_fatura(client, admin_headers, db_session):
    _dados(db_session)
    r = client.get("/busca", params={"q": "00419"}, headers=admin_headers).json()
    assert {x["tipo"] for x in r["resultados"]} >= {"obra"}
    assert any(x["titulo"] == "DMP/A.SUL.25.00419" for x in r["resultados"])

    r = client.get("/busca", params={"q": "tees"}, headers=admin_headers).json()
    assert [x["tipo"] for x in r["resultados"]] == ["cliente"]

    # fatura encontrada pelo codigo da obra
    r = client.get("/busca", params={"q": "A.SUL"}, headers=admin_headers).json()
    assert {"obra", "fatura"} <= {x["tipo"] for x in r["resultados"]}


def test_busca_filtra_por_tipo_e_regional(client, admin_headers, db_session):
    _dados(db_session)
    r = client.get("/busca", params={"q": "25", "tipos": "obra", "regional": "A.NORTE"}, headers=admin_headers).json()
    assert [x["titulo"] for x in r["resultados"]] == ["CTM/A.NORTE.25.00118"]


def test_busca_trata_curingas_literalmente(client, admin_headers, db_session):
    _dados(db_session)
    assert client.get("/busca", params={"q": "%%"}, headers=admin_headers).json()["total"] == 0
    assert client.get("/busca", params={"q": "A_SUL"}, headers=admin_headers).json()["total"] == 0


def test_busca_respeita_rbac(client, db_session, admin_headers):
    _dados(db_session)
    criar_perfil(db_session, perfil_id="so-clientes", permissoes=["clientes:read"])
    h = _login(client, criar_usuario(db_session, usuario="cli", perfil_id="so-clientes"))
    r = client.get("/busca", params={"q": "A.SUL"}, headers=h).json()
    assert r["total"] == 0  # obras/faturas nao sao legiveis por este perfil
    r = client.get("/busca", params={"q": "tees"}, headers=h).json()
    assert r["total"] == 1


def test_busca_exige_login_e_termo_minimo(client, admin_headers):
    assert client.get("/busca", params={"q": "abc"}).status_code == 401
    assert client.get("/busca", params={"q": "a"}, headers=admin_headers).status_code == 422


# ---------------- frota ----------------
def test_frota_crud_e_placa_unica(client, admin_headers):
    r = client.post("/veiculos", json={"placa": "abc-1d23".replace("-", ""), "modelo": "Hilux", "regional": "A.SUL"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    assert r.json()["placa"] == "ABC1D23"
    vid = r.json()["id"]
    assert client.post("/veiculos", json={"placa": "abc1d23", "modelo": "Outro"}, headers=admin_headers).status_code == 409
    assert client.patch(f"/veiculos/{vid}", json={"status": "Manutencao", "km_atual": 1000}, headers=admin_headers).json()["status"] == "Manutencao"
    assert client.patch(f"/veiculos/{vid}", json={"status": "Quebrado"}, headers=admin_headers).status_code == 422
    # busca por placa
    assert [v["placa"] for v in client.get("/veiculos?q=abc1", headers=admin_headers).json()] == ["ABC1D23"]
    assert client.delete(f"/veiculos/{vid}", headers=admin_headers).status_code == 204
    assert client.get(f"/veiculos/{vid}", headers=admin_headers).status_code == 404


def test_concluir_manutencao_atualiza_data_e_km(client, admin_headers):
    vid = client.post("/veiculos", json={"placa": "KLM2N34", "modelo": "Cesto", "km_atual": 5000}, headers=admin_headers).json()["id"]
    m = client.post(
        f"/veiculos/{vid}/manutencoes",
        json={"descricao": "Revisao 10k", "data_prevista": str(date.today()), "km": 10000, "custo": 350.5},
        headers=admin_headers,
    )
    assert m.status_code == 201, m.text
    mid = m.json()["id"]
    r = client.patch(f"/manutencoes/{mid}", json={"status": "Concluida"}, headers=admin_headers).json()
    assert r["data_realizada"] == str(date.today())
    assert client.get(f"/veiculos/{vid}", headers=admin_headers).json()["km_atual"] == 10000


def test_frota_exige_permissao_e_audita(client, db_session, admin_headers):
    criar_perfil(db_session, perfil_id="leitor-frota", permissoes=["frota:read"])
    h = _login(client, criar_usuario(db_session, usuario="lf", perfil_id="leitor-frota"))
    assert client.get("/veiculos", headers=h).status_code == 200
    assert client.post("/veiculos", json={"placa": "QWE1R23", "modelo": "x"}, headers=h).status_code == 403
    client.post("/veiculos", json={"placa": "QWE1R23", "modelo": "x"}, headers=admin_headers)
    acoes = {l["acao"] for l in client.get("/auditoria", headers=admin_headers).json()}
    assert {"veiculo_criado", "acesso_negado"} <= acoes
