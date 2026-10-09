from datetime import date, datetime

from app.schemas.base import OrmModel


class TipoRelatorioOut(OrmModel):
    chave: str
    nome: str
    descricao: str
    data_referencia: str
    formatos: list[str]


class RelatorioGeradoOut(OrmModel):
    id: int
    usuario_id: int
    usuario_nome: str | None = None
    tipo: str
    formato: str
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    obra_id: int | None = None
    responsavel_usuario_id: int | None = None
    filtros: dict | None = None
    nome_arquivo: str
    linhas: int
    tamanho_bytes: int
    criado_em: datetime


class HistoricoRelatorios(OrmModel):
    total: int
    itens: list[RelatorioGeradoOut]
