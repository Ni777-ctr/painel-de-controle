"""Painel unificado + notificacoes (geracao, dedup, destinatarios, leitura, e-mail)."""
from datetime import date, datetime, timedelta, timezone

from app.models.automacao import Automacao, ExecucaoAutomacao
from app.models.financeiro import Fatura
from app.models.frota import ManutencaoVeiculo, Veiculo
from app.models.notificacao import Notificacao
from app.models.obra import Obra
from app.services import email_service, notificacao_service
from tests.conftest import criar_perfil, criar_usuario


def _login(client, cred):
    r = client.post("/auth/login", json=cred)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _semear_pendencias(db_session):
    db = db_session()
    hoje = date.today()
    obra = Obra(wl="OBR-ATRASADA", status="em_execucao", data_fim=hoje - timedelta(days=3), valor_contrato=1000)
    db.add(obra)
    db.flush()
    db.add(Fatura(obra_id=obra.id, valor=500, vencimento=hoje - timedelta(days=2), status="Emitida"))
    v = Veiculo(placa="ABC1D23", modelo="Hilux", status="Ativo", licenciamento_vence_em=hoje - timedelta(days=1))
    db.add(v)
    db.flush()
    db.add(ManutencaoVeiculo(veiculo_id=v.id, descricao="Troca de oleo", data_prevista=hoje - timedelta(days=5), status="Agendada"))
    a = Automacao(nome="Bot SIGEO", gatilho="cron", acao={}, ativo=True)
    db.add(a)
    db.flush()
    db.add(ExecucaoAutomacao(automacao_id=a.id, status="falha", mensagem="Timeout no portal"))
    db.commit()
    db.close()


