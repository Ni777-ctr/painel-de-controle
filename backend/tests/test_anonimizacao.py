"""Anonimizador de homologacao: travas de seguranca, cobertura de colunas e efeito sobre os dados."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.models.auditoria import AuditLog
from app.models.cliente import Cliente
from app.models.compras import Fornecedor
from app.models.frota import Veiculo
from app.models.obra import Obra
from app.models.parametro import ParametroGlobal
from app.models.supervisao import Empreiteira, RelatorioSupervisao
from app.models.usuario import Perfil, RefreshToken, Usuario
from app.schemas.supervisao import cnpj_valido
from app.security import hash_senha, verificar_senha
from scripts import anonimizar_homologacao as an


def test_trava_do_nome_do_banco():
    for ruim in ["eletrogestor", "neondb", "postgres", "producao", "/data/eletrogestor.db", ""]:
        with pytest.raises(SystemExit):
            an.validar_nome_banco(ruim)
    for bom in ["eletrogestor_homolog", "HOMOLOG_eletro", "/tmp/x/homologacao.db"]:
        an.validar_nome_banco(bom)  # nao levanta


def test_nenhuma_coluna_de_texto_sem_classificacao():
    """Se este teste falhar, uma coluna nova de texto/JSON apareceu: decida se anonimiza ou preserva
    (ESTRATEGIAS / PRESERVADAS em scripts/anonimizar_homologacao.py) antes de usar dados reais."""
    assert an.colunas_nao_classificadas() == []


def test_estrategias_so_referenciam_tabelas_e_colunas_existentes():
    from app.database import Base

    for tabela, cols in an.ESTRATEGIAS.items():
        assert tabela in Base.metadata.tables, tabela
        for c in cols:
            assert c in Base.metadata.tables[tabela].c, f"{tabela}.{c}"
    for tabela, cols in an.PRESERVADAS.items():
        assert tabela in Base.metadata.tables, tabela
        for c in cols:
            assert c in Base.metadata.tables[tabela].c, f"{tabela}.{c}"


def test_cnpj_sintetico_valido_unico_e_formatado():
    gerados = {an.cnpj_sintetico(i) for i in range(1, 200)}
    assert len(gerados) == 199
    assert all(cnpj_valido("".join(ch for ch in g if ch.isdigit())) for g in gerados)


def _popular(db_session):
    db = db_session()
    db.add(Perfil(id="supervisor", nome="Supervisor", descricao="d", categoria="OPERACAO", permissoes=["supervisao:read"]))
    db.flush()
    u1 = Usuario(nome="Maria da Silva", usuario="maria.silva", email="maria@empresa.com.br", senha_hash=hash_senha("SenhaReal#1"),
                 perfil_id="supervisor", mfa_habilitado=True, mfa_secret="SEGREDOMFA", convite_token_hash="a" * 64)
    u2 = Usuario(nome="Joao Souza", usuario="joao", email=None, senha_hash=hash_senha("outra"), perfil_id="supervisor")
    db.add_all([u1, u2]); db.flush()
    db.add(RefreshToken(usuario_id=u1.id, token_hash="b" * 64, expira_em=datetime.now(timezone.utc) + timedelta(days=1)))
    db.add(AuditLog(usuario_id=u1.id, acao="usuario_criado", entidade="usuarios", ip="200.1.2.3", user_agent="Mozilla",
                    antes={"email": "maria@empresa.com.br"}, depois={"nome": "Maria da Silva"}))
    db.add(Cliente(nome="ENEL Distribuicao SA", documento="33.050.071/0001-58", contato="Carlos", telefone="(11) 99999-1111",
                   email="carlos@enel.com", endereco="Av Real 100"))
    db.add(Fornecedor(nome="Fornecedor Real Ltda", documento="12.345.678/0001-95", contato="Ana", telefone="1133334444", email="ana@forn.com"))
    db.add(Veiculo(placa="ABC1D23", modelo="Hilux", tipo="Utilitario", ano=2022, regional="A.SUL", km_atual=1000))
    db.add(Obra(wl="DMP/A.SUL.25.00419", descricao="Rede MT", regional="A.SUL", status="em_execucao", observacoes="Ligar para dona Maria"))
    db.add(ParametroGlobal(chave="notif", valor={"destinos": ["chefe@empresa.com"], "limite": 5}, descricao="x"))
    e1 = Empreiteira(nome_razao_social="Alfa Real Construcoes", cnpj="11.444.777/0001-61", codigo_contrato="4600004258")
    e2 = Empreiteira(nome_razao_social="Beta Real SA")
    db.add_all([e1, e2]); db.flush()
    for resp in ("Joao Pedreiro", "Joao Pedreiro", "Outra Pessoa"):
        db.add(RelatorioSupervisao(
            data_relatorio=date(2026, 10, 5), empreiteira_id=e1.id, responsavel=resp, contato="(11) 98888-7777",
            codigo_placa="XYZ9K88", supervisor_beq="Sup Real", endereco="Rua Verdadeira 5", municipio="Santo Andre",
            servicos_executados="Falei com o Sr. Jose", pendencias="Ligar para 11 97777-0000",
            composicao_equipe=[{"nome": "Fulano Real", "funcao": "Eletricista"}, {"nome": "Beltrano", "funcao": "Ajudante"}],
            fotos=[{"url": "https://real.com/foto.jpg", "legenda": "x"}], projeto_atividade="DMP/A.SUL.25.00419",
        ))
    db.commit()
    engine = db.get_bind()
    db.close()
    return engine


def test_anonimizacao_remove_pii_preserva_estrutura_e_codigos(db_session):
    engine = _popular(db_session)
    resumo = an.anonimizar(engine)
    assert resumo["usuarios"] == 2 and resumo["refresh_tokens"] == 1 and resumo["relatorios_supervisao"] == 3

    db = db_session()
    try:
        us = db.query(Usuario).order_by(Usuario.id).all()
        assert [u.usuario for u in us] == ["anon-user-1", "anon-user-2"]
        assert us[0].email == "user1@homolog.invalid" and us[1].email is None
        assert all(u.nome.startswith("Usuario ") and u.mfa_secret is None and not u.mfa_habilitado and u.convite_token_hash is None
                   and u.deve_trocar_senha and not u.notificacoes_email for u in us)
        assert not verificar_senha("SenhaReal#1", us[0].senha_hash) and not verificar_senha("outra", us[1].senha_hash)
        assert us[0].perfil_id == "supervisor"  # relacao preservada
        assert db.query(RefreshToken).count() == 0

        log = db.query(AuditLog).one()
        assert log.ip is None and log.user_agent is None and log.antes is None and log.depois is None
        assert log.acao == "usuario_criado"  # o que aconteceu continua visivel

        c = db.query(Cliente).one()
        assert c.nome == f"Cliente {c.id}" and c.email.endswith("@homolog.invalid") and c.telefone == "(00) 00000-0000"
        assert c.documento != "33.050.071/0001-58" and "Real" not in c.endereco
        f = db.query(Fornecedor).one()
        assert f.nome == f"Fornecedor {f.id}" and f.email.endswith("@homolog.invalid")
        assert db.query(Veiculo).one().placa == "TST0001"

        o = db.query(Obra).one()
        assert o.wl == "DMP/A.SUL.25.00419" and o.observacoes == an.MARCADOR  # codigo preservado, texto livre removido
        assert db.get(ParametroGlobal, "notif").valor == {"destinos": [an.MARCADOR], "limite": 5}

        es = {e.id: e for e in db.query(Empreiteira).all()}
        assert es[1].nome_razao_social == "Empreiteira 1" and es[1].codigo_contrato == "CT 1"
        assert es[1].cnpj != "11.444.777/0001-61" and cnpj_valido("".join(ch for ch in es[1].cnpj if ch.isdigit()))
        assert es[2].cnpj is None  # nulo continua nulo

        rs = db.query(RelatorioSupervisao).order_by(RelatorioSupervisao.id).all()
        assert all(r.empreiteira_id == 1 for r in rs)  # vinculo preservado
        assert rs[0].responsavel == rs[1].responsavel != rs[2].responsavel  # pseudonimo estavel
        assert "Joao" not in rs[0].responsavel and "Pedreiro" not in rs[0].responsavel
        r = rs[0]
        assert r.contato == f"Contato {r.id}" and r.codigo_placa == f"TST{r.id:04d}" and r.endereco.startswith("Endereco ficticio")
        assert r.composicao_equipe == [{"nome": "Integrante 1", "funcao": "Eletricista"}, {"nome": "Integrante 2", "funcao": "Ajudante"}]
        assert r.fotos is None and r.servicos_executados == an.MARCADOR and r.pendencias == an.MARCADOR
        assert r.projeto_atividade == "DMP/A.SUL.25.00419" and r.municipio == "Santo Andre" and r.data_relatorio == date(2026, 10, 5)
        # fotos viraram SQL NULL de verdade (nao o literal JSON 'null')
        assert db.execute(text("select count(*) from relatorios_supervisao where fotos is null")).scalar() == 3
    finally:
        db.close()


def test_anonimizacao_dry_run_nao_grava_e_e_idempotente(db_session):
    engine = _popular(db_session)
    an.anonimizar(engine, dry_run=True)
    db = db_session()
    assert db.query(Usuario).first().usuario == "maria.silva" and db.query(RefreshToken).count() == 1
    db.close()
    an.anonimizar(engine)
    an.anonimizar(engine)  # segunda vez nao quebra (unicidade de login/e-mail/cnpj/placa respeitada)
    db = db_session()
    assert db.query(Usuario).first().usuario == "anon-user-1"
    db.close()


def test_pseudonimo_depende_do_sal_da_execucao():
    a, b = an.Ctx("h", salt=b"1" * 16), an.Ctx("h", salt=b"2" * 16)
    assert a.pseudo("Joao") == a.pseudo(" joao ") and a.pseudo("Joao") != b.pseudo("Joao")


def test_criar_usuarios_teste_idempotente_com_senha_aleatoria(db_session):
    engine = _popular(db_session)
    primeiros = an.criar_usuarios_teste(engine)
    assert [(l, p) for l, _s, p in primeiros] == [("homolog.supervisor", "supervisor")]
    senha = primeiros[0][1]
    assert len(senha) >= 12 and senha != "supervisor@teste"
    assert an.criar_usuarios_teste(engine) == []  # idempotente
    db = db_session()
    u = db.query(Usuario).filter(Usuario.usuario == "homolog.supervisor").one()
    assert verificar_senha(senha, u.senha_hash) and u.deve_trocar_senha and not u.notificacoes_email
    db.close()
