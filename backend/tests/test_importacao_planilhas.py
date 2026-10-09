from datetime import date
from decimal import Decimal

import pytest

from app.importacao import relatorio
from app.importacao.aplicar import ImportacaoErro, aplicar
from app.importacao.codigos import codigo_valido, normalizar_codigo, regional_do_codigo
from app.importacao.leitor import normalizar_cabecalho, para_decimal
from app.importacao.parsers import MOTIVO_GLOSA_IMPORTADA, ler_planilhas
from app.models.auditoria import AuditLog
from app.models.cliente import Cliente
from app.models.equipe import Equipe
from app.models.financeiro import Fatura, Glosa, Medicao
from app.models.obra import Obra, Programacao
from app.models.planilha import ExecucaoObra, GeradorProgramacao, InventarioObra, SigeoExtracao
from tests import planilhas_sinteticas as P


@pytest.fixture()
def arquivos(tmp_path):
    f, p = tmp_path / "FATURAMENTO.xlsx", tmp_path / "PROGRAMACAO_TEES.xlsx"
    P.faturamento(f)
    P.programacao(p)
    return f, p


@pytest.fixture()
def dados(arquivos):
    return ler_planilhas(*arquivos)


def _estat(dados, aba):
    return next(e for e in dados.estat if e.aba == aba)


def _motivos(dados, aba):
    return sorted(r.motivo for r in dados.rejeicoes if r.aba == aba)


# ---------------- codigos e conversores ----------------
def test_codigos_do_relatorio():
    assert codigo_valido(normalizar_codigo(" dmp/a.sul.25.00419 ")) and regional_do_codigo("DMP/A.SUL.25.00419") == "A.SUL"
    for ruim in ("DMP/A.SUL25.06647", "DAC/A,SUL.26.00403", "DMP/A.SUL.26.2128", "DMP/A.SUL.25.007392", "PROG++"):
        assert not codigo_valido(normalizar_codigo(ruim)), ruim


def test_conversores():
    assert para_decimal("R$ 1.484,10") == Decimal("1484.10") and para_decimal("#N/A") is None and para_decimal(";") is None
    assert normalizar_cabecalho("Valor (R$) Faturado") == "VALOR R FATURADO"


# ---------------- obras ----------------
def test_universo_de_obras_e_regional(dados):
    assert set(dados.obras) == {P.A, P.B, P.D, P.E, P.F, P.H, P.G}
    assert dados.obras[P.A]["regional"] == "A.SUL" and dados.obras[P.D]["regional"] == "A.NOR"
    assert "codigo fora do padrao" in _motivos(dados, "CGO")
    assert [r.projeto for r in dados.rejeicoes if r.aba == "CGO"] == [P.INVALIDO_1]


def test_valores_da_cgo_prevalecem_e_conflitos_sao_listados(dados):
    a = dados.obras[P.A]
    assert a["necs_planejados"] == Decimal("1234.567") and a["avanco_realizado"] == Decimal("50.00")
    assert a["observacoes"] == "obs da CGO" and a["data_fim"] == date(2027, 12, 1)
    assert dados.obras[P.B]["necs_planejados"] == Decimal("100.500")  # UPS ORCADO em texto
    assert dados.total_conflitos == 2 and {c["campo"] for c in dados.conflitos} == {"necs_planejados"}
    # colunas sem campo proprio ficam guardadas, por fonte
    assert a["dados_planilha"]["CGO"]["CONTRATO"] == 4600004258 and a["dados_planilha"]["CARTEIRA_SOT"]["STATUS SAP"] == "MEDI"


def test_cliente_so_com_nome_real_e_sem_duplicar(dados):
    assert sorted(dados.clientes.values()) == ["A 2 TRANSPORTES LTDA", "ENEL CLIENTE FINAL SA"]
    assert dados.obras[P.A]["cliente_nome"] is None  # "-" nao vira cliente (D2)


def test_arquivo_morto(dados):
    assert dados.arquivados == {P.D, "DAC/A.ABC.99.99999"}
    assert _motivos(dados, "ARQUIVO MORTO") == ["codigo fora do padrao"]


