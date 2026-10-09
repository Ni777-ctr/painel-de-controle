"""Regras de negocio de faturamento/medicao: configuracao (via
ParametroGlobal, sem preco/meta fixo no codigo), resumo gerencial, evolucao
mensal, carteira de obras/contratos e geracao de alertas financeiros.

Nao envia e-mail real -- a geracao de alertas apenas persiste no banco e
grava uma entrada de auditoria simulando a notificacao (lista de e-mails
configurados + quantidade de alertas), como pedido para esta etapa."""
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.models.financeiro import AlertaFinanceiro, Fatura, Glosa, Medicao
from app.models.obra import Obra
from app.models.parametro import ParametroGlobal
from app.schemas.financeiro import ConfiguracaoFaturamento, ItemCarteira, ItemEvolucaoMensal, ResumoFaturamento

CHAVE_CONFIGURACAO = "faturamento_configuracao"

# Limiares dos alertas. Os dois primeiros (saldo baixo / vencimento de
# contrato) foram pedidos explicitamente com esses valores; o de "fatura
# proxima do vencimento" nao teve um numero de dias definido na spec --
# usei 7 dias como padrao razoavel (ajuste aqui se o valor real for outro).
LIMIAR_SALDO_CONTRATO_BAIXO_PCT = 15
LIMIAR_CONTRATO_VENCIMENTO_DIAS = 30
LIMIAR_FATURA_PROXIMA_VENCIMENTO_DIAS = 7

STATUS_OBRA_TERMINAIS = {"concluida", "cancelada"}


# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
def obter_configuracao(db: Session) -> ConfiguracaoFaturamento:
    parametro = db.get(ParametroGlobal, CHAVE_CONFIGURACAO)
    if parametro and isinstance(parametro.valor, dict):
        return ConfiguracaoFaturamento(**parametro.valor)
    return ConfiguracaoFaturamento()


def definir_configuracao(db: Session, dados: ConfiguracaoFaturamento) -> ConfiguracaoFaturamento:
    parametro = db.get(ParametroGlobal, CHAVE_CONFIGURACAO)
    valor = dados.model_dump()
    if parametro:
        parametro.valor = valor
        parametro.descricao = "Configuracao de faturamento (meta mensal, mes de referencia, alerta, e-mails)."
    else:
        db.add(ParametroGlobal(
            chave=CHAVE_CONFIGURACAO,
            valor=valor,
            descricao="Configuracao de faturamento (meta mensal, mes de referencia, alerta, e-mails).",
        ))
    return dados


# ---------------------------------------------------------------------------
# Resumo gerencial / evolucao mensal
# ---------------------------------------------------------------------------
def _mes_referencia(config: ConfiguracaoFaturamento) -> tuple[int, int]:
    if config.mes_referencia:
        ano_str, mes_str = config.mes_referencia.split("-")
        return int(ano_str), int(mes_str)
    hoje = date.today()
    return hoje.year, hoje.month


def _somar_necs_por_mes(db: Session, ano: int, mes: int) -> float:
    medicoes = db.query(Medicao).filter(Medicao.status == "Aprovada").all()
    total = 0.0
    for m in medicoes:
        criado = m.criado_em
        if criado and criado.year == ano and criado.month == mes:
            total += float(m.necs_medidos or 0)
    return total


def _mes_anterior(ano: int, mes: int) -> tuple[int, int]:
    if mes == 1:
        return ano - 1, 12
    return ano, mes - 1


def calcular_evolucao_mensal(db: Session, meses: int = 6) -> list[ItemEvolucaoMensal]:
    config = obter_configuracao(db)
    ano, mes = _mes_referencia(config)
    pontos: list[ItemEvolucaoMensal] = []
    for _ in range(meses):
        total = _somar_necs_por_mes(db, ano, mes)
        pontos.append(ItemEvolucaoMensal(mes=f"{ano:04d}-{mes:02d}", necs=total))
        ano, mes = _mes_anterior(ano, mes)
    pontos.reverse()
    return pontos


