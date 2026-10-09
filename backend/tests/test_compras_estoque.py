"""Etapas 3 e 4: ciclo compras -> estoque -> custo da obra, e requisicao de
compra automatica por estoque minimo."""


def _setup_material_almox(client, headers, estoque_minimo=0):
    r = client.post("/materiais", json={"nome": "Material Teste", "unidade": "UN", "estoque_minimo": estoque_minimo}, headers=headers)
    material_id = r.json()["id"]
    r = client.post("/almoxarifados", json={"nome": "Almox Teste"}, headers=headers)
    almox_id = r.json()["id"]
    r = client.post("/fornecedores", json={"nome": "Fornecedor Teste"}, headers=headers)
    fornecedor_id = r.json()["id"]
    return material_id, almox_id, fornecedor_id


def _receber_pedido(client, headers, fornecedor_id, almox_id, material_id, quantidade, valor_unitario):
    r = client.post(
        "/pedidos-compra",
        json={
            "fornecedor_id": fornecedor_id,
            "almoxarifado_id": almox_id,
            "itens": [{"material_id": material_id, "quantidade": quantidade, "valor_unitario": valor_unitario}],
        },
        headers=headers,
    )
    pedido_id = r.json()["id"]
    client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Enviado"}, headers=headers)
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=headers)
    return pedido_id, r


def test_pedido_sem_almoxarifado_nao_pode_ser_recebido(client, admin_headers):
    material_id, _, fornecedor_id = _setup_material_almox(client, admin_headers)
    r = client.post(
        "/pedidos-compra",
        json={"fornecedor_id": fornecedor_id, "itens": [{"material_id": material_id, "quantidade": 10, "valor_unitario": 5}]},
        headers=admin_headers,
    )
    pedido_id = r.json()["id"]
    client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Enviado"}, headers=admin_headers)
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=admin_headers)
    assert r.status_code == 422


def test_pedido_nao_pode_pular_etapa(client, admin_headers):
    material_id, almox_id, fornecedor_id = _setup_material_almox(client, admin_headers)
    r = client.post(
        "/pedidos-compra",
        json={"fornecedor_id": fornecedor_id, "almoxarifado_id": almox_id, "itens": [{"material_id": material_id, "quantidade": 10, "valor_unitario": 5}]},
        headers=admin_headers,
    )
    pedido_id = r.json()["id"]
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=admin_headers)
    assert r.status_code == 422


def test_custo_medio_ponderado_e_idempotencia_do_recebimento(client, admin_headers):
    material_id, almox_id, fornecedor_id = _setup_material_almox(client, admin_headers)

    _, r = _receber_pedido(client, admin_headers, fornecedor_id, almox_id, material_id, 100, 10)
    assert r.status_code == 200
    r = client.get("/materiais", headers=admin_headers)
    assert [m for m in r.json() if m["id"] == material_id][0]["custo_medio"] == 10.0

    # Recebe de novo o MESMO pedido (idempotente -- nao duplica saldo).
    pedido_id, _ = _receber_pedido(client, admin_headers, fornecedor_id, almox_id, material_id, 100, 10)
    # (a chamada acima criou um pedido NOVO -- para testar idempotencia de fato, reenviamos o status)
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=admin_headers)
    assert r.status_code == 200

    r = client.get("/estoque", headers=admin_headers)
    saldo_apos_2_recebimentos = sum(i["quantidade"] for i in r.json() if i["material_id"] == material_id)
    assert saldo_apos_2_recebimentos == 200.0  # 100 do primeiro pedido + 100 do segundo, sem duplicar o 2o

    # Media ponderada com um 3o pedido a preco diferente: (200@10 + 100@20) / 300 = 13.333...
    _receber_pedido(client, admin_headers, fornecedor_id, almox_id, material_id, 100, 20)
    r = client.get("/materiais", headers=admin_headers)
    custo_medio = [m for m in r.json() if m["id"] == material_id][0]["custo_medio"]
    assert round(custo_medio, 2) == 13.33


def test_saida_vinculada_a_obra_valoriza_custo_realizado(client, admin_headers):
    material_id, almox_id, fornecedor_id = _setup_material_almox(client, admin_headers)
    _receber_pedido(client, admin_headers, fornecedor_id, almox_id, material_id, 100, 15)

    r = client.post("/obras", json={"wl": "OBRA-CUSTO", "status": "proposta"}, headers=admin_headers)
    obra_id = r.json()["id"]

    r = client.post(
        "/estoque/movimentacoes",
        json={"almoxarifado_id": almox_id, "material_id": material_id, "obra_id": obra_id, "tipo": "saida", "quantidade": 10},
        headers=admin_headers,
    )
    assert r.status_code == 201

    r = client.get(f"/obras/{obra_id}", headers=admin_headers)
    assert r.json()["custo_realizado"] == 150.0  # 10 * 15


def test_saida_maior_que_saldo_e_bloqueada(client, admin_headers):
    material_id, almox_id, _ = _setup_material_almox(client, admin_headers)
    r = client.post(
        "/estoque/movimentacoes",
        json={"almoxarifado_id": almox_id, "material_id": material_id, "tipo": "saida", "quantidade": 5},
        headers=admin_headers,
    )
    assert r.status_code == 422


def test_requisicao_automatica_por_estoque_minimo_sem_duplicar(client, admin_headers):
    material_id, almox_id, _ = _setup_material_almox(client, admin_headers, estoque_minimo=5)
    client.put("/estoque", json={"almoxarifado_id": almox_id, "material_id": material_id, "quantidade": 10}, headers=admin_headers)

    # Saldo cai para 6 (acima do minimo) -> nao gera requisicao.
    client.post(
        "/estoque/movimentacoes",
        json={"almoxarifado_id": almox_id, "material_id": material_id, "tipo": "saida", "quantidade": 4},
        headers=admin_headers,
    )
    r = client.get("/requisicoes-compra", params={"origem_automatica": True}, headers=admin_headers)
    assert len(r.json()) == 0

    # Saldo cai para 3 (<= minimo) -> gera 1 requisicao.
    client.post(
        "/estoque/movimentacoes",
        json={"almoxarifado_id": almox_id, "material_id": material_id, "tipo": "saida", "quantidade": 3},
        headers=admin_headers,
    )
    r = client.get("/requisicoes-compra", params={"origem_automatica": True}, headers=admin_headers)
    assert len(r.json()) == 1
    assert r.json()[0]["itens"][0]["quantidade"] == 2  # 5 (minimo) - 3 (saldo)

    # Nova saida com a requisicao ainda aberta -> nao duplica.
    client.post(
        "/estoque/movimentacoes",
        json={"almoxarifado_id": almox_id, "material_id": material_id, "tipo": "saida", "quantidade": 1},
        headers=admin_headers,
    )
    r = client.get("/requisicoes-compra", params={"origem_automatica": True}, headers=admin_headers)
    assert len(r.json()) == 1
