"""Deteccao centralizada de pendencias/alertas de todas as areas.

Uma unica fonte de verdade usada pelo painel unificado (GET /painel/gerencia)
e pelo gerador de notificacoes -- assim o que a gerencia ve no painel e o que
chega por aviso/e-mail nunca diverge.

Cada Pendencia carrega a permissao de leitura necessaria para enxerga-la
(`permissao`), usada tanto para filtrar o painel por perfil quanto para
escolher os destinatarios das notificacoes."""
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.automacao import Automacao, ExecucaoAutomacao
from app.models.estoque import EstoqueItem, Material
from app.models.financeiro import Fatura, Glosa, Medicao
from app.models.frota import ManutencaoVeiculo, Veiculo
from app.models.obra import Obra, Programacao
from app.models.relatorio import RelatorioGerado
from app.services import faturamento_service

# Limiares (dias). Ponto de partida razoavel -- ajuste aqui se a regra real for outra.
OBRA_PRAZO_PROXIMO_DIAS = 7
FATURA_VENCIMENTO_PROXIMO_DIAS = 7
MANUTENCAO_PROXIMA_DIAS = 15
DOCUMENTO_VEICULO_PROXIMO_DIAS = 30
AUTOMACAO_FALHA_JANELA_HORAS = 24
EXPORTACAO_FROTA_DIAS_INICIAIS = 5  # lembra nos primeiros dias do mes
# Programacao antiga (ex.: historico importado de planilha) nao vira alerta: so olha os ultimos N dias.
PROGRAMACAO_SEM_FECHAMENTO_JANELA_DIAS = 30

STATUS_OBRA_TERMINAIS = {"concluida", "cancelada"}
NIVEL_ORDEM = {"critico": 0, "atencao": 1, "info": 2}


@dataclass
class Pendencia:
    tipo: str
    modulo: str  # faturamento | obras | frota | programacao | automacao | estoque
    nivel: str  # info | atencao | critico
    titulo: str
    mensagem: str
    permissao: str  # permissao de leitura exigida para ver/receber
    chave_dedup: str
    entidade: str | None = None
    entidade_id: str | None = None


def _p(**kw) -> Pendencia:
    return Pendencia(**kw)


# ---------------------------------------------------------------------------
# Detectores por modulo
# ---------------------------------------------------------------------------
def pendencias_obras(db: Session, hoje: date) -> list[Pendencia]:
    saida: list[Pendencia] = []
    for obra in db.query(Obra).filter(Obra.status.notin_(STATUS_OBRA_TERMINAIS), Obra.arquivada.is_(False)).all():
        if not obra.data_fim:
            continue
        dias = (obra.data_fim - hoje).days
        if dias < 0:
            saida.append(_p(
                tipo="obra_atrasada", modulo="obras", nivel="critico", permissao="obras:read",
                titulo=f"Obra {obra.wl} atrasada",
                mensagem=f"Prazo final {obra.data_fim.isoformat()} vencido ha {-dias} dia(s); status: {obra.status}.",
                chave_dedup=f"obra_atrasada:{obra.id}", entidade="obras", entidade_id=str(obra.id),
            ))
        elif dias <= OBRA_PRAZO_PROXIMO_DIAS:
            saida.append(_p(
                tipo="obra_prazo_proximo", modulo="obras", nivel="atencao", permissao="obras:read",
                titulo=f"Prazo da obra {obra.wl} se aproximando",
                mensagem=f"Faltam {dias} dia(s) para o prazo final ({obra.data_fim.isoformat()}).",
                chave_dedup=f"obra_prazo_proximo:{obra.id}", entidade="obras", entidade_id=str(obra.id),
            ))
    return saida