# ---------------- medicao ----------------
def test_medicao_regras_e_conciliacao(dados):
    est = next(e for e in dados.estat if e.destino.startswith("medicoes"))
    assert est.lidas == 6 and est.aceitas == 4
    assert _motivos(dados, est.aba) == ["duplicidade projeto+ciclo", "projeto sem obra"]
    m = {(x["wl"], x["ciclo"]): x for x in dados.medicoes}
    primeira = m[(P.A, "C1")]
    assert primeira["necs_medidos"] == Decimal("22.120") and primeira["percentual"] == Decimal("50.00")  # 22,12 / 44,24
    assert primeira["glosado"] == Decimal("100.00") and primeira["data_emissao_nf"] == date(2026, 3, 10)
    assert m[(P.D, "C1")]["valor_faturado"] == Decimal("1484.10")           # texto "R$ 1.484,10"
    layout_simples = m[(P.E, "C2")]
    assert layout_simples["familia"] == "AC" and layout_simples["area"] is None  # familia veio na coluna Area
    assert m[(P.F, "C1")]["valor_faturado"] is None                          # #N/A
    t = dados.totais_medicao
    assert t["lido_numerico"] == Decimal("1003.5") and t["lido_texto"] == Decimal("1984.10") and t["celulas_texto"] == 2
    assert t["aceito"] == Decimal("2984.60") and t["nf_sim_sem_data"] == 1 and t["celulas_erro"] == 1


# ---------------- tabelas novas ----------------
def test_inventario_so_entra_com_obra(dados):
    assert len(dados.inventarios) == 2  # o projeto repetido e' mantido (sao ciclos diferentes)
    assert _motivos(dados, "INVENTARIO") == ["codigo fora do padrao", "projeto sem obra"]
    assert dados.inventarios[0]["valor_inventario"] == Decimal("990.00") and dados.inventarios[0]["data_inventario"] == date(2026, 2, 1)


def test_execucao_mantem_historico_sem_obra(dados):
    assert len(dados.execucoes) == 2
    sem = next(x for x in dados.execucoes if x["projeto_codigo"] == P.SEM_OBRA)
    assert sem["tem_obra"] is False and dados.execucoes[0]["nec_executada"] == Decimal("4.500")
    assert dados.execucoes[0]["dados_extras"] == {"COLUNA NOVA": "extra!"}


def test_sigeo_cria_obra_so_com_codigo_e_ignora_colunas_auxiliares(dados):
    assert len(dados.sigeo) == 1 and dados.sigeo[0]["horario_inicio"] == "08:30" and dados.sigeo[0]["chi"] == Decimal("12.500")
    assert dados.sigeo[0]["dados_extras"] is None  # CONCATENAR e' auxiliar
    assert dados.obras[P.G]["fontes"] == ["SIGEO"]
    assert _motivos(dados, "EXTRAÇÃO SIGEO") == ["codigo fora do padrao"]


def test_gerador(dados):
    assert [g["projeto_codigo"] for g in dados.geradores] == [P.A, "DMP/A.ABC.26.55555"]
    assert dados.geradores[1]["tem_obra"] is False and dados.geradores[0]["dados_extras"] == {"CARREGAMENTO": 0.8}
    assert _motivos(dados, "GERADOR") == ["codigo fora do padrao"]


# ---------------- programacao ----------------
def test_programacao_regras_de_validacao(dados):
    est = _estat(dados, "PROGRAMAÇÃO")
    assert est.erro is None and est.aceitas == 3
    assert _motivos(dados, "PROGRAMAÇÃO") == sorted([
        "% PROG fora de 0-1", "codigo fora do padrao", "duplicidade (projeto+data+equipe)", "projeto sem obra",
        "sem data", "sem equipe (encarregado)", "sem projeto",
    ])
    # cabecalho na linha 6, comecando na coluna C
    assert est.colunas_usadas["projeto"] == "PROJETO" and est.colunas_usadas["equipe"] == "EQUIPE"
    # linha informada = linha real do Excel (duplicidade esta na 10a linha: 6 + 4)
    dup = next(r for r in dados.rejeicoes if r.aba == "PROGRAMAÇÃO" and r.motivo.startswith("duplicidade"))
    assert dup.linha == 10 and dup.projeto == P.A