def calcular_resumo(db: Session) -> ResumoFaturamento:
    config = obter_configuracao(db)
    ano, mes = _mes_referencia(config)
    evolucao = calcular_evolucao_mensal(db, meses=6)
    nec_realizado_mes = evolucao[-1].necs if evolucao else _somar_necs_por_mes(db, ano, mes)
    media_6m = (sum(p.necs for p in evolucao) / len(evolucao)) if evolucao else 0.0

    meta = config.meta_mensal_nec
    percentual_meta = round((nec_realizado_mes / meta) * 100, 2) if meta > 0 else 0.0
    saldo_para_meta = meta - nec_realizado_mes

    medicoes_aprovadas = db.query(Medicao).filter(Medicao.status == "Aprovada").count()

    hoje = date.today()
    faturas = db.query(Fatura).all()
    faturas_emitidas = len(faturas)
    faturas_pagas = len([f for f in faturas if f.status == "Paga"])
    faturas_atrasadas = len([f for f in faturas if f.status != "Paga" and f.vencimento < hoje])
    faturas_pendentes = len([f for f in faturas if f.status != "Paga" and f.vencimento >= hoje])
    valor_faturado_total = sum(float(f.valor) for f in faturas)
    valor_pago_total = sum(float(f.valor) for f in faturas if f.status == "Paga")

    return ResumoFaturamento(
        meta_mensal_nec=meta,
        nec_realizado_mes=nec_realizado_mes,
        percentual_meta=percentual_meta,
        saldo_para_meta=saldo_para_meta,
        media_ultimos_6_meses=round(media_6m, 2),
        evolucao_mensal=evolucao,
        medicoes_aprovadas=medicoes_aprovadas,
        faturas_emitidas=faturas_emitidas,
        faturas_pagas=faturas_pagas,
        faturas_pendentes=faturas_pendentes,
        faturas_atrasadas=faturas_atrasadas,
        valor_faturado_total=valor_faturado_total,
        valor_pago_total=valor_pago_total,
        valor_pendente_total=valor_faturado_total - valor_pago_total,
    )


# ---------------------------------------------------------------------------
# Carteira de obras/contratos
# ---------------------------------------------------------------------------
def calcular_carteira(db: Session) -> list[ItemCarteira]:
    obras = db.query(Obra).all()
    itens: list[ItemCarteira] = []
    for obra in obras:
        valor_medido = sum(
            float(m.contrato) * float(m.percentual) / 100 for m in obra.medicoes if m.status == "Aprovada"
        )
        valor_faturado = sum(float(f.valor) for f in obra.faturas)
        glosas_total = sum(float(g.valor) for m in obra.medicoes for g in m.glosas)

        itens.append(ItemCarteira(
            obra_id=obra.id,
            codigo_contrato=obra.wl,
            cliente_nome=obra.cliente.nome if obra.cliente else None,
            descricao=obra.descricao,
            data_inicio=obra.data_inicio,
            data_vencimento=obra.data_fim,
            situacao_contrato=obra.status,
            valor_contrato=float(obra.valor_contrato),
            nec_previsto=float(obra.necs_planejados or 0),
            nec_executado=float(obra.necs_executados or 0),
            nec_faturado=float(obra.necs_faturados or 0),
            saldo_nec_estimado=float(obra.necs_planejados or 0) - float(obra.necs_executados or 0),
            valor_medido=valor_medido,
            valor_faturado=valor_faturado,
            saldo_valor_estimado=float(obra.valor_contrato) - valor_faturado,
            glosas_total=glosas_total,
            observacoes=obra.observacoes,
        ))
    return itens


# ---------------------------------------------------------------------------
# Alertas financeiros
# ---------------------------------------------------------------------------
def _ja_existe_alerta_ativo(db: Session, *, tipo: str, obra_id=None, fatura_id=None, medicao_id=None) -> bool:
    query = db.query(AlertaFinanceiro).filter(AlertaFinanceiro.tipo == tipo, AlertaFinanceiro.resolvido.is_(False))
    if obra_id is not None:
        query = query.filter(AlertaFinanceiro.obra_id == obra_id)
    if fatura_id is not None:
        query = query.filter(AlertaFinanceiro.fatura_id == fatura_id)
    if medicao_id is not None:
        query = query.filter(AlertaFinanceiro.medicao_id == medicao_id)
    return query.first() is not None


def _criar_alerta(db: Session, **kwargs) -> AlertaFinanceiro:
    alerta = AlertaFinanceiro(**kwargs)
    db.add(alerta)
    return alerta