def pendencias_faturamento(db: Session, hoje: date) -> list[Pendencia]:
    saida: list[Pendencia] = []
    for f in db.query(Fatura).filter(Fatura.status != "Paga").all():
        dias = (f.vencimento - hoje).days
        if dias < 0:
            saida.append(_p(
                tipo="fatura_vencida", modulo="faturamento", nivel="critico", permissao="financeiro:read",
                titulo=f"Fatura #{f.id} vencida",
                mensagem=f"Vencida ha {-dias} dia(s) (vencimento {f.vencimento.isoformat()}), valor R$ {float(f.valor):.2f}.",
                chave_dedup=f"fatura_vencida:{f.id}", entidade="faturas", entidade_id=str(f.id),
            ))
        elif dias <= FATURA_VENCIMENTO_PROXIMO_DIAS:
            saida.append(_p(
                tipo="fatura_vencendo", modulo="faturamento", nivel="atencao", permissao="financeiro:read",
                titulo=f"Fatura #{f.id} vence em {dias} dia(s)",
                mensagem=f"Vencimento {f.vencimento.isoformat()}, valor R$ {float(f.valor):.2f}.",
                chave_dedup=f"fatura_vencendo:{f.id}", entidade="faturas", entidade_id=str(f.id),
            ))

    faturadas = {x[0] for x in db.query(Fatura.medicao_id).filter(Fatura.medicao_id.isnot(None)).all()}
    for m in db.query(Medicao).filter(Medicao.status == "Aprovada").all():
        if m.id not in faturadas:
            saida.append(_p(
                tipo="medicao_sem_fatura", modulo="faturamento", nivel="info", permissao="financeiro:read",
                titulo=f"Medicao #{m.id} aprovada sem fatura",
                mensagem=f"Medicao #{m.id} da obra #{m.obra_id} esta aprovada e ainda nao foi faturada.",
                chave_dedup=f"medicao_sem_fatura:{m.id}", entidade="medicoes", entidade_id=str(m.id),
            ))

    for g in db.query(Glosa).filter(Glosa.resolvida.is_(False)).all():
        saida.append(_p(
            tipo="glosa_pendente", modulo="faturamento", nivel="atencao", permissao="financeiro:read",
            titulo=f"Glosa pendente na medicao #{g.medicao_id}",
            mensagem=f"Glosa de R$ {float(g.valor):.2f} aguardando resolucao: {g.motivo[:120]}",
            chave_dedup=f"glosa_pendente:{g.id}", entidade="glosas", entidade_id=str(g.id),
        ))

    # Meta mensal de NECs em risco a partir do dia de alerta configurado (ex.: dia 25).
    config = faturamento_service.obter_configuracao(db)
    if config.meta_mensal_nec > 0 and hoje.day >= config.dia_alerta:
        resumo = faturamento_service.calcular_resumo(db)
        if resumo.percentual_meta < 100:
            saida.append(_p(
                tipo="meta_mensal_em_risco", modulo="faturamento", nivel="atencao", permissao="financeiro:read",
                titulo="Meta mensal de NECs abaixo do esperado",
                mensagem=(
                    f"Realizado {resumo.nec_realizado_mes} de {resumo.meta_mensal_nec} NECs "
                    f"({resumo.percentual_meta:.1f}%) no dia {hoje.day}."
                ),
                chave_dedup=f"meta_mensal_em_risco:{hoje:%Y-%m}", entidade="faturamento", entidade_id=f"{hoje:%Y-%m}",
            ))
    return saida


