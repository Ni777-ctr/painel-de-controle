from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import OrmModel


class AutomacaoCreate(OrmModel):
    nome: str
    gatilho: str
    acao: dict[str, Any] = {}
    ativo: bool = True


class AutomacaoUpdate(OrmModel):
    nome: str | None = None
    gatilho: str | None = None
    acao: dict[str, Any] | None = None
    ativo: bool | None = None


class AutomacaoOut(OrmModel):
    id: int
    nome: str
    gatilho: str
    acao: dict[str, Any]
    ativo: bool


class PainelAutomacao(OrmModel):
    dispositivos_automacao: int
    subestacoes_digitais: int
    eventos_self_healing: int
    percentual_restabelecimento_automatico: float
    pontos_criticos_vegetacao_abertos: int


class IndicadoresSelfHealing(OrmModel):
    total_eventos: int
    resolvidos_automaticamente: int
    percentual_resolucao_automatica: float
    tempo_medio_restauracao_segundos: float | None = None


class LeituraSubestacaoOut(OrmModel):
    id: int
    subestacao_id: int
    registrado_em: datetime
    temperatura_c: float | None = None
    carga_percentual: float | None = None
    vibracao_mm_s: float | None = None
    alerta_gerado: bool


class StatusSubestacao(OrmModel):
    subestacao: str
    operacao_remota_ativa: bool
    ultima_leitura: LeituraSubestacaoOut | None = None
    alertas_ativos: list[str] = []


class PontoVegetacaoOut(OrmModel):
    id: int
    risco: str
    resolvido: bool


class DashboardObras(OrmModel):
    total: int
    concluidas: int
    pendentes: int
    em_execucao: int
    aguardando_inventario: int


class DashboardMateriais(OrmModel):
    total_itens: int
    saldo_total: float


class DashboardProdutividadeEquipe(OrmModel):
    equipe: str
    total: int
    concluidas: int


class DashboardFaturamento(OrmModel):
    pendencias_abertas: int


class DashboardOut(OrmModel):
    obras: DashboardObras
    materiais: DashboardMateriais
    produtividade_por_equipe: list[DashboardProdutividadeEquipe]
    faturamento: DashboardFaturamento


class ExecucaoAutomacaoCreate(OrmModel):
    status: str = Field(pattern="^(sucesso|falha)$")
    mensagem: str | None = Field(default=None, max_length=500)
    duracao_ms: int | None = Field(default=None, ge=0)


class ExecucaoAutomacaoOut(OrmModel):
    id: int
    automacao_id: int
    status: str
    mensagem: str | None = None
    duracao_ms: int | None = None
    iniciado_em: datetime
