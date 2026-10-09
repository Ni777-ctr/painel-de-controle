import re
from datetime import date, datetime, time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.base import OrmModel

StatusRelatorio = Literal["Concluído", "Parcial", "Cancelado", "Sem status"]
STATUS_RELATORIO = ("Concluído", "Parcial", "Cancelado", "Sem status")


def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def cnpj_valido(digitos: str) -> bool:
    """Valida os 14 digitos e os 2 digitos verificadores do CNPJ (rejeita sequencias repetidas)."""
    if len(digitos) != 14 or not digitos.isdigit() or digitos == digitos[0] * 14:
        return False

    def dv(base: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(base):]
        resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
        return "0" if resto < 2 else str(11 - resto)

    d1 = dv(digitos[:12])
    d2 = dv(digitos[:12] + d1)
    return digitos[12:] == d1 + d2


# ---------------------------------------------------------------------------
# Empreiteira
# ---------------------------------------------------------------------------
class EmpreiteiraBase(OrmModel):
    nome_razao_social: str = Field(min_length=1, max_length=160)
    cnpj: str | None = Field(default=None, max_length=18)
    codigo_contrato: str | None = Field(default=None, max_length=60)
    ativo: bool = True

    @field_validator("nome_razao_social")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nome_razao_social nao pode ser vazio.")
        return v

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str | None) -> str | None:
        """Opcional. Se informado, precisa ser um CNPJ valido (14 digitos + digitos verificadores);
        e' gravado formatado (00.000.000/0000-00)."""
        if v is None or not v.strip():
            return None
        d = _so_digitos(v)
        if len(d) != 14:
            raise ValueError("cnpj deve ter 14 digitos.")
        if not cnpj_valido(d):
            raise ValueError("cnpj invalido (digitos verificadores nao conferem).")
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


class EmpreiteiraCreate(EmpreiteiraBase):
    pass


class EmpreiteiraUpdate(OrmModel):
    nome_razao_social: str | None = Field(default=None, min_length=1, max_length=160)
    cnpj: str | None = Field(default=None, max_length=18)
    codigo_contrato: str | None = Field(default=None, max_length=60)
    ativo: bool | None = None

    _cnpj = field_validator("cnpj")(EmpreiteiraBase._cnpj.__func__)  # mesma regra do create


class EmpreiteiraOut(EmpreiteiraBase):
    id: int
    criado_em: datetime


# ---------------------------------------------------------------------------
# Relatorio de supervisao
# ---------------------------------------------------------------------------
class IntegranteEquipe(OrmModel):
    nome: str = Field(min_length=1, max_length=120)
    funcao: str | None = Field(default=None, max_length=80)


class FotoRelatorio(OrmModel):
    url: str = Field(min_length=1, max_length=2000)
    legenda: str | None = Field(default=None, max_length=300)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        # Aceita http(s) ou caminho relativo do proprio sistema; bloqueia esquemas perigosos
        # (javascript:, data:...) e URLs "protocol-relative" (//host) ou com barra invertida (/\\host).
        if (
            not v.startswith(("http://", "https://", "/"))
            or v.startswith(("//", "/\\"))
            or any(c in v for c in "\n\r\t\\")
        ):
            raise ValueError("url da foto deve comecar com http://, https:// ou / (caminho do proprio sistema).")
        return v


class RelatorioSupervisaoBase(OrmModel):
    data_relatorio: date
    projeto_atividade: str | None = Field(default=None, max_length=200)
    ordem: str | None = Field(default=None, max_length=60)
    status: StatusRelatorio = "Sem status"
    porcentagem_execucao: int | None = Field(default=None, ge=0, le=100)

    empreiteira_id: int | None = None
    empreiteira_nome_customizado: str | None = Field(default=None, max_length=160)

    contato: str | None = Field(default=None, max_length=120)
    lv_lm: str | None = Field(default=None, max_length=20)
    responsavel: str | None = Field(default=None, max_length=120)
    codigo_placa: str | None = Field(default=None, max_length=40)
    supervisor_beq: str | None = Field(default=None, max_length=120)

    endereco: str | None = Field(default=None, max_length=255)
    bairro: str | None = Field(default=None, max_length=120)
    municipio: str | None = Field(default=None, max_length=120)
    estado: str | None = Field(default=None, min_length=2, max_length=2)

    composicao_equipe: list[IntegranteEquipe] | None = None
    servicos_executados: str | None = None
    pendencias: str | None = None

    horario_saida_base: time | None = None
    horario_chegada_obra: time | None = None
    horario_saida_obra: time | None = None
    horario_chegada_base: time | None = None

    fotos: list[FotoRelatorio] | None = None

    @field_validator("estado")
    @classmethod
    def _uf(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class RelatorioSupervisaoCreate(RelatorioSupervisaoBase):
    pass


class RelatorioSupervisaoUpdate(RelatorioSupervisaoBase):
    """PUT: substitui o relatorio inteiro (campos omitidos voltam ao padrao/nulo)."""


class RelatorioSupervisaoOut(RelatorioSupervisaoBase):
    id: int
    empreiteira_nome: str | None = None  # nome exibivel: cadastrada ou customizada
    criado_por_id: int | None = None
    criado_em: datetime
    atualizado_em: datetime
