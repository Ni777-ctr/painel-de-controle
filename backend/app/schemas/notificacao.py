from datetime import datetime

from app.schemas.base import OrmModel


class NotificacaoOut(OrmModel):
    id: int
    tipo: str
    modulo: str
    nivel: str
    titulo: str
    mensagem: str
    entidade: str | None = None
    entidade_id: str | None = None
    lida: bool
    lida_em: datetime | None = None
    email_status: str | None = None
    criado_em: datetime


class ContagemNaoLidas(OrmModel):
    nao_lidas: int
    criticas: int


class PreferenciasNotificacao(OrmModel):
    notificacoes_email: bool


class ProcessamentoResultado(OrmModel):
    novas: int
    enviados: int
    falhas: int
    ignorados: int