def test_programacao_equipes_status_e_extras(dados):
    assert sorted(dados.equipes.values()) == ["João Silva", "Maria"]  # "JOÃO  SILVA" == "João Silva"
    status = [p["status"] for p in dados.programacoes]
    assert status == ["Programada", "Concluida", "Programada"]
    assert dict(dados.status_prog_nao_reconhecidos) == {"STATUS ESTRANHO": 1}
    assert dados.programacoes[0]["dados_planilha"] == {"PROG.1": "x", "QTD LM": 3}


def test_erros_claros_quando_a_planilha_nao_bate(tmp_path):
    f, p = tmp_path / "f.xlsx", tmp_path / "p.xlsx"
    P.faturamento(f, sem_aba_medicao=True)
    P.programacao(p, sem_coluna_equipe=True)
    d = ler_planilhas(f, p)
    erros = {e.aba: e.erro for e in d.estat if e.erro}
    assert any("MEDICAO" in v and "nao encontrada" in v for v in erros.values())
    assert "equipe" in erros["PROGRAMAÇÃO"] and d.programacoes == []
    p2 = tmp_path / "p2.xlsx"
    P.programacao(p2, sem_aba_programacao=True)
    assert any("PROGRAMACAO" in (e.erro or "") for e in ler_planilhas(None, p2).estat)


# ---------------- aplicar no banco ----------------
def _contagens(db):
    return {m.__name__: db.query(m).count() for m in (
        Obra, Cliente, Equipe, Medicao, Glosa, Programacao, InventarioObra, ExecucaoObra, SigeoExtracao, GeradorProgramacao)}


def test_aplicar_grava_tudo_e_e_idempotente(arquivos, db_session):
    dados = ler_planilhas(*arquivos)
    db = db_session()
    resumo = aplicar(db, dados)
    db.commit()
    esperado = {"Obra": 7, "Cliente": 2, "Equipe": 2, "Medicao": 4, "Glosa": 1, "Programacao": 3,
                "InventarioObra": 2, "ExecucaoObra": 2, "SigeoExtracao": 1, "GeradorProgramacao": 2}
    assert _contagens(db) == esperado
    assert resumo["obras_criadas"] == 7 and resumo["obras_arquivadas"] == 1 and resumo["arquivo_morto_sem_obra"] == 1

    a = db.query(Obra).filter_by(wl=P.A).one()
    assert float(a.necs_planejados) == 1234.567 and float(a.avanco_realizado) == 50 and a.regional == "A.SUL"
    assert float(a.necs_faturados) == 22.12 + 1 - 1  # so a medicao aceita do ciclo C1 (a duplicada foi rejeitada)
    assert db.query(Obra).filter_by(wl=P.D).one().arquivada is True and a.arquivada is False
    e = db.query(Obra).filter_by(wl=P.E).one()
    assert e.cliente.nome == "A 2 TRANSPORTES LTDA" and e.cliente_id == db.query(Obra).filter_by(wl=P.F).one().cliente_id

    m = db.query(Medicao).filter_by(obra_id=a.id).one()
    assert m.status == "Rascunho" and m.origem and m.emitida_nf is True and float(m.valor_faturado) == 1000.5
    assert m.criado_em.date() == date(2026, 3, 10)  # criado_em = data de emissao da NF
    g = db.query(Glosa).one()
    assert g.motivo == MOTIVO_GLOSA_IMPORTADA and g.resolvida is True and float(g.valor) == 100
    assert db.query(Fatura).count() == 0  # D1: nenhuma fatura inventada

    assert db.query(ExecucaoObra).filter(ExecucaoObra.obra_id.is_(None)).count() == 1  # historico sem obra mantido
    assert db.query(Programacao).filter(Programacao.origem.isnot(None)).count() == 3
    assert db.query(AuditLog).filter_by(acao="importacao_planilhas").one().bot == "importacao_planilhas"

    # idempotencia: reimportar nao duplica nada
    aplicar(db, ler_planilhas(*arquivos))
    db.commit()
    assert _contagens(db) == esperado
    db.close()


def test_reimportar_respeita_edicao_manual(arquivos, db_session):
    db = db_session()
    aplicar(db, ler_planilhas(*arquivos))
    db.commit()
    a = db.query(Obra).filter_by(wl=P.A).one()
    a.observacoes, a.necs_planejados = "editado a mao", 5
    db.commit()
    aplicar(db, ler_planilhas(*arquivos))
    db.commit()
    db.refresh(a)
    assert a.observacoes == "editado a mao" and float(a.necs_planejados) == 5
    aplicar(db, ler_planilhas(*arquivos), sobrescrever=True)
    db.commit()
    db.refresh(a)
    assert a.observacoes == "obs da CGO" and float(a.necs_planejados) == 1234.567
    db.close()


