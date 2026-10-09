from app.schemas.base import OrmModel


class MaterialCreate(OrmModel):
    codigo: str | None = None
    nome: str
    unidade: str = "UN"
    estoque_minimo: float = 0


class MaterialUpdate(OrmModel):
    codigo: str | None = None
    nome: str | None = None
    unidade: str | None = None
    estoque_minimo: float | None = None


class MaterialOut(OrmModel):
    id: int
    codigo: str | None = None
    nome: str
    unidade: str
    estoque_minimo: float
    custo_medio: float


class AlmoxarifadoCreate(OrmModel):
    nome: str
    regional: str | None = None


class AlmoxarifadoOut(OrmModel):
    id: int
    nome: str
    regional: str | None = None


class EstoqueItemUpsert(OrmModel):
    almoxarifado_id: int
    material_id: int
    quantidade: float


class EstoqueItemOut(OrmModel):
    id: int
    almoxarifado_id: int
    material_id: int
    quantidade: float


class MovimentacaoEstoqueCreate(OrmModel):
    almoxarifado_id: int
    material_id: int
    obra_id: int | None = None
    tipo: str  # entrada | saida
    quantidade: float
    valor_unitario: float | None = None  # custo unitario da entrada (recalcula o custo medio do material)
    observacao: str | None = None


class MovimentacaoEstoqueOut(OrmModel):
    id: int
    almoxarifado_id: int
    material_id: int
    obra_id: int | None = None
    usuario_id: int | None = None
    tipo: str
    quantidade: float
    valor_unitario: float | None = None
    observacao: str | None = None
