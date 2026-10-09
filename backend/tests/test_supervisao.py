"""Supervisao: empreiteiras e Relatorios Diarios de Campo (modelos, CRUD, filtros, RBAC, auditoria)."""
from datetime import date, time

import pytest

from app.models.auditoria import AuditLog
from app.models.supervisao import Empreiteira, RelatorioSupervisao
from tests.conftest import criar_perfil, criar_usuario

BASE = "/supervisao"


def _login(client, cred):
    r = client.post("/auth/login", json=cred)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _usuario(client, db_session, nome, permissoes):
    criar_perfil(db_session, perfil_id=f"perfil-{nome}", permissoes=permissoes)
    return _login(client, criar_usuario(db_session, usuario=nome, perfil_id=f"perfil-{nome}"))


def _relatorio(**extra):
    base = {"data_relatorio": "2026-10-05", "projeto_atividade": "DMP/A.SUL.25.00419", "status": "Parcial", "municipio": "Santo André"}
    return {**base, **extra}


def _criar_emp(client, h, nome="Alfa Construções Ltda", **extra):
    r = client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": nome, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
def test_modelo_empreiteira_defaults(db_session):
    db = db_session()
    e = Empreiteira(nome_razao_social="Beta SA")
    db.add(e)
    db.commit()
    db.refresh(e)
    assert e.id and e.ativo is True and e.cnpj is None and e.codigo_contrato is None and e.criado_em is not None
    db.close()


def test_modelo_relatorio_defaults_e_json_roundtrip(db_session):
    db = db_session()
    e = Empreiteira(nome_razao_social="Beta SA")
    db.add(e)
    db.flush()
    r = RelatorioSupervisao(
        data_relatorio=date(2026, 10, 5), empreiteira_id=e.id, horario_saida_base=time(7, 30),
        composicao_equipe=[{"nome": "João", "funcao": "Eletricista"}], fotos=[{"url": "https://x/a.jpg", "legenda": "antes"}],
    )
    db.add(r)
    db.commit()
    db.expire_all()
    r = db.get(RelatorioSupervisao, r.id)
    assert r.status == "Sem status" and r.porcentagem_execucao is None and r.empreiteira.nome_razao_social == "Beta SA"
    assert r.horario_saida_base == time(7, 30) and r.horario_chegada_base is None
    assert r.composicao_equipe == [{"nome": "João", "funcao": "Eletricista"}] and r.fotos[0]["legenda"] == "antes"
    assert r.criado_em is not None and r.atualizado_em is not None
    db.close()


def test_modelo_json_vazio_e_sql_null(db_session):
    db = db_session()
    r = RelatorioSupervisao(data_relatorio=date(2026, 10, 5))
    db.add(r)
    db.commit()
    assert db.query(RelatorioSupervisao).filter(RelatorioSupervisao.fotos.is_(None)).count() == 1
    db.close()