def test_painel_agrega_alertas_de_todas_as_areas(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    r = client.get("/painel/gerencia", headers=admin_headers)
    assert r.status_code == 200, r.text
    corpo = r.json()
    tipos = {a["tipo"] for a in corpo["alertas"]}
    assert {"obra_atrasada", "fatura_vencida", "manutencao_vencida", "licenciamento_vencido", "automacao_falhou"} <= tipos
    assert corpo["obras"]["atrasadas"] == 1
    assert corpo["faturamento"]["faturas_atrasadas"] == 1
    assert corpo["frota"]["manutencoes_atrasadas"] == 1
    assert corpo["automacoes"]["com_falha"] == 1
    # criticos primeiro
    assert corpo["alertas"][0]["nivel"] == "critico"
    assert corpo["totais_por_nivel"]["critico"] >= 5


def test_painel_oculta_secoes_sem_permissao(client, db_session, admin_headers):
    _semear_pendencias(db_session)
    criar_perfil(db_session, perfil_id="so-obras", permissoes=["dashboard:read", "obras:read"])
    cred = criar_usuario(db_session, usuario="gerente", perfil_id="so-obras")
    h = _login(client, cred)
    corpo = client.get("/painel/gerencia", headers=h).json()
    assert corpo["obras"] is not None
    assert corpo["faturamento"] is None and corpo["frota"] is None and corpo["automacoes"] is None
    assert {a["modulo"] for a in corpo["alertas"]} == {"obras"}


def test_painel_exige_permissao(client, db_session):
    criar_perfil(db_session, perfil_id="sem-dash", permissoes=["obras:read"])
    h = _login(client, criar_usuario(db_session, usuario="x", perfil_id="sem-dash"))
    assert client.get("/painel/gerencia", headers=h).status_code == 403


def test_processar_gera_notificacoes_uma_vez_por_evento(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    r1 = client.post("/notificacoes/processar", headers=admin_headers)
    assert r1.status_code == 200, r1.text
    assert r1.json()["novas"] >= 5
    # Idempotente: rodar de novo nao duplica
    r2 = client.post("/notificacoes/processar", headers=admin_headers)
    assert r2.json()["novas"] == 0

    lista = client.get("/notificacoes", headers=admin_headers).json()
    assert len(lista) == r1.json()["novas"]
    assert client.get("/notificacoes/contagem", headers=admin_headers).json()["criticas"] >= 4


def test_notificacoes_respeitam_permissao_do_destinatario(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    criar_perfil(db_session, perfil_id="so-frota", permissoes=["frota:read"])
    h = _login(client, criar_usuario(db_session, usuario="frotista", perfil_id="so-frota"))
    client.post("/notificacoes/processar", headers=admin_headers)
    mods = {n["modulo"] for n in client.get("/notificacoes", headers=h).json()}
    assert mods == {"frota"}


def test_marcar_lida_e_isolamento_entre_usuarios(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    criar_perfil(db_session, perfil_id="obras", permissoes=["obras:read"])
    h2 = _login(client, criar_usuario(db_session, usuario="outro", perfil_id="obras"))
    client.post("/notificacoes/processar", headers=admin_headers)

    minha = client.get("/notificacoes", headers=admin_headers).json()[0]
    # outro usuario nao consegue marcar a notificacao alheia
    assert client.patch(f"/notificacoes/{minha['id']}/lida", headers=h2).status_code == 404
    assert client.patch(f"/notificacoes/{minha['id']}/lida", headers=admin_headers).json()["lida"] is True

    antes = client.get("/notificacoes/contagem", headers=admin_headers).json()["nao_lidas"]
    assert client.post("/notificacoes/marcar-todas-lidas", headers=admin_headers).json()["nao_lidas"] == 0
    assert antes > 0
    assert client.get("/notificacoes?somente_nao_lidas=true", headers=admin_headers).json() == []


def test_processar_exige_permissao(client, db_session):
    criar_perfil(db_session, perfil_id="comum", permissoes=["obras:read"])
    h = _login(client, criar_usuario(db_session, usuario="comum", perfil_id="comum"))
    assert client.post("/notificacoes/processar", headers=h).status_code == 403


def test_bloqueio_de_conta_notifica_quem_gerencia_usuarios(client, admin_headers, db_session):
    criar_usuario(db_session, usuario="alvo", perfil_id="administrador", senha="correta")
    for _ in range(5):
        client.post("/auth/login", json={"usuario": "alvo", "senha": "errada"})
    notifs = client.get("/notificacoes", headers=admin_headers).json()
    assert any(n["tipo"] == "conta_bloqueada" and "alvo" in n["titulo"] for n in notifs)


def test_email_enviado_e_falha_registrada(client, admin_headers, db_session, monkeypatch):
    _semear_pendencias(db_session)
    db = db_session()
    from app.models.usuario import Usuario

    db.query(Usuario).filter(Usuario.usuario == "admin").update({Usuario.email: "admin@exemplo.com"})
    db.commit()
    db.close()

    enviados = []
    monkeypatch.setattr(email_service, "email_disponivel", lambda: True)

    def fake_envio(dest, assunto, texto, html=None):
        if "Bot SIGEO" in assunto:
            raise RuntimeError("SMTP caiu")
        enviados.append((dest, assunto))

    monkeypatch.setattr(email_service, "enviar_email", fake_envio)
    r = client.post("/notificacoes/processar", headers=admin_headers).json()
    assert r["enviados"] >= 4 and r["falhas"] == 1
    assert all(d == "admin@exemplo.com" for d, _ in enviados)

    db = db_session()
    falha = db.query(Notificacao).filter(Notificacao.email_status == "falhou").one()
    assert "SMTP caiu" in falha.email_erro and falha.email_tentativas == 1
    # info (medicao sem fatura etc.) nao gera e-mail
    assert db.query(Notificacao).filter(Notificacao.nivel == "info", Notificacao.email_status.isnot(None)).count() == 0
    db.close()


def test_sem_smtp_marca_ignorado_em_vez_de_reprocessar(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    db = db_session()
    from app.models.usuario import Usuario

    db.query(Usuario).filter(Usuario.usuario == "admin").update({Usuario.email: "admin@exemplo.com"})
    db.commit()
    db.close()
    r = client.post("/notificacoes/processar", headers=admin_headers).json()
    assert r["enviados"] == 0 and r["ignorados"] >= 4
    # segunda rodada nao tem mais nada na fila
    assert client.post("/notificacoes/processar", headers=admin_headers).json()["ignorados"] == 0


def test_preferencia_de_email_desligada_nao_enfileira(client, admin_headers, db_session):
    _semear_pendencias(db_session)
    db = db_session()
    from app.models.usuario import Usuario

    db.query(Usuario).filter(Usuario.usuario == "admin").update({Usuario.email: "a@b.com"})
    db.commit()
    db.close()
    assert client.put("/notificacoes/preferencias", json={"notificacoes_email": False}, headers=admin_headers).json() == {"notificacoes_email": False}
    client.post("/notificacoes/processar", headers=admin_headers)
    db = db_session()
    assert db.query(Notificacao).filter(Notificacao.email_status.isnot(None)).count() == 0
    db.close()


def test_registrar_execucao_de_automacao_com_falha_vira_alerta(client, admin_headers):
    a = client.post("/automacoes", json={"nome": "SIGEOhelper", "gatilho": "diario"}, headers=admin_headers).json()
    assert client.post(f"/automacoes/{a['id']}/execucoes", json={"status": "sucesso"}, headers=admin_headers).status_code == 201
    painel = client.get("/painel/gerencia", headers=admin_headers).json()
    assert painel["automacoes"]["com_falha"] == 0
    assert client.post(f"/automacoes/{a['id']}/execucoes", json={"status": "falha", "mensagem": "login recusado"}, headers=admin_headers).status_code == 201
    painel = client.get("/painel/gerencia", headers=admin_headers).json()
    assert painel["automacoes"]["com_falha"] == 1
    assert client.post(f"/automacoes/{a['id']}/execucoes", json={"status": "talvez"}, headers=admin_headers).status_code == 422
    assert len(client.get(f"/automacoes/{a['id']}/execucoes", headers=admin_headers).json()) == 2


def test_meta_mensal_em_risco_a_partir_do_dia_de_alerta(client, admin_headers, db_session):
    from app.services import pendencias_service

    db = db_session()
    dia_alerta_passado = date(2026, 9, 25)
    tipos = {p.tipo for p in pendencias_service.coletar_pendencias(db, dia_alerta_passado)}
    assert "meta_mensal_em_risco" in tipos
    tipos_antes = {p.tipo for p in pendencias_service.coletar_pendencias(db, date(2026, 9, 10))}
    assert "meta_mensal_em_risco" not in tipos_antes
    db.close()


def test_lembrete_exportacao_mensal_da_frota(client, admin_headers, db_session):
    from app.services import pendencias_service

    db = db_session()
    db.add(Veiculo(placa="XYZ9K88", modelo="Fiorino", status="Ativo"))
    db.commit()
    assert "frota_exportacao_mensal" in {p.tipo for p in pendencias_service.coletar_pendencias(db, date(2026, 10, 2))}
    assert "frota_exportacao_mensal" not in {p.tipo for p in pendencias_service.coletar_pendencias(db, date(2026, 10, 20))}
    # Depois de uma exportacao da frota no mes, o lembrete some (data fixa => teste deterministico).
    from app.models.relatorio import RelatorioGerado
    from app.models.usuario import Usuario

    uid = db.query(Usuario.id).filter(Usuario.usuario == "admin").scalar()
    db.add(RelatorioGerado(
        usuario_id=uid, tipo="frota", formato="xlsx", nome_arquivo="frota.xlsx",
        criado_em=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc),
    ))
    db.commit()
    assert "frota_exportacao_mensal" not in {p.tipo for p in pendencias_service.coletar_pendencias(db, date(2026, 10, 2))}
    db.close()
