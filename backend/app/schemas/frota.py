from datetime import date, datetime

from pydantic import Field

from app.schemas.base import OrmModel


class VeiculoBase(OrmModel):
    placa: str = Field(min_length=7, max_length=10)
    modelo: str = Field(min_length=1, max_length=80)
    tipo: str | None = None
    ano: int | None = Field(default=None, ge=1950, le=2100)
    regional: str | None = None
    equipe_id: int | None = None
    status: str = Field(default="Ativo", pattern="^(Ativo|Manutencao|Inativo)$")
    km_atual: int = Field(default=0, ge=0)
    licenciamento_vence_em: date | None = None
    seguro_vence_em: date | None = None


class VeiculoCreate(VeiculoBase):
    pass


class VeiculoUpdate(OrmModel):
    modelo: str | None = None
    tipo: str | None = None
    ano: int | None = Field(default=None, ge=1950, le=2100)
    regional: str | None = None
    equipe_id: int | None = None
    status: str | None = Field(default=None, pattern="^(Ativo|Manutencao|Inativo)$")
    km_atual: int | None = Field(default=None, ge=0)
    licenciamento_vence_em: date | None = None
    seguro_vence_em: date | None = None


class VeiculoOut(VeiculoBase):
    id: int
    criado_em: datetime


class ManutencaoBase(OrmModel):
    tipo: str = Field(default="Preventiva", pattern="^(Preventiva|Corretiva)$")
    descricao: str = Field(min_length=1, max_length=255)
    data_prevista: date | None = None
    data_realizada: date | None = None
    km: int | None = Field(default=None, ge=0)
    custo: float = Field(default=0, ge=0)
    status: str = Field(default="Agendada", pattern="^(Agendada|Concluida|Cancelada)$")
    observacoes: str | None = None


class ManutencaoCreate(ManutencaoBase):
    pass


class ManutencaoUpdate(OrmModel):
    tipo: str | None = Field(default=None, pattern="^(Preventiva|Corretiva)$")
    descricao: str | None = None
    data_prevista: date | None = None
    data_realizada: date | None = None
    km: int | None = Field(default=None, ge=0)
    custo: float | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(Agendada|Concluida|Cancelada)$")
    observacoes: str | None = None


class ManutencaoOut(ManutencaoBase):
    id: int
    veiculo_id: int
    criado_em: datetime