# ---------------------------------------------------------------------------
# Empreiteiras: CRUD
# ---------------------------------------------------------------------------
def test_crud_empreiteira_completo(client, admin_headers):
    e = _criar_emp(client, admin_headers, cnpj="11444777000161", codigo_contrato="4600004258")
    assert e["cnpj"] == "11.444.777/0001-61" and e["ativo"] is True and e["id"]

    r = client.get(f"{BASE}/empreiteiras", headers=admin_headers)
    assert r.status_code == 200 and [x["id"] for x in r.json()] == [e["id"]]
    r = client.get(f"{BASE}/empreiteiras/{e['id']}", headers=admin_headers)
    assert r.status_code == 200 and r.json()["codigo_contrato"] == "4600004258"

    r = client.patch(f"{BASE}/empreiteiras/{e['id']}", json={"ativo": False, "nome_razao_social": "Alfa Novo"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["ativo"] is False and r.json()["nome_razao_social"] == "Alfa Novo"

    assert client.delete(f"{BASE}/empreiteiras/{e['id']}", headers=admin_headers).status_code == 204
    assert client.get(f"{BASE}/empreiteiras/{e['id']}", headers=admin_headers).status_code == 404


def test_empreiteira_minima_so_com_nome(client, admin_headers):
    r = client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": "  Gama  "}, headers=admin_headers)
    assert r.status_code == 201
    assert r.json()["nome_razao_social"] == "Gama" and r.json()["cnpj"] is None and r.json()["ativo"] is True


def test_empreiteira_validacoes(client, admin_headers):
    assert client.post(f"{BASE}/empreiteiras", json={}, headers=admin_headers).status_code == 422
    assert client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": "  "}, headers=admin_headers).status_code == 422
    assert client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": "X", "cnpj": "123"}, headers=admin_headers).status_code == 422
    e = _criar_emp(client, admin_headers, cnpj="11.444.777/0001-61")
    r = client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": "Outra", "cnpj": "11444777000161"}, headers=admin_headers)
    assert r.status_code == 409  # CNPJ duplicado (mesmo digitado de outro jeito)
    outra = _criar_emp(client, admin_headers, nome="Outra")
    r = client.patch(f"{BASE}/empreiteiras/{outra['id']}", json={"cnpj": "11444777000161"}, headers=admin_headers)
    assert r.status_code == 409
    assert client.patch(f"{BASE}/empreiteiras/{outra['id']}", json={"nome_razao_social": None}, headers=admin_headers).status_code == 422
    assert client.patch(f"{BASE}/empreiteiras/{outra['id']}", json={"ativo": None}, headers=admin_headers).status_code == 422
    assert client.patch(f"{BASE}/empreiteiras/9999", json={"ativo": False}, headers=admin_headers).status_code == 404
    assert client.delete(f"{BASE}/empreiteiras/9999", headers=admin_headers).status_code == 404
    assert e["id"]


def test_empreiteira_filtros_ativo_e_busca(client, admin_headers):
    _criar_emp(client, admin_headers, nome="Alfa Elétrica", cnpj="11222333000181", codigo_contrato="CT-100")
    b = _criar_emp(client, admin_headers, nome="Beta Redes", ativo=False)
    nomes = lambda **p: [x["nome_razao_social"] for x in client.get(f"{BASE}/empreiteiras", params=p, headers=admin_headers).json()]  # noqa: E731
    assert nomes() == ["Alfa Elétrica", "Beta Redes"]
    assert nomes(ativo="true") == ["Alfa Elétrica"] and nomes(ativo="false") == ["Beta Redes"]
    assert nomes(q="redes") == ["Beta Redes"] and nomes(q="CT-100") == ["Alfa Elétrica"] and nomes(q="11.222") == ["Alfa Elétrica"]
    assert nomes(q="%") == []  # curinga tratado como literal
    assert b["ativo"] is False


def test_nao_exclui_empreiteira_com_relatorios(client, admin_headers):
    e = _criar_emp(client, admin_headers)
    assert client.post(f"{BASE}/relatorios", json=_relatorio(empreiteira_id=e["id"]), headers=admin_headers).status_code == 201
    r = client.delete(f"{BASE}/empreiteiras/{e['id']}", headers=admin_headers)
    assert r.status_code == 409 and "desative" in r.json()["detail"]
    assert client.get(f"{BASE}/empreiteiras/{e['id']}", headers=admin_headers).status_code == 200


# ---------------------------------------------------------------------------
# Relatorios: CRUD
# ---------------------------------------------------------------------------
def test_criar_e_obter_relatorio_completo(client, admin_headers):
    e = _criar_emp(client, admin_headers)
    payload = _relatorio(
        ordem="OS-123", porcentagem_execucao=60, empreiteira_id=e["id"], contato="(11) 99999-0000", lv_lm="LV",
        responsavel="Carlos Souza", codigo_placa="ABC1D23", supervisor_beq="Ana Lima",
        endereco="Rua das Flores, 100", bairro="Centro", estado="sp",
        composicao_equipe=[{"nome": "João", "funcao": "Eletricista"}, {"nome": "Pedro"}],
        servicos_executados="Troca de 3 postes", pendencias="Aguardando poda",
        horario_saida_base="07:30", horario_chegada_obra="08:15", horario_saida_obra="16:40", horario_chegada_base="17:20",
        fotos=[{"url": "https://exemplo.com/f1.jpg", "legenda": "Antes"}, {"url": "/uploads/f2.jpg"}],
    )
    r = client.post(f"{BASE}/relatorios", json=payload, headers=admin_headers)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["id"] and c["status"] == "Parcial" and c["estado"] == "SP"  # UF normalizada
    assert c["empreiteira_id"] == e["id"] and c["empreiteira_nome"] == "Alfa Construções Ltda"
    assert c["horario_saida_base"] == "07:30:00" and c["horario_chegada_base"] == "17:20:00"
    assert c["composicao_equipe"] == [{"nome": "João", "funcao": "Eletricista"}, {"nome": "Pedro", "funcao": None}]
    assert c["fotos"] == [{"url": "https://exemplo.com/f1.jpg", "legenda": "Antes"}, {"url": "/uploads/f2.jpg", "legenda": None}]
    assert c["criado_por_id"] and c["criado_em"] and c["atualizado_em"]

    g = client.get(f"{BASE}/relatorios/{c['id']}", headers=admin_headers)
    assert g.status_code == 200 and g.json() == c


def test_relatorio_minimo_e_empreiteira_customizada(client, admin_headers):
    r = client.post(f"{BASE}/relatorios", json={"data_relatorio": "2026-10-06", "empreiteira_nome_customizado": "Empreiteira Avulsa"}, headers=admin_headers)
    assert r.status_code == 201
    c = r.json()
    assert c["status"] == "Sem status" and c["empreiteira_id"] is None and c["empreiteira_nome"] == "Empreiteira Avulsa"
    assert c["fotos"] is None and c["composicao_equipe"] is None


@pytest.mark.parametrize("campo,valor", [
    ("status", "Em andamento"), ("status", "concluido"), ("porcentagem_execucao", 101), ("porcentagem_execucao", -1),
    ("estado", "SAO"), ("horario_saida_base", "25:99"), ("data_relatorio", "05/10/2026"),
    ("fotos", [{"url": "javascript:alert(1)"}]), ("fotos", [{"legenda": "sem url"}]), ("composicao_equipe", [{"funcao": "sem nome"}]),
])
def test_relatorio_validacoes(client, admin_headers, campo, valor):
    r = client.post(f"{BASE}/relatorios", json=_relatorio(**{campo: valor}), headers=admin_headers)
    assert r.status_code == 422, (campo, valor, r.text)


def test_relatorio_exige_data_e_empreiteira_existente(client, admin_headers):
    assert client.post(f"{BASE}/relatorios", json={"status": "Parcial"}, headers=admin_headers).status_code == 422
    r = client.post(f"{BASE}/relatorios", json=_relatorio(empreiteira_id=9999), headers=admin_headers)
    assert r.status_code == 422 and r.json()["detail"] == "empreiteira_id inexistente."


def test_todos_os_status_validos(client, admin_headers):
    for s in ("Concluído", "Parcial", "Cancelado", "Sem status"):
        r = client.post(f"{BASE}/relatorios", json=_relatorio(status=s), headers=admin_headers)
        assert r.status_code == 201 and r.json()["status"] == s


def test_obter_relatorio_inexistente(client, admin_headers):
    assert client.get(f"{BASE}/relatorios/9999", headers=admin_headers).status_code == 404


def test_put_substitui_o_relatorio_inteiro(client, admin_headers):
    e = _criar_emp(client, admin_headers)
    c = client.post(f"{BASE}/relatorios", json=_relatorio(empreiteira_id=e["id"], pendencias="x", fotos=[{"url": "/a.jpg"}]), headers=admin_headers).json()
    novo = _relatorio(status="Concluído", porcentagem_execucao=100, servicos_executados="Tudo pronto", empreiteira_nome_customizado="Outra")
    r = client.put(f"{BASE}/relatorios/{c['id']}", json=novo, headers=admin_headers)
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["id"] == c["id"] and u["status"] == "Concluído" and u["porcentagem_execucao"] == 100
    assert u["pendencias"] is None and u["fotos"] is None and u["empreiteira_id"] is None  # omitidos voltam a nulo (PUT)
    assert u["empreiteira_nome"] == "Outra" and u["criado_por_id"] == c["criado_por_id"] and u["criado_em"] == c["criado_em"]
    assert client.get(f"{BASE}/relatorios/{c['id']}", headers=admin_headers).json() == u


def test_put_erros(client, admin_headers):
    c = client.post(f"{BASE}/relatorios", json=_relatorio(), headers=admin_headers).json()
    assert client.put(f"{BASE}/relatorios/9999", json=_relatorio(), headers=admin_headers).status_code == 404
    assert client.put(f"{BASE}/relatorios/{c['id']}", json=_relatorio(status="Nada"), headers=admin_headers).status_code == 422
    assert client.put(f"{BASE}/relatorios/{c['id']}", json=_relatorio(empreiteira_id=9999), headers=admin_headers).status_code == 422
    assert client.put(f"{BASE}/relatorios/{c['id']}", json={"status": "Parcial"}, headers=admin_headers).status_code == 422  # sem data
    assert client.get(f"{BASE}/relatorios/{c['id']}", headers=admin_headers).json()["status"] == "Parcial"  # nada mudou


# ---------------------------------------------------------------------------
# Relatorios: filtros
# ---------------------------------------------------------------------------
@pytest.fixture()
def massa(client, admin_headers):
    a = _criar_emp(client, admin_headers, nome="Alfa Elétrica")
    b = _criar_emp(client, admin_headers, nome="Beta Redes")
    dados = [
        _relatorio(data_relatorio="2026-10-01", municipio="Santo André", status="Concluído", empreiteira_id=a["id"], responsavel="Carlos Souza"),
        _relatorio(data_relatorio="2026-10-02", municipio="São Bernardo", status="Parcial", empreiteira_id=b["id"], responsavel="Ana Lima"),
        _relatorio(data_relatorio="2026-10-02", municipio="Santo André", status="Cancelado", empreiteira_nome_customizado="Gama Avulsa", responsavel="Carlos Souza"),
        _relatorio(data_relatorio="2026-10-03", municipio="Mauá", status="Sem status", responsavel="Pedro 100%_ok"),
    ]
    for d in dados:
        assert client.post(f"{BASE}/relatorios", json=d, headers=admin_headers).status_code == 201
    return {"a": a["id"], "b": b["id"]}


def _ids(client, h, **params):
    r = client.get(f"{BASE}/relatorios", params=params, headers=h)
    assert r.status_code == 200, r.text
    return [(x["data_relatorio"], x["municipio"]) for x in r.json()]


def test_filtro_sem_parametros_ordena_por_data_desc(client, admin_headers, massa):
    datas = [d for d, _ in _ids(client, admin_headers)]
    assert datas == ["2026-10-03", "2026-10-02", "2026-10-02", "2026-10-01"]


def test_filtros_de_data(client, admin_headers, massa):
    assert len(_ids(client, admin_headers, data="2026-10-02")) == 2
    assert len(_ids(client, admin_headers, data_inicio="2026-10-02")) == 3
    assert len(_ids(client, admin_headers, data_fim="2026-10-01")) == 1
    assert len(_ids(client, admin_headers, data_inicio="2026-10-02", data_fim="2026-10-02")) == 2
    assert client.get(f"{BASE}/relatorios", params={"data_inicio": "2026-10-05", "data_fim": "2026-10-01"}, headers=admin_headers).status_code == 422


def test_filtro_municipio_status_responsavel(client, admin_headers, massa):
    assert len(_ids(client, admin_headers, municipio="santo")) == 2          # parcial, sem diferenciar caixa
    assert _ids(client, admin_headers, municipio="Mauá") == [("2026-10-03", "Mauá")]
    assert len(_ids(client, admin_headers, status="Parcial")) == 1
    assert len(_ids(client, admin_headers, status="Concluído")) == 1
    assert client.get(f"{BASE}/relatorios", params={"status": "Inexistente"}, headers=admin_headers).status_code == 422
    assert len(_ids(client, admin_headers, responsavel="carlos")) == 2
    assert len(_ids(client, admin_headers, responsavel="100%_")) == 1         # % e _ sao literais
    assert _ids(client, admin_headers, municipio="%") == []


def test_filtro_empreiteira_por_id_e_por_nome(client, admin_headers, massa):
    assert len(_ids(client, admin_headers, empreiteira_id=massa["a"])) == 1
    assert len(_ids(client, admin_headers, empreiteira_id=massa["b"])) == 1
    assert len(_ids(client, admin_headers, empreiteira="elétrica")) == 1     # nome cadastrado
    assert len(_ids(client, admin_headers, empreiteira="gama")) == 1         # nome customizado
    assert len(_ids(client, admin_headers, empreiteira="zzz")) == 0


def test_filtros_combinados_e_paginacao(client, admin_headers, massa):
    assert _ids(client, admin_headers, municipio="Santo", status="Cancelado", responsavel="Carlos", data="2026-10-02") == [("2026-10-02", "Santo André")]
    assert _ids(client, admin_headers, municipio="Santo", status="Parcial") == []
    assert len(_ids(client, admin_headers, limite=2)) == 2 and len(_ids(client, admin_headers, limite=2, offset=3)) == 1
    assert client.get(f"{BASE}/relatorios", params={"limite": 0}, headers=admin_headers).status_code == 422
    assert client.get(f"{BASE}/relatorios", params={"limite": 501}, headers=admin_headers).status_code == 422


# ---------------------------------------------------------------------------
# Permissoes (RBAC)
# ---------------------------------------------------------------------------
def test_sem_token_401(client):
    for metodo, rota in (("get", "/empreiteiras"), ("post", "/empreiteiras"), ("get", "/relatorios"), ("post", "/relatorios"),
                         ("get", "/relatorios/1"), ("put", "/relatorios/1")):
        assert getattr(client, metodo)(BASE + rota).status_code == 401, (metodo, rota)


def test_perfil_so_leitura(client, db_session, admin_headers):
    leitor = _usuario(client, db_session, "leitor", ["supervisao:read"])
    e = _criar_emp(client, admin_headers)
    c = client.post(f"{BASE}/relatorios", json=_relatorio(empreiteira_id=e["id"]), headers=admin_headers).json()

    assert client.get(f"{BASE}/empreiteiras", headers=leitor).status_code == 200
    assert client.get(f"{BASE}/empreiteiras/{e['id']}", headers=leitor).status_code == 200
    assert client.get(f"{BASE}/relatorios", headers=leitor).status_code == 200
    assert client.get(f"{BASE}/relatorios/{c['id']}", headers=leitor).status_code == 200

    assert client.post(f"{BASE}/empreiteiras", json={"nome_razao_social": "X"}, headers=leitor).status_code == 403
    assert client.patch(f"{BASE}/empreiteiras/{e['id']}", json={"ativo": False}, headers=leitor).status_code == 403
    assert client.delete(f"{BASE}/empreiteiras/{e['id']}", headers=leitor).status_code == 403
    assert client.post(f"{BASE}/relatorios", json=_relatorio(), headers=leitor).status_code == 403
    assert client.put(f"{BASE}/relatorios/{c['id']}", json=_relatorio(), headers=leitor).status_code == 403


def test_perfil_sem_permissao_de_supervisao(client, db_session, admin_headers):
    outro = _usuario(client, db_session, "outro", ["obras:read", "clientes:read"])
    for rota in ("/empreiteiras", "/relatorios"):
        assert client.get(BASE + rota, headers=outro).status_code == 403
    assert client.post(f"{BASE}/relatorios", json=_relatorio(), headers=outro).status_code == 403


def test_perfil_com_escrita_cria_e_edita(client, db_session):
    escritor = _usuario(client, db_session, "escritor", ["supervisao:read", "supervisao:write"])
    r = client.post(f"{BASE}/relatorios", json=_relatorio(), headers=escritor)
    assert r.status_code == 201
    assert client.put(f"{BASE}/relatorios/{r.json()['id']}", json=_relatorio(status="Concluído"), headers=escritor).status_code == 200


def test_somente_escrita_nao_le(client, db_session):
    so_w = _usuario(client, db_session, "sow", ["supervisao:write"])
    assert client.get(f"{BASE}/relatorios", headers=so_w).status_code == 403
    assert client.post(f"{BASE}/relatorios", json=_relatorio(), headers=so_w).status_code == 201


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
def test_escritas_geram_auditoria(client, db_session, admin_headers):
    e = _criar_emp(client, admin_headers)
    client.patch(f"{BASE}/empreiteiras/{e['id']}", json={"ativo": False}, headers=admin_headers)
    c = client.post(f"{BASE}/relatorios", json=_relatorio(), headers=admin_headers).json()
    client.put(f"{BASE}/relatorios/{c['id']}", json=_relatorio(status="Concluído", pendencias="nenhuma"), headers=admin_headers)
    outra = _criar_emp(client, admin_headers, nome="Outra")
    client.delete(f"{BASE}/empreiteiras/{outra['id']}", headers=admin_headers)

    db = db_session()
    acoes = [(l.acao, l.entidade) for l in db.query(AuditLog).order_by(AuditLog.id).all() if l.entidade in ("empreiteiras", "relatorios_supervisao")]
    assert acoes == [
        ("empreiteira_criada", "empreiteiras"), ("empreiteira_atualizada", "empreiteiras"),
        ("relatorio_supervisao_criado", "relatorios_supervisao"), ("relatorio_supervisao_atualizado", "relatorios_supervisao"),
        ("empreiteira_criada", "empreiteiras"), ("empreiteira_excluida", "empreiteiras"),
    ]
    put = db.query(AuditLog).filter_by(acao="relatorio_supervisao_atualizado").one()
    assert put.antes == {"status": "Parcial", "pendencias": None} and put.depois == {"status": "Concluído", "pendencias": "nenhuma"}
    assert put.usuario_id and put.entidade_id == str(c["id"])
    db.close()


def test_leitura_nao_gera_auditoria(client, db_session, admin_headers):
    _criar_emp(client, admin_headers)
    db = db_session()
    antes = db.query(AuditLog).count()
    client.get(f"{BASE}/empreiteiras", headers=admin_headers)
    client.get(f"{BASE}/relatorios", headers=admin_headers)
    assert db.query(AuditLog).count() == antes
    db.close()


# ---------------------------------------------------------------------------
# Convencao de URL
# ---------------------------------------------------------------------------
def test_nao_existe_prefixo_api_v1(client, admin_headers):
    """O projeto nao usa /api/v1 (routers sem prefixo global); o modulo segue o mesmo padrao."""
    assert client.get("/api/v1/supervisao/relatorios", headers=admin_headers).status_code == 404
    assert client.get(f"{BASE}/relatorios", headers=admin_headers).status_code == 200
