"""Fornecedores, requisicoes de compra e pedidos de compra."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Fornecedor(Base):
    __tablename__ = "fornecedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    documento: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contato: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telefone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(160), nullable=True)


class RequisicaoCompra(Base):
    """Pedido interno de compra feito por uma area (ex.: almoxarifado pedindo reposicao)."""

    __tablename__ = "requisicoes_compra"

    id: Mapped[int] = mapped_column(primary_key=True)
    solicitante_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obras.id"), nullable=True)
    almoxarifado_id: Mapped[int | None] = mapped_column(ForeignKey("almoxarifados.id"), nullable=True)
    # Preenchido quando a requisicao e para repor o estoque minimo de um
    # almoxarifado (ao inves de -- ou alem de -- suprir uma obra especifica).
    origem_automatica: Mapped[bool] = mapped_column(default=False, nullable=False)
    # True quando gerada pelo sistema por saldo <= estoque_minimo do material.
    status: Mapped[str] = mapped_column(String(20), default="Pendente")
    # Pendente | Aprovada | Rejeitada | Convertida em pedido
    observacoes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    itens: Mapped[list["RequisicaoCompraItem"]] = relationship(
        back_populates="requisicao", cascade="all, delete-orphan"
    )
    obra: Mapped["Obra | None"] = relationship(back_populates="requisicoes_compra")
    almoxarifado: Mapped["Almoxarifado | None"] = relationship()


class RequisicaoCompraItem(Base):
    __tablename__ = "requisicao_compra_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisicao_id: Mapped[int] = mapped_column(ForeignKey("requisicoes_compra.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), nullable=False)
    quantidade: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    requisicao: Mapped["RequisicaoCompra"] = relationship(back_populates="itens")
    material: Mapped["Material"] = relationship()


class PedidoCompra(Base):
    """Pedido de compra formal enviado a um fornecedor."""

    __tablename__ = "pedidos_compra"

    id: Mapped[int] = mapped_column(primary_key=True)
    requisicao_id: Mapped[int | None] = mapped_column(ForeignKey("requisicoes_compra.id"), nullable=True)
    fornecedor_id: Mapped[int] = mapped_column(ForeignKey("fornecedores.id"), nullable=False)
    almoxarifado_id: Mapped[int | None] = mapped_column(ForeignKey("almoxarifados.id"), nullable=True)
    # Almoxarifado que recebera os itens quando o pedido for marcado como "Recebido".
    status: Mapped[str] = mapped_column(String(20), default="Aberto")
    # Aberto | Enviado | Recebido | Cancelado
    valor_total: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fornecedor: Mapped["Fornecedor"] = relationship()
    almoxarifado: Mapped["Almoxarifado | None"] = relationship()
    itens: Mapped[list["PedidoCompraItem"]] = relationship(back_populates="pedido", cascade="all, delete-orphan")


class PedidoCompraItem(Base):
    __tablename__ = "pedido_compra_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos_compra.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), nullable=False)
    quantidade: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    valor_unitario: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    pedido: Mapped["PedidoCompra"] = relationship(back_populates="itens")
    material: Mapped["Material"] = relationship()
