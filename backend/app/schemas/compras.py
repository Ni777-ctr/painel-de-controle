from app.schemas.base import OrmModel


class FornecedorCreate(OrmModel):
    nome: str
    documento: str | None = None
    contato: str | None = None
    telefone: str | None = None
    email: str | None = None


class FornecedorUpdate(OrmModel):
    nome: str | None = None
    documento: str | None = None
    contato: str | None = None
    telefone: str | None = None
    email: str | None = None


class FornecedorOut(OrmModel):
    id: int
    nome: str
    documento: str | None = None
    contato: str | None = None
    telefone: str | None = None
    email: str | None = None


class RequisicaoItemIn(OrmModel):
    material_id: int
    quantidade: float


class RequisicaoItemOut(OrmModel):
    id: int
    material_id: int
    quantidade: float


class RequisicaoCreate(OrmModel):
    obra_id: int | None = None
    almoxarifado_id: int | None = None
    observacoes: str | None = None
    itens: list[RequisicaoItemIn]


class RequisicaoUpdateStatus(OrmModel):
    status: str  # Pendente | Aprovada | Rejeitada | Convertida em pedido


class RequisicaoOut(OrmModel):
    id: int
    solicitante_usuario_id: int | None = None
    obra_id: int | None = None
    almoxarifado_id: int | None = None
    origem_automatica: bool
    status: str
    observacoes: str | None = None
    itens: list[RequisicaoItemOut] = []


class PedidoItemIn(OrmModel):
    material_id: int
    quantidade: float
    valor_unitario: float = 0


class PedidoItemOut(OrmModel):
    id: int
    material_id: int
    quantidade: float
    valor_unitario: float


class PedidoCreate(OrmModel):
    fornecedor_id: int
    requisicao_id: int | None = None
    almoxarifado_id: int | None = None  # obrigatorio antes de marcar o pedido como "Recebido"
    itens: list[PedidoItemIn]


class PedidoUpdateStatus(OrmModel):
    status: str  # Aberto | Enviado | Recebido | Cancelado


class PedidoOut(OrmModel):
    id: int
    fornecedor_id: int
    requisicao_id: int | None = None
    almoxarifado_id: int | None = None
    status: str
    valor_total: float
    itens: list[PedidoItemOut] = []
