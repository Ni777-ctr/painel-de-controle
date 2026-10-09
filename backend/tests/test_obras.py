"""Etapa 2: Obra como entidade central -- maquina de estados, historico de
status e resumo agregado."""


def _criar_obra(client, headers, wl="OBRA-001", status="proposta"):
    r = client.post("/obras", json={"wl": wl, "status": status}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_transicao_de_status_invalida(client, admin_headers):
    obra_id = _criar_obra(client, admin_headers)
    r = client.patch(f"/obras/{obra_id}", json={"status": "em_execucao"}, headers=admin_headers)
    assert r.status_code == 422


def test_em_execucao_exige_equipe(client, admin_headers):
    obra_id = _criar_obra(client, admin_headers)
    client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=admin_headers)

    r = client.patch(f"/obras/{obra_id}", json={"status": "em_execucao"}, headers=admin_headers)
    assert r.status_code == 422

    r = client.post("/equipes", json={"nome": "Equipe Alfa"}, headers=admin_headers)
    equipe_id = r.json()["id"]
    r = client.patch(f"/obras/{obra_id}", json={"status": "em_execucao", "equipe_id": equipe_id}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["equipe"] == "Equipe Alfa"


def test_status_terminal_nao_permite_nova_transicao(client, admin_headers):
    obra_id = _criar_obra(client, admin_headers)
    client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=admin_headers)
    r = client.post("/equipes", json={"nome": "Equipe X"}, headers=admin_headers)
    equipe_id = r.json()["id"]
    client.patch(f"/obras/{obra_id}", json={"status": "em_execucao", "equipe_id": equipe_id}, headers=admin_headers)
    client.patch(f"/obras/{obra_id}", json={"status": "concluida"}, headers=admin_headers)

    r = client.patch(f"/obras/{obra_id}", json={"status": "cancelada"}, headers=admin_headers)
    assert r.status_code == 422


def test_resumo_agregado_da_obra(client, admin_headers):
    obra_id = _criar_obra(client, admin_headers)
    client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=admin_headers)
    r = client.post("/equipes", json={"nome": "Equipe R"}, headers=admin_headers)
    equipe_id = r.json()["id"]
    client.patch(f"/obras/{obra_id}", json={"status": "em_execucao", "equipe_id": equipe_id}, headers=admin_headers)
    client.post("/programacao", json={"obra_id": obra_id, "equipe_id": equipe_id, "data": "2026-09-20"}, headers=admin_headers)

    r = client.get(f"/obras/{obra_id}/resumo", headers=admin_headers)
    assert r.status_code == 200
    resumo = r.json()
    assert resumo["programacao"]["total"] == 1
    assert len(resumo["historico_status"]) == 3  # proposta -> contratada -> em_execucao


def test_auditoria_registra_criacao_e_mudanca_de_status(client, admin_headers):
    obra_id = _criar_obra(client, admin_headers)
    client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=admin_headers)

    r = client.get("/auditoria", headers=admin_headers)
    acoes = [log["acao"] for log in r.json() if log["entidade"] == "obras" and log["entidade_id"] == str(obra_id)]
    assert "obra_criada" in acoes
    assert "obra_status_alterado" in acoes