def gerar_alertas(db: Session, usuario_id: int | None) -> tuple[int, list[AlertaFinanceiro]]:
    hoje = date.today()
    config = obter_configuracao(db)
    novos = 0

    # a) Saldo de contrato baixo (<= 15%)
    for obra in db.query(Obra).all():
        if obra.status in STATUS_OBRA_TERMINAIS or float(obra.valor_contrato) <= 0:
            continue
        faturado = sum(float(f.valor) for f in obra.faturas)
        saldo_pct = (float(obra.valor_contrato) - faturado) / float(obra.valor_contrato) * 100
        if saldo_pct <= LIMIAR_SALDO_CONTRATO_BAIXO_PCT:
            if not _ja_existe_alerta_ativo(db, tipo="saldo_baixo", obra_id=obra.id):
                _criar_alerta(
                    db, tipo="saldo_baixo", nivel="atencao", obra_id=obra.id,
                    mensagem=f"Obra {obra.wl}: saldo de contrato em {saldo_pct:.1f}% (limite {LIMIAR_SALDO_CONTRATO_BAIXO_PCT}%).",
                )
                novos += 1

    # b) Contrato proximo do vencimento (<= 30 dias)
    for obra in db.query(Obra).all():
        if obra.status in STATUS_OBRA_TERMINAIS or not obra.data_fim:
            continue
        dias_restantes = (obra.data_fim - hoje).days
        if 0 <= dias_restantes <= LIMIAR_CONTRATO_VENCIMENTO_DIAS:
            if not _ja_existe_alerta_ativo(db, tipo="vencimento_proximo", obra_id=obra.id):
                _criar_alerta(
                    db, tipo="vencimento_proximo", nivel="atencao", obra_id=obra.id,
                    mensagem=f"Obra {obra.wl}: contrato vence em {dias_restantes} dia(s) ({obra.data_fim.isoformat()}).",
                )
                novos += 1

    # c) Medicao aprovada aguardando faturamento (sem fatura vinculada)
    faturadas_ids = {f.medicao_id for f in db.query(Fatura).filter(Fatura.medicao_id.isnot(None)).all()}
    for medicao in db.query(Medicao).filter(Medicao.status == "Aprovada").all():
        if medicao.id in faturadas_ids:
            continue
        if not _ja_existe_alerta_ativo(db, tipo="medicao_aguardando_faturamento", medicao_id=medicao.id):
            _criar_alerta(
                db, tipo="medicao_aguardando_faturamento", nivel="info", obra_id=medicao.obra_id, medicao_id=medicao.id,
                mensagem=f"Medicao #{medicao.id} (obra #{medicao.obra_id}) aprovada e ainda sem fatura emitida.",
            )
            novos += 1

    # d) Fatura vencida / proxima do vencimento
    for fatura in db.query(Fatura).filter(Fatura.status != "Paga").all():
        dias = (fatura.vencimento - hoje).days
        if dias < 0:
            if not _ja_existe_alerta_ativo(db, tipo="fatura_vencida", fatura_id=fatura.id):
                _criar_alerta(
                    db, tipo="fatura_vencida", nivel="critico", obra_id=fatura.obra_id, fatura_id=fatura.id,
                    mensagem=f"Fatura #{fatura.id} (obra #{fatura.obra_id}) vencida ha {-dias} dia(s).",
                )
                novos += 1
        elif dias <= LIMIAR_FATURA_PROXIMA_VENCIMENTO_DIAS:
            if not _ja_existe_alerta_ativo(db, tipo="fatura_proxima_vencimento", fatura_id=fatura.id):
                _criar_alerta(
                    db, tipo="fatura_proxima_vencimento", nivel="atencao", obra_id=fatura.obra_id, fatura_id=fatura.id,
                    mensagem=f"Fatura #{fatura.id} (obra #{fatura.obra_id}) vence em {dias} dia(s).",
                )
                novos += 1

    # e) Glosa pendente
    for glosa in db.query(Glosa).filter(Glosa.resolvida.is_(False)).all():
        if not _ja_existe_alerta_ativo(db, tipo="glosa_pendente", medicao_id=glosa.medicao_id):
            _criar_alerta(
                db, tipo="glosa_pendente", nivel="atencao", obra_id=glosa.medicao.obra_id, medicao_id=glosa.medicao_id,
                mensagem=f"Glosa de R$ {float(glosa.valor):.2f} pendente na medicao #{glosa.medicao_id}.",
            )
            novos += 1

    ativos = db.query(AlertaFinanceiro).filter(AlertaFinanceiro.resolvido.is_(False)).order_by(
        AlertaFinanceiro.criado_em.desc()
    ).all()

    # Simulacao segura de notificacao (NAO envia e-mail real).
    registrar(
        db,
        usuario_id=usuario_id,
        acao="alertas_financeiros_notificacao_simulada",
        entidade="alertas_financeiros",
        depois={"emails_configurados": config.emails_alerta, "quantidade_alertas_ativos": len(ativos), "novos": novos},
    )

    return novos, ativos
