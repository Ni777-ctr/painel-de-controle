from datetime import datetime

from app.schemas.base import OrmModel


class AuditLogCreate(OrmModel):
    acao: str
    entidade: str
    entidade_id: str | None = None
    bot: str | None = None
    antes: dict | None = None
    depois: dict | None = None


class AuditLogOut(OrmModel):
    id: int
    usuario_id: int | None = None
    usuario_nome: str | None = None
    bot: str | None = None
    acao: str
    categoria: str = "alteracao"
    entidade: str
    entidade_id: str | None = None
    antes: dict | None = None
    depois: dict | None = None
    ip: str | None = None
    user_agent: str | None = None
    criado_em: datetime


class AuditLogPagina(OrmModel):
    total: int
    limite: int
    offset: int
    itens: list[AuditLogOut]


class ResumoAuditoria(OrmModel):
    desde: datetime
    por_categoria: dict[str, int]
    top_acoes: list[dict]
    falhas_acesso_por_ip: list[dict]