def pendencias_frota(db: Session, hoje: date) -> list[Pendencia]:
    saida: list[Pendencia] = []
    ativos = {v.id: v for v in db.query(Veiculo).filter(Veiculo.status != "Inativo").all()}

    for m in db.query(ManutencaoVeiculo).filter(ManutencaoVeiculo.status == "Agendada").all():
        v = ativos.get(m.veiculo_id)
        if not v or not m.data_prevista:
            continue
        dias = (m.data_prevista - hoje).days
        if dias < 0:
            saida.append(_p(
                tipo="manutencao_vencida", modulo="frota", nivel="critico", permissao="frota:read",
                titulo=f"Manutencao atrasada - {v.placa}",
                mensagem=f"{m.tipo}: {m.descricao}. Prevista para {m.data_prevista.isoformat()} (ha {-dias} dia(s)).",
                chave_dedup=f"manutencao_vencida:{m.id}", entidade="manutencoes_veiculo", entidade_id=str(m.id),
            ))
        elif dias <= MANUTENCAO_PROXIMA_DIAS:
            saida.append(_p(
                tipo="manutencao_proxima", modulo="frota", nivel="atencao", permissao="frota:read",
                titulo=f"Manutencao em {dias} dia(s) - {v.placa}",
                mensagem=f"{m.tipo}: {m.descricao}. Prevista para {m.data_prevista.isoformat()}.",
                chave_dedup=f"manutencao_proxima:{m.id}", entidade="manutencoes_veiculo", entidade_id=str(m.id),
            ))

    for v in ativos.values():
        for rotulo, campo, chave in (
            ("Licenciamento", v.licenciamento_vence_em, "licenciamento"),
            ("Seguro", v.seguro_vence_em, "seguro"),
        ):
            if not campo:
                continue
            dias = (campo - hoje).days
            if dias < 0:
                saida.append(_p(
                    tipo=f"{chave}_vencido", modulo="frota", nivel="critico", permissao="frota:read",
                    titulo=f"{rotulo} vencido - {v.placa}",
                    mensagem=f"{rotulo} venceu em {campo.isoformat()} (ha {-dias} dia(s)).",
                    chave_dedup=f"{chave}_vencido:{v.id}:{campo.isoformat()}", entidade="veiculos", entidade_id=str(v.id),
                ))
            elif dias <= DOCUMENTO_VEICULO_PROXIMO_DIAS:
                saida.append(_p(
                    tipo=f"{chave}_vencendo", modulo="frota", nivel="atencao", permissao="frota:read",
                    titulo=f"{rotulo} vence em {dias} dia(s) - {v.placa}",
                    mensagem=f"{rotulo} vence em {campo.isoformat()}.",
                    chave_dedup=f"{chave}_vencendo:{v.id}:{campo.isoformat()}", entidade="veiculos", entidade_id=str(v.id),
                ))

    # Lembrete da exportacao mensal da frota: nos primeiros dias do mes, se ninguem exportou.
    if hoje.day <= EXPORTACAO_FROTA_DIAS_INICIAIS and db.query(Veiculo).count() > 0:
        inicio_mes = date(hoje.year, hoje.month, 1)
        exportou = (
            db.query(func.count(RelatorioGerado.id))
            .filter(RelatorioGerado.tipo == "frota", RelatorioGerado.criado_em >= inicio_mes)
            .scalar()
        )
        if not exportou:
            saida.append(_p(
                tipo="frota_exportacao_mensal", modulo="frota", nivel="atencao", permissao="frota:read",
                titulo="Exportacao mensal da frota pendente",
                mensagem=f"O relatorio de frota de {hoje:%m/%Y} ainda nao foi exportado.",
                chave_dedup=f"frota_exportacao_mensal:{hoje:%Y-%m}", entidade="relatorios", entidade_id="frota",
            ))
    return saida


