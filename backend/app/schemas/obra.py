from datetime import date, datetime

from app.schemas.base import OrmModel


class ObraCreate(OrmModel):
    wl: str
    descricao: str | None = None
    regional: str | None = None
    cliente_id: int | None = None
    equipe_id: int | None = None
    status: str = "proposta"
    valor_contrato: float = 0
    custo_previsto: float = 0
    custo_realizado: float = 0
    avanco_previsto: float = 0
    avanco_realizado: float = 0
    necs_planejados: float = 0
    necs_executados: float = 0
    dias_contratada: int | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    observacoes: str | None = None


class ObraUpdate(OrmModel):
    descricao: str | None = None
    regional: str | None = None
    cliente_id: int | None = None
    equipe_id: int | None = None
    status: str | None = None
    valor_contrato: float | None = None
    custo_previsto: float | None = None
    custo_realizado: float | None = None
    avanco_previsto: float | None = None
    avanco_realizado: float | None = None
    necs_planejados: float | None = None
    necs_executados: float | None = None
    dias_contratada: int | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    observacoes: str | None = None


class ObraOut(OrmModel):
    id: int
    wl: str
    descricao: str | None = None
    regional: str | None = None
    cliente_id: int | None = None
    equipe_id: int | None = None
    equipe: str | None = None  # nome da equipe, preenchido no router
    status: str
    valor_contrato: float
    custo_previsto: float
    custo_realizado: float
    avanco_previsto: float
    avanco_realizado: float
    necs_planejados: float
    necs_executados: float
    necs_faturados: float = 0
    dias_contratada: int | None = None
    data_inicio: date | None = None
    data_fim: date | None = None
    observacoes: str | None = None


class ProgramacaoCreate(OrmModel):
    obra_id: int
    equipe_id: int
    data: date
    turno: str = "Diurno"
    status: str = "Programada"
    observacoes: str | None = None


class ProgramacaoUpdate(OrmModel):
    equipe_id: int | None = None
    data: date | None = None
    turno: str | None = None
    status: str | None = None
    observacoes: str | None = None


class ProgramacaoOut(OrmModel):
    id: int
    obra_id: int
    equipe_id: int
    data: date
    turno: str
    status: str
    observacoes: str | None = None


class HistoricoStatusOut(OrmModel):
    id: int
    status_anterior: str | None = None
    status_novo: str
    usuario_id: int | None = None
    observacao: str | None = None
    criado_em: datetime


class ResumoProgramacao(OrmModel):
    total: int
    por_status: dict[str, int]


class ResumoFinanceiro(OrmModel):
    medicoes_total: int
    faturas_total: int
    valor_faturado: float
    valor_pago: float
    valor_pendente: float


class ResumoCompras(OrmModel):
    requisicoes_total: int
    por_status: dict[str, int]


class MaterialConsumidoResumo(OrmModel):
    material_id: int
    material_nome: str
    quantidade_saida: float


class ObraResumoOut(OrmModel):
    obra: ObraOut
    cliente_nome: str | None = None
    programacao: ResumoProgramacao
    financeiro: ResumoFinanceiro
    compras: ResumoCompras
    materiais_consumidos: list[MaterialConsumidoResumo]
    historico_status: list[HistoricoStatusOut]
