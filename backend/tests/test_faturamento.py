"""Prioridade 2: configuracao de faturamento, resumo gerencial, evolucao
mensal, carteira de obras/contratos e alertas financeiros."""
from datetime import date, timedelta


def _obra_com_medicao_e_fatura(client, headers):
    r = client.post("/clientes", json={"nome": "Cliente Fat"}, headers=headers)
    cliente_id = r.json()["id"]
    r = client.post(
        "/obras",
        json={
            "wl": "FAT-TESTE", "cliente_id": cliente_id, "status": "em_execucao",
            "valor_contrato": 100000, "necs_planejados": 5000,
            "data_fim": str(date.today() + timedelta(days=10)),
        },
        headers=headers,
    )
    obra_id = r.json()["id"]
    r = client.post("/medicoes", json={"obra_id": obra_id, "contrato": 100000, "percentual": 20, "necs_medidos": 1000}, headers=headers)
    medicao_id = r.json()["id"]
    client.patch(f"/medicoes/{medicao_id}", json={"status": "Aprovada"}, headers=headers)
    r = client.post(
        "/faturas",
        json={"obra_id": obra_id, "medicao_id": medicao_id, "valor": 20000, "necs_faturados": 1000, "vencimento": str(date.today() + timedelta(days=5))},
        headers=headers,
    )
    return obra_id, medicao_id, r.json()["id"]


def test_configuracao_faturamento_get_e_put(client, admin_headers):
    r = client.get("/faturamento/configuracao", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["meta_mensal_nec"] == 20000

    r = client.put(
        "/faturamento/configuracao",
        json={"meta_mensal_nec": 15000, "dia_alerta": 20, "emails_alerta": ["a@b.com"]},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["meta_mensal_nec"] == 15000

    r = client.get("/faturamento/configuracao", headers=admin_headers)
    assert r.json()["meta_mensal_nec"] == 15000


def test_medicao_maquina_de_estados_e_nec_propagam_para_fatura_e_obra(client, admin_headers):
    obra_id, medicao_id, _ = _obra_com_medicao_e_fatura(client, admin_headers)

    r = client.get(f"/obras/{obra_id}", headers=admin_headers)
    assert r.json()["necs_faturados"] == 1000

    # Medicao aprovada e' terminal (nao pode voltar para Rascunho).
    r = client.patch(f"/medicoes/{medicao_id}", json={"status": "Rascunho"}, headers=admin_headers)
    assert r.status_code == 422


def test_resumo_e_evolucao_mensal(client, admin_headers):
    _obra_com_medicao_e_fatura(client, admin_headers)

    r = client.get("/faturamento/resumo", headers=admin_headers)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["nec_realizado_mes"] == 1000
    assert corpo["faturas_emitidas"] == 1
    assert len(corpo["evolucao_mensal"]) == 6

    r = client.get("/faturamento/evolucao-mensal?meses=3", headers=admin_headers)
    assert r.status_code == 200
    assert len(r.json()) == 3
    assert r.json()[-1]["necs"] == 1000


def test_carteira_de_obras(client, admin_headers):
    obra_id, _, _ = _obra_com_medicao_e_fatura(client, admin_headers)
    r = client.get("/faturamento/carteira", headers=admin_headers)
    assert r.status_code == 200
    item = next(i for i in r.json() if i["obra_id"] == obra_id)
    assert item["codigo_contrato"] == "FAT-TESTE"
    assert item["nec_faturado"] == 1000
    assert item["valor_faturado"] == 20000.0
    assert item["saldo_valor_estimado"] == 80000.0


def test_alertas_gerados_sem_duplicar_e_resolvidos(client, admin_headers):
    obra_id, medicao_id, _ = _obra_com_medicao_e_fatura(client, admin_headers)
    client.post(f"/medicoes/{medicao_id}/glosas", json={"valor": 200, "motivo": "teste"}, headers=admin_headers)

    r = client.post("/faturamento/alertas/gerar", headers=admin_headers)
    assert r.status_code == 200
    primeiro = r.json()
    assert primeiro["novos"] >= 1
    tipos = {a["tipo"] for a in primeiro["alertas"]}
    assert "vencimento_proximo" in tipos  # data_fim em 10 dias
    assert "glosa_pendente" in tipos

    # Gerar de novo nao duplica os mesmos alertas.
    r = client.post("/faturamento/alertas/gerar", headers=admin_headers)
    assert r.json()["novos"] == 0
    assert r.json()["total_ativos"] == primeiro["total_ativos"]

    alerta_id = r.json()["alertas"][0]["id"]
    r = client.patch(f"/faturamento/alertas/{alerta_id}/resolver", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["resolvido"] is True

    r = client.get("/faturamento/alertas", headers=admin_headers)
    assert all(a["id"] != alerta_id for a in r.json())


def test_faturamento_exige_permissao(client, db_session, usuario_admin):
    from tests.conftest import criar_perfil, criar_usuario

    criar_perfil(db_session, perfil_id="sem-acesso", permissoes=[])
    creds = criar_usuario(db_session, usuario="semacesso", perfil_id="sem-acesso")
    r = client.post("/auth/login", json=creds)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/faturamento/resumo", headers=headers)
    assert r.status_code == 403
    r = client.get("/faturamento/resumo")
    assert r.status_code == 401