def pendencias_programacao(db: Session, hoje: date) -> list[Pendencia]:
    saida: list[Pendencia] = []
    atrasadas = (
        db.query(Programacao)
        .filter(
            Programacao.data < hoje,
            Programacao.data >= hoje - timedelta(days=PROGRAMACAO_SEM_FECHAMENTO_JANELA_DIAS),
            Programacao.status.in_(("Programada", "Em execucao")),
        )
        .all()
    )
    for p in atrasadas:
        saida.append(_p(
            tipo="programacao_pendente", modulo="programacao", nivel="atencao", permissao="programacao:read",
            titulo=f"Programacao de {p.data.isoformat()} sem fechamento",
            mensagem=f"Programacao #{p.id} (obra #{p.obra_id}) continua '{p.status}' apos a data prevista.",
            chave_dedup=f"programacao_pendente:{p.id}", entidade="programacoes", entidade_id=str(p.id),
        ))

    com_futuro = {
        x[0]
        for x in db.query(Programacao.obra_id)
        .filter(Programacao.data >= hoje, Programacao.status != "Cancelada")
        .all()
    }
    for obra in db.query(Obra).filter(Obra.status == "em_execucao", Obra.arquivada.is_(False)).all():
        if obra.id not in com_futuro:
            saida.append(_p(
                tipo="obra_sem_programacao", modulo="programacao", nivel="atencao", permissao="programacao:read",
                titulo=f"Obra {obra.wl} sem programacao futura",
                mensagem="Obra em execucao sem nenhuma programacao a partir de hoje.",
                chave_dedup=f"obra_sem_programacao:{obra.id}:{hoje:%Y-%m}", entidade="obras", entidade_id=str(obra.id),
            ))
    return saida


def pendencias_automacao(db: Session, agora=None) -> list[Pendencia]:
    from datetime import datetime, timezone

    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(hours=AUTOMACAO_FALHA_JANELA_HORAS)
    saida: list[Pendencia] = []
    for a in db.query(Automacao).filter(Automacao.ativo.is_(True)).all():
        ultima = (
            db.query(ExecucaoAutomacao)
            .filter(ExecucaoAutomacao.automacao_id == a.id)
            .order_by(ExecucaoAutomacao.iniciado_em.desc(), ExecucaoAutomacao.id.desc())
            .first()
        )
        if not ultima or ultima.status != "falha":
            continue
        inicio = ultima.iniciado_em
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=timezone.utc)
        if inicio < limite:
            continue
        saida.append(_p(
            tipo="automacao_falhou", modulo="automacao", nivel="critico", permissao="automacoes:read",
            titulo=f"Automacao '{a.nome}' falhou",
            mensagem=(ultima.mensagem or "Sem detalhe do erro.")[:300],
            chave_dedup=f"automacao_falhou:{a.id}:{ultima.id}", entidade="automacoes", entidade_id=str(a.id),
        ))
    return saida


def pendencias_estoque(db: Session) -> list[Pendencia]:
    saida: list[Pendencia] = []
    saldos = dict(
        db.query(EstoqueItem.material_id, func.coalesce(func.sum(EstoqueItem.quantidade), 0))
        .group_by(EstoqueItem.material_id)
        .all()
    )
    for m in db.query(Material).filter(Material.estoque_minimo > 0).all():
        saldo = float(saldos.get(m.id, 0) or 0)
        if saldo < float(m.estoque_minimo):
            saida.append(_p(
                tipo="estoque_abaixo_minimo", modulo="estoque", nivel="atencao", permissao="estoque:read",
                titulo=f"Estoque baixo: {m.nome}",
                mensagem=f"Saldo {saldo:g} {m.unidade} abaixo do minimo ({float(m.estoque_minimo):g}).",
                chave_dedup=f"estoque_abaixo_minimo:{m.id}:{date.today():%Y-%m}", entidade="materiais", entidade_id=str(m.id),
            ))
    return saida


# ---------------------------------------------------------------------------
def coletar_pendencias(db: Session, hoje: date | None = None) -> list[Pendencia]:
    hoje = hoje or date.today()
    todas = (
        pendencias_faturamento(db, hoje)
        + pendencias_obras(db, hoje)
        + pendencias_frota(db, hoje)
        + pendencias_programacao(db, hoje)
        + pendencias_automacao(db)
        + pendencias_estoque(db)
    )
    todas.sort(key=lambda p: (NIVEL_ORDEM.get(p.nivel, 9), p.modulo, p.titulo))
    return todas
