from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import get_current_user, requer_permissao, tem_permissao
from app.models.compras import Fornecedor, PedidoCompra, PedidoCompraItem, RequisicaoCompra, RequisicaoCompraItem
from app.models.usuario import Usuario
from app.schemas.compras import (
    FornecedorCreate,
    FornecedorOut,
    FornecedorUpdate,
    PedidoCreate,
    PedidoOut,
    PedidoUpdateStatus,
    RequisicaoCreate,
    RequisicaoOut,
    RequisicaoUpdateStatus,
)
from app.services.estoque_service import aplicar_movimentacao

router = APIRouter(tags=["Compras"])

STATUS_REQUISICAO_VALIDOS = {"Pendente", "Aprovada", "Rejeitada", "Convertida em pedido"}
STATUS_PEDIDO_VALIDOS = {"Aberto", "Enviado", "Recebido", "Cancelado"}

# Maquina de estados do pedido de compra (mesmo padrao usado em Obra).
TRANSICOES_PEDIDO: dict[str, set[str]] = {
    "Aberto": {"Enviado", "Cancelado"},
    "Enviado": {"Recebido", "Cancelado"},
    "Recebido": set(),
    "Cancelado": set(),
}


# ---------- Fornecedores ----------
@router.get("/fornecedores", response_model=list[FornecedorOut])
def listar_fornecedores(db: Session = Depends(get_db), _=Depends(requer_permissao("compras:read"))):
    return db.query(Fornecedor).order_by(Fornecedor.nome).all()


@router.post("/fornecedores", response_model=FornecedorOut, status_code=status.HTTP_201_CREATED)
def criar_fornecedor(
    dados: FornecedorCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("compras:write"))
):
    fornecedor = Fornecedor(**dados.model_dump())
    db.add(fornecedor)
    db.commit()
    db.refresh(fornecedor)
    return fornecedor


@router.patch("/fornecedores/{fornecedor_id}", response_model=FornecedorOut)
def atualizar_fornecedor(
    fornecedor_id: int,
    dados: FornecedorUpdate,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("compras:write")),
):
    fornecedor = db.get(Fornecedor, fornecedor_id)
    if not fornecedor:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(fornecedor, campo, valor)
    db.commit()
    db.refresh(fornecedor)
    return fornecedor


# ---------- Requisicoes de compra ----------
@router.get("/requisicoes-compra", response_model=list[RequisicaoOut])
def listar_requisicoes(
    origem_automatica: bool | None = None,
    obra_id: int | None = None,
    almoxarifado_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("compras:read")),
):
    query = db.query(RequisicaoCompra)
    if origem_automatica is not None:
        query = query.filter(RequisicaoCompra.origem_automatica == origem_automatica)
    if obra_id:
        query = query.filter(RequisicaoCompra.obra_id == obra_id)
    if almoxarifado_id:
        query = query.filter(RequisicaoCompra.almoxarifado_id == almoxarifado_id)
    return query.order_by(RequisicaoCompra.criado_em.desc()).all()


@router.post("/requisicoes-compra", response_model=RequisicaoOut, status_code=status.HTTP_201_CREATED)
def criar_requisicao(
    dados: RequisicaoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(requer_permissao("compras:write")),
):
    requisicao = RequisicaoCompra(
        obra_id=dados.obra_id,
        almoxarifado_id=dados.almoxarifado_id,
        observacoes=dados.observacoes,
        solicitante_usuario_id=usuario.id,
    )
    requisicao.itens = [RequisicaoCompraItem(**item.model_dump()) for item in dados.itens]
    db.add(requisicao)
    db.commit()
    db.refresh(requisicao)
    return requisicao


@router.patch("/requisicoes-compra/{requisicao_id}", response_model=RequisicaoOut)
def atualizar_status_requisicao(
    requisicao_id: int,
    dados: RequisicaoUpdateStatus,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("compras:write")),
):
    requisicao = db.get(RequisicaoCompra, requisicao_id)
    if not requisicao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requisicao nao encontrada.")
    if dados.status not in STATUS_REQUISICAO_VALIDOS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status invalido.")
    requisicao.status = dados.status
    db.commit()
    db.refresh(requisicao)
    return requisicao


# ---------- Pedidos de compra ----------
@router.get("/pedidos-compra", response_model=list[PedidoOut])
def listar_pedidos(db: Session = Depends(get_db), _=Depends(requer_permissao("compras:read"))):
    return db.query(PedidoCompra).order_by(PedidoCompra.criado_em.desc()).all()


@router.post("/pedidos-compra", response_model=PedidoOut, status_code=status.HTTP_201_CREATED)
def criar_pedido(dados: PedidoCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("compras:write"))):
    if not db.get(Fornecedor, dados.fornecedor_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fornecedor nao encontrado.")
    itens = [PedidoCompraItem(**item.model_dump()) for item in dados.itens]
    valor_total = sum(item.quantidade * item.valor_unitario for item in itens)
    pedido = PedidoCompra(
        fornecedor_id=dados.fornecedor_id,
        requisicao_id=dados.requisicao_id,
        almoxarifado_id=dados.almoxarifado_id,
        valor_total=valor_total,
        itens=itens,
    )
    db.add(pedido)
    if dados.requisicao_id:
        requisicao = db.get(RequisicaoCompra, dados.requisicao_id)
        if requisicao:
            requisicao.status = "Convertida em pedido"
    db.commit()
    db.refresh(pedido)
    return pedido


@router.patch("/pedidos-compra/{pedido_id}", response_model=PedidoOut)
def atualizar_status_pedido(
    pedido_id: int,
    dados: PedidoUpdateStatus,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(get_current_user),
):
    pedido = db.get(PedidoCompra, pedido_id)
    if not pedido:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedido nao encontrado.")
    if dados.status not in STATUS_PEDIDO_VALIDOS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Status invalido.")

    if dados.status != pedido.status:
        permitidos = TRANSICOES_PEDIDO.get(pedido.status, set())
        if dados.status not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Transicao de status invalida: '{pedido.status}' -> '{dados.status}'.",
            )
        chave_permissao = f"compras:transicao:{pedido.status}:{dados.status}"
        if not tem_permissao(ator, chave_permissao) and not tem_permissao(ator, "compras:write"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Seu perfil nao tem permissao para a transicao '{pedido.status}' -> '{dados.status}'.",
            )
    elif not tem_permissao(ator, "compras:write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao tem permissao para esta acao.")

    if dados.status == "Recebido" and pedido.status != "Recebido":
        if not pedido.almoxarifado_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Defina o almoxarifado de destino (almoxarifado_id) antes de marcar o pedido como recebido.",
            )
        # Da entrada em cada item no estoque e atualiza o custo medio do material.
        for item in pedido.itens:
            aplicar_movimentacao(
                db,
                almoxarifado_id=pedido.almoxarifado_id,
                material_id=item.material_id,
                tipo="entrada",
                quantidade=float(item.quantidade),
                usuario_id=ator.id,
                observacao=f"Recebimento do pedido de compra #{pedido.id}",
                valor_unitario=float(item.valor_unitario) if item.valor_unitario else None,
            )
        registrar(db, usuario_id=ator.id, acao="pedido_recebido", entidade="pedidos_compra", entidade_id=str(pedido.id))

    pedido.status = dados.status
    db.commit()
    db.refresh(pedido)
    return pedido
