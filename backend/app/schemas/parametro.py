from typing import Any

from app.schemas.base import OrmModel


class ParametroUpsert(OrmModel):
    valor: Any
    descricao: str | None = None


class ParametroOut(OrmModel):
    chave: str
    valor: Any
    descricao: str | None = None