def test_glosas_pendentes_opcional(arquivos, db_session):
    db = db_session()
    aplicar(db, ler_planilhas(*arquivos), glosas_resolvidas=False)
    db.commit()
    assert db.query(Glosa).one().resolvida is False
    db.close()


def test_bloqueia_reimportacao_se_ha_fatura_nas_medicoes_importadas(arquivos, db_session):
    db = db_session()
    aplicar(db, ler_planilhas(*arquivos))
    db.commit()
    m = db.query(Medicao).first()
    db.add(Fatura(obra_id=m.obra_id, medicao_id=m.id, valor=1, vencimento=date(2030, 1, 1)))
    db.commit()
    with pytest.raises(ImportacaoErro):
        aplicar(db, ler_planilhas(*arquivos))
    db.rollback()
    assert db.query(Medicao).count() == 4  # nada foi perdido
    db.close()


def test_importado_nao_gera_alertas_falsos(arquivos, db_session):
    from app.services.pendencias_service import coletar_pendencias

    db = db_session()
    aplicar(db, ler_planilhas(*arquivos))
    db.commit()
    tipos = {(p.tipo, p.entidade_id) for p in coletar_pendencias(db)}
    d_id = str(db.query(Obra).filter_by(wl=P.D).one().id)
    assert ("obra_atrasada", d_id) not in tipos                       # obra arquivada nao alerta
    assert not any(t == "programacao_pendente" for t, _ in tipos)      # historico antigo nao alerta
    assert not any(t == "glosa_pendente" for t, _ in tipos)            # glosa importada entra como resolvida
    db.close()


# ---------------- relatorio e CLI ----------------
def test_relatorio_markdown_e_csv(dados, tmp_path):
    pasta = relatorio.gravar(dados, None, tmp_path / "saida")
    md = (pasta / "relatorio.md").read_text(encoding="utf-8")
    assert "SIMULACAO (nada foi gravado)" in md and "R$ 1.003,50" in md and "R$ 1.984,10" in md
    assert "duplicidade projeto+ciclo" in md and "DMP/A.SUL25.06647" in md and "STATUS ESTRANHO" in md
    linhas = (pasta / "rejeicoes.csv").read_text(encoding="utf-8-sig").splitlines()
    assert linhas[0] == "arquivo;aba;linha;projeto;motivo;detalhe" and len(linhas) == 1 + len(dados.rejeicoes)
    assert (pasta / "relatorio.json").exists()


def test_cli_simulacao_nao_abre_banco(arquivos, tmp_path, monkeypatch, capsys):
    import app.database as database
    from app.importacao.__main__ import main

    def proibido(*a, **k):
        raise AssertionError("a simulacao nao pode abrir sessao de banco")

    monkeypatch.setattr(database, "SessionLocal", proibido)
    rc = main(["--faturamento", str(arquivos[0]), "--programacao", str(arquivos[1]), "--saida", str(tmp_path / "o")])
    out = capsys.readouterr().out
    assert rc == 0 and "SIMULACAO" in out and "7 obras" in out and (tmp_path / "o" / "rejeicoes.csv").exists()


def test_cli_confirmar_grava(arquivos, tmp_path, monkeypatch, db_session):
    import app.database as database
    from app.importacao.__main__ import main

    monkeypatch.setattr(database, "SessionLocal", db_session)
    rc = main(["--faturamento", str(arquivos[0]), "--programacao", str(arquivos[1]), "--saida", str(tmp_path / "o"), "--confirmar"])
    assert rc == 0
    db = db_session()
    assert db.query(Obra).count() == 7 and db.query(Programacao).count() == 3
    assert "GRAVADO NO BANCO" in (tmp_path / "o" / "relatorio.md").read_text(encoding="utf-8")
    db.close()


def test_cli_valida_argumentos(tmp_path, capsys):
    from app.importacao.__main__ import main

    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["--faturamento", str(tmp_path / "nao_existe.xlsx")])
