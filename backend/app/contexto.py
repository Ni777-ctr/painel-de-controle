"""Contexto da requisicao corrente (IP, user-agent, request id), acessivel de
qualquer camada sem passar `request` por parametro. Alimentado pelo middleware
em app/main.py; a auditoria le daqui para gravar IP/UA automaticamente."""
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextoRequisicao:
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


_contexto: ContextVar[ContextoRequisicao] = ContextVar("contexto_requisicao", default=ContextoRequisicao())


def definir_contexto(ctx: ContextoRequisicao):
    return _contexto.set(ctx)


def restaurar_contexto(token) -> None:
    _contexto.reset(token)


def obter_contexto() -> ContextoRequisicao:
    return _contexto.get()
