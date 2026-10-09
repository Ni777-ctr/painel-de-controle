"""Regras de negocio de estoque compartilhadas entre o router de estoque
(movimentacao manual) e o recebimento automatico de pedidos de compra.

Mantem uma unica fonte de verdade para: atualizar o saldo em EstoqueItem,
recalcular o custo medio ponderado do Material em entradas com valor
unitario, valorizar/debitar o custo_realizado da Obra em saidas vinculadas
a uma obra, e disparar uma RequisicaoCompra automatica quando o saldo cai
para o estoque minimo ou abaixo dele."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.models.compras import RequisicaoCompra, RequisicaoCompraItem
from app.models.estoque import Almoxarifado, EstoqueItem, Material, MovimentacaoEstoque
from app.models.obra import Obra

STATUS_REQUISICAO_ABERTOS = ("Pendente", "Aprovada")


def aplicar_movimentacao(
    db: Session,
    *,
    almoxarifado_id: int,
    material_id: int,
    tipo: str,
    quantidade: float,
    obra_id: int | None = None,
    usuario_id: int | None = None,
    observacao: str | None = None,
    valor_unitario: float | None = None,
) -> MovimentacaoEstoque:
    if tipo not in ("entrada", "saida"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="tipo deve ser 'entrada' ou 'saida'.")
    if quantidade <= 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="quantidade deve ser maior que zero.")

    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material nao encontrado.")
    if not db.get(Almoxarifado, almoxarifado_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Almoxarifado nao encontrado.")

    item = (
        db.query(EstoqueItem)
        .filter(EstoqueItem.almoxarifado_id == almoxarifado_id, EstoqueItem.material_id == material_id)
        .first()
    )
    if not item:
        item = EstoqueItem(almoxarifado_id=almoxarifado_id, material_id=material_id, quantidade=0)
        db.add(item)

    saldo_atual = float(item.quantidade)

    if tipo == "saida":
        if quantidade > saldo_atual:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Saldo insuficiente: disponivel {saldo_atual}, solicitado {quantidade}.",
            )
        item.quantidade = saldo_atual - quantidade

        # Saida vinculada a obra: valoriza o consumo pelo custo medio do
        # material e incrementa o custo realizado da obra.
        if obra_id is not None and float(material.custo_medio or 0) > 0:
            obra = db.get(Obra, obra_id)
            if obra:
                obra.custo_realizado = float(obra.custo_realizado) + quantidade * float(material.custo_medio)

        _verificar_estoque_minimo(
            db, material=material, almoxarifado_id=almoxarifado_id, saldo_apos=item.quantidade, usuario_id=usuario_id
        )
    else:
        nova_quantidade = saldo_atual + quantidade
        if valor_unitario is not None and valor_unitario > 0:
            custo_medio_atual = float(material.custo_medio or 0)
            if nova_quantidade > 0:
                material.custo_medio = (
                    (saldo_atual * custo_medio_atual) + (quantidade * valor_unitario)
                ) / nova_quantidade
        item.quantidade = nova_quantidade

    movimentacao = MovimentacaoEstoque(
        almoxarifado_id=almoxarifado_id,
        material_id=material_id,
        obra_id=obra_id,
        usuario_id=usuario_id,
        tipo=tipo,
        quantidade=quantidade,
        valor_unitario=valor_unitario,
        observacao=observacao,
    )
    db.add(movimentacao)
    return movimentacao


def _verificar_estoque_minimo(
    db: Session,
    *,
    material: Material,
    almoxarifado_id: int,
    saldo_apos: float,
    usuario_id: int | None,
) -> None:
    """Se o saldo apos a saida ficou <= estoque_minimo do material, gera uma
    RequisicaoCompra automatica de reposicao -- a menos que ja exista uma
    requisicao automatica aberta para o mesmo material/almoxarifado."""
    estoque_minimo = float(material.estoque_minimo or 0)
    if estoque_minimo <= 0 or float(saldo_apos) > estoque_minimo:
        return

    ja_existe = (
        db.query(RequisicaoCompra)
        .join(RequisicaoCompraItem, RequisicaoCompraItem.requisicao_id == RequisicaoCompra.id)
        .filter(
            RequisicaoCompra.origem_automatica.is_(True),
            RequisicaoCompra.almoxarifado_id == almoxarifado_id,
            RequisicaoCompra.status.in_(STATUS_REQUISICAO_ABERTOS),
            RequisicaoCompraItem.material_id == material.id,
        )
        .first()
    )
    if ja_existe:
        return

    quantidade_sugerida = estoque_minimo - float(saldo_apos)
    requisicao = RequisicaoCompra(
        solicitante_usuario_id=usuario_id,
        almoxarifado_id=almoxarifado_id,
        origem_automatica=True,
        status="Pendente",
        observacoes=(
            f"Gerada automaticamente: saldo de '{material.nome}' ({saldo_apos}) "
            f"atingiu o estoque minimo ({estoque_minimo})."
        ),
    )
    requisicao.itens = [RequisicaoCompraItem(material_id=material.id, quantidade=quantidade_sugerida)]
    db.add(requisicao)
    db.flush()  # obtem requisicao.id para a auditoria
    registrar(
        db,
        usuario_id=usuario_id,
        acao="requisicao_gerada_automaticamente",
        entidade="requisicoes_compra",
        entidade_id=str(requisicao.id),
        depois={"material_id": material.id, "quantidade_sugerida": quantidade_sugerida},
    )
