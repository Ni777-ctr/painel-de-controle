from typing import Any

from app.schemas.base import OrmModel


class AlertaPainel(OrmModel):
    tipo: str
    modulo: str
    nivel: str
    titulo: str
    mensagem: str
    entidade: str | None = None
    entidade_id: str | None = None


class PainelGerencia(OrmModel):
    gerado_em: str
    totais_por_nivel: dict[str, int]
    totais_por_modulo: dict[str, int]
    alertas: list[AlertaPainel]
    # Uma secao por modulo; ausente quando o perfil nao tem permissao de leitura nele.
    faturamento: dict[str, Any] | None = None
    obras: dict[str, Any] | None = None
    frota: dict[str, Any] | None = None
    programacao: dict[str, Any] | None = None
    automacoes: dict[str, Any] | None = None
    estoque: dict[str, Any] | None = None
