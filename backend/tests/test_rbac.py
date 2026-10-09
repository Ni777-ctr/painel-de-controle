"""Etapa 6: RBAC granular por perfil sobre transicoes de status (obra e
pedido de compra)."""
from tests.conftest import criar_perfil, criar_usuario


def _login(client, credenciais):
    r = client.post("/auth/login", json=credenciais)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_perfil_so_com_permissao_de_transicao_nao_edita_outros_campos(client, db_session, admin_headers):
    criar_perfil(db_session, perfil_id="programacao", permissoes=["obras:read", "obras:transicao:contratada:em_execucao"])
    creds = criar_usuario(db_session, usuario="prog", perfil_id="programacao")
    headers_prog = _login(client, creds)

    r = client.post("/equipes", json={"nome": "Equipe Alfa"}, headers=admin_headers)
    equipe_id = r.json()["id"]
    r = client.post("/obras", json={"wl": "RBAC-1", "status": "proposta"}, headers=admin_headers)
    obra_id = r.json()["id"]
    client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=admin_headers)

    # Nao pode editar campo fora da transicao.
    r = client.patch(f"/obras/{obra_id}", json={"valor_contrato": 999}, headers=headers_prog)
    assert r.status_code == 403

    # Pode fazer a transicao para a qual tem permissao, com equipe_id junto.
    r = client.patch(f"/obras/{obra_id}", json={"status": "em_execucao", "equipe_id": equipe_id}, headers=headers_prog)
    assert r.status_code == 200

    # Nao pode fazer uma transicao para a qual NAO tem permissao.
    r = client.patch(f"/obras/{obra_id}", json={"status": "concluida"}, headers=headers_prog)
    assert r.status_code == 403


def test_visualizador_nao_transiciona_nem_edita(client, db_session, admin_headers):
    criar_perfil(db_session, perfil_id="visualizador", permissoes=["obras:read"])
    creds = criar_usuario(db_session, usuario="viewer", perfil_id="visualizador")
    headers_viewer = _login(client, creds)

    r = client.post("/obras", json={"wl": "RBAC-2", "status": "proposta"}, headers=admin_headers)
    obra_id = r.json()["id"]

    r = client.patch(f"/obras/{obra_id}", json={}, headers=headers_viewer)
    assert r.status_code == 403
    r = client.patch(f"/obras/{obra_id}", json={"status": "contratada"}, headers=headers_viewer)
    assert r.status_code == 403


def test_almoxarifado_recebe_pedido_sem_compras_write(client, db_session, admin_headers):
    criar_perfil(
        db_session,
        perfil_id="almoxarifado",
        permissoes=["estoque:read", "estoque:write", "compras:read", "compras:transicao:Enviado:Recebido"],
    )
    creds = criar_usuario(db_session, usuario="almox", perfil_id="almoxarifado")
    headers_almox = _login(client, creds)

    r = client.post("/fornecedores", json={"nome": "Forn"}, headers=admin_headers)
    fornecedor_id = r.json()["id"]
    r = client.post("/almoxarifados", json={"nome": "Almox"}, headers=admin_headers)
    almox_id = r.json()["id"]
    r = client.post("/materiais", json={"nome": "Mat", "unidade": "UN"}, headers=admin_headers)
    material_id = r.json()["id"]
    r = client.post(
        "/pedidos-compra",
        json={"fornecedor_id": fornecedor_id, "almoxarifado_id": almox_id, "itens": [{"material_id": material_id, "quantidade": 5, "valor_unitario": 2}]},
        headers=admin_headers,
    )
    pedido_id = r.json()["id"]

    # Nao pode pular etapa mesmo tendo a permissao de Enviado->Recebido.
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=headers_almox)
    assert r.status_code == 422

    client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Enviado"}, headers=admin_headers)

    # Agora sim, sem ter compras:write.
    r = client.patch(f"/pedidos-compra/{pedido_id}", json={"status": "Recebido"}, headers=headers_almox)
    assert r.status_code == 200
