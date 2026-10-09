from datetime import date, datetime

from app.schemas.base import OrmModel


class MedicaoCreate(OrmModel):
    obra_id: int
    contrato: float
    percentual: float = 0
    necs_medidos: float = 0
    responsavel_usuario_id: int | None = None
    status: str = "Rascunho"
    dias_parada: int = 0


class MedicaoUpdate(OrmModel):
    percentual: float | None = None
    necs_medidos: float | None = None
    status: str | None = None  # transicao validada no router (Rascunho -> Aprovada|Reprovada)
    dias_parada: int | None = None


class MedicaoOut(OrmModel):
    id: int
    obra_id: int
    contrato: float
    percentual: float
    necs_medidos: float
    responsavel_usuario_id: int | None = None
    status: str
    dias_parada: int
    criado_em: datetime


class GlosaCreate(OrmModel):
    valor: float
    motivo: str


class GlosaOut(OrmModel):
    id: int
    medicao_id: int
    valor: float
    motivo: str
    resolvida: bool
    criado_em: datetime


class FaturaCreate(OrmModel):
    obra_id: int
    medicao_id: int | None = None
    valor: float
    necs_faturados: float | None = None
    vencimento: date
    status: str = "Emitida"
    percentual_faturado: float | None = None
    percentual_pago: float | None = None


class FaturaUpdate(OrmModel):
    status: str | None = None
    percentual_faturado: float | None = None
    percentual_pago: float | None = None


class FaturaOut(OrmModel):
    id: int
    obra_id: int
    medicao_id: int | None = None
    valor: float
    necs_faturados: float | None = None
    vencimento: date
    status: str
    dias_atraso: int = 0  # calculado no router
    percentual_faturado: float | None = None
    percentual_pago: float | None = None


class PagamentoCreate(OrmModel):
    fatura_id: int
    valor: float
    data_pagamento: date
    metodo: str | None = None


class PagamentoOut(OrmModel):
    id: int
    fatura_id: int
    valor: float
    data_pagamento: date
    metodo: str | None = None


class ResumoCobranca(OrmModel):
    recuperacao_percentual: float
    tempo_medio_dias: float
    valor_pendente: float
    valor_pago: float
    faixas_atraso: dict  # {"ate_10": n, "11_a_30": n, "acima_30": n}


# ---------- Configuracao de faturamento ----------
class ConfiguracaoFaturamento(OrmModel):
    meta_mensal_nec: int = 20000
    mes_referencia: str | None = None  # formato "AAAA-MM"; None = mes corrente
    dia_alerta: int = 25  # dia do mes em que o alerta de meta e' considerado
    emails_alerta: list[str] = []


# ---------- Resumo gerencial / evolucao mensal ----------
class ItemEvolucaoMensal(OrmModel):
    mes: str  # "AAAA-MM"
    necs: float


class ResumoFaturamento(OrmModel):
    meta_mensal_nec: int
    nec_realizado_mes: float
    percentual_meta: float
    saldo_para_meta: int
    media_ultimos_6_meses: float
    evolucao_mensal: list[ItemEvolucaoMensal]
    medicoes_aprovadas: int
    faturas_emitidas: int
    faturas_pagas: int
    faturas_pendentes: int
    faturas_atrasadas: int
    valor_faturado_total: float
    valor_pago_total: float
    valor_pendente_total: float


# ---------- Carteira de obras/contratos ----------
class ItemCarteira(OrmModel):
    obra_id: int
    codigo_contrato: str  # Obra.wl
    cliente_nome: str | None = None
    descricao: str | None = None
    data_inicio: date | None = None
    data_vencimento: date | None = None
    situacao_contrato: str  # Obra.status
    valor_contrato: float
    nec_previsto: float
    nec_executado: float
    nec_faturado: float
    saldo_nec_estimado: float
    valor_medido: float
    valor_faturado: float
    saldo_valor_estimado: float
    glosas_total: float
    observacoes: str | None = None


# ---------- Alertas financeiros ----------
class AlertaFinanceiroOut(OrmModel):
    id: int
    tipo: str
    nivel: str
    obra_id: int | None = None
    fatura_id: int | None = None
    medicao_id: int | None = None
    mensagem: str
    resolvido: bool
    resolvido_em: datetime | None = None
    criado_em: datetime


class GerarAlertasResponse(OrmModel):
    total_ativos: int
    novos: int
    alertas: list[AlertaFinanceiroOut]
