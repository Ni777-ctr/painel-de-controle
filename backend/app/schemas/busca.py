from app.schemas.base import OrmModel


class ResultadoBusca(OrmModel):
    tipo: str  # obra | cliente | veiculo | fatura | medicao | material | fornecedor | equipe
    id: int
    titulo: str
    subtitulo: str | None = None
    rota: str  # rota sugerida no frontend, ex.: /obras/12


class RespostaBusca(OrmModel):
    termo: str
    total: int
    resultados: list[ResultadoBusca]
