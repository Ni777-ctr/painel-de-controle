"""Materiais, almoxarifados e saldos de estoque."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Material(Base):
    __tablename__ = "materiais"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    unidade: Mapped[str] = mapped_column(String(10), nullable=False, default="UN")
    estoque_minimo: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # Custo medio ponderado, recalculado a cada entrada com valor_unitario informado
    # (ex.: recebimento de pedido de compra). Usado para valorizar consumo por obra.
    custo_medio: Mapped[float] = mapped_column(Numeric(12, 2), default=0)


class Almoxarifado(Base):
    __tablename__ = "almoxarifados"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    regional: Mapped[str | None] = mapped_column(String(60), nullable=True)


class EstoqueItem(Base):
    __tablename__ = "estoque_itens"
    __table_args__ = (UniqueConstraint("almoxarifado_id", "material_id", name="uq_estoque_almox_material"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    almoxarifado_id: Mapped[int] = mapped_column(ForeignKey("almoxarifados.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), nullable=False)
    quantidade: Mapped[float] = mapped_column(Numeric(12, 2), default=0)

    almoxarifado: Mapped["Almoxarifado"] = relationship()
    material: Mapped["Material"] = relationship()


class MovimentacaoEstoque(Base):
    """Ledger de entradas/saidas de material -- a saida vinculada a uma obra e
    o jeito de registrar consumo de material por obra, sem duplicar o
    cadastro de materiais/estoque."""

    __tablename__ = "movimentacoes_estoque"

    id: Mapped[int] = mapped_column(primary_key=True)
    almoxarifado_id: Mapped[int] = mapped_column(ForeignKey("almoxarifados.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), nullable=False, index=True)
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obras.id"), nullable=True, index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    tipo: Mapped[str] = mapped_column(String(10), nullable=False)  # entrada | saida
    quantidade: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    # Custo unitario da entrada (ex.: valor_unitario do item do pedido recebido).
    # Usado para atualizar Material.custo_medio; nao se aplica a saidas.
    valor_unitario: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    observacao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    almoxarifado: Mapped["Almoxarifado"] = relationship()
    material: Mapped["Material"] = relationship()
    obra: Mapped["Obra | None"] = relationship(back_populates="movimentacoes_estoque")
