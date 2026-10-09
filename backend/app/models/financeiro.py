"""Medicoes, faturas, pagamentos, glosas e alertas financeiros
(faturamento/cobranca). A Obra continua sendo a entidade central -- nada
aqui duplica Obra/Cliente, so referencia por FK."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Medicao(Base):
    __tablename__ = "medicoes"
    # Um ciclo por obra (NULL = medicao criada manualmente, sem ciclo informado).
    __table_args__ = (UniqueConstraint("obra_id", "ciclo_medicao", name="uq_medicao_obra_ciclo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obras.id"), nullable=False)
    contrato: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    percentual: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    # NECs medidos neste ciclo -- ponte entre Programacao/execucao e o
    # faturamento (usado no resumo mensal e na evolucao de 6 meses).
    necs_medidos: Mapped[float] = mapped_column(Numeric(14, 3), default=0, nullable=False)
    responsavel_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Rascunho")  # Rascunho | Aprovada | Reprovada
    dias_parada: Mapped[int] = mapped_column(default=0)
    # ---- Campos vindos da aba MEDICAO da planilha (nulos em medicoes criadas na API) ----
    ciclo_medicao: Mapped[str | None] = mapped_column(String(30), nullable=True)
    area: Mapped[str | None] = mapped_column(String(40), nullable=True)  # Construcao | Manutencao
    familia: Mapped[str | None] = mapped_column(String(20), nullable=True)
    valor_faturado: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    emitida_nf: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    data_emissao_nf: Mapped[date | None] = mapped_column(Date, nullable=True)
    necs_orcados: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    necs_inventariados: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    divergencia_necs: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    valor_pago_por_nec: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    origem: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    obra: Mapped["Obra"] = relationship(back_populates="medicoes")
    glosas: Mapped[list["Glosa"]] = relationship(back_populates="medicao", cascade="all, delete-orphan")


class Glosa(Base):
    """Valor descontado de uma medicao por divergencia/nao conformidade."""

    __tablename__ = "glosas"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicao_id: Mapped[int] = mapped_column(ForeignKey("medicoes.id"), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    resolvida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    medicao: Mapped["Medicao"] = relationship(back_populates="glosas")


class Fatura(Base):
    __tablename__ = "faturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int] = mapped_column(ForeignKey("obras.id"), nullable=False)
    medicao_id: Mapped[int | None] = mapped_column(ForeignKey("medicoes.id"), nullable=True)
    valor: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    # NECs cobertos por esta fatura -- soma-se em Obra.necs_faturados ao emitir.
    necs_faturados: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    vencimento: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="Emitida")  # Emitida | Paga | Atrasada
    percentual_faturado: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    percentual_pago: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    obra: Mapped["Obra"] = relationship(back_populates="faturas")
    pagamentos: Mapped[list["Pagamento"]] = relationship(back_populates="fatura", cascade="all, delete-orphan")


class Pagamento(Base):
    __tablename__ = "pagamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    fatura_id: Mapped[int] = mapped_column(ForeignKey("faturas.id"), nullable=False)
    valor: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    data_pagamento: Mapped[date] = mapped_column(Date, nullable=False)
    metodo: Mapped[str | None] = mapped_column(String(40), nullable=True)  # Boleto | Pix | Transferencia
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fatura: Mapped["Fatura"] = relationship(back_populates="pagamentos")


class AlertaFinanceiro(Base):
    """Alertas de faturamento/cobranca (saldo baixo, vencimento proximo,
    medicao aguardando faturamento, fatura vencida, glosa pendente).
    Persistidos no banco -- nesta etapa NAO envia e-mail real, so registra
    (ver app/services/faturamento_service.py)."""

    __tablename__ = "alertas_financeiros"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    # saldo_baixo | vencimento_proximo | medicao_aguardando_faturamento | fatura_vencida | glosa_pendente
    nivel: Mapped[str] = mapped_column(String(20), default="atencao")  # info | atencao | critico
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obras.id"), nullable=True)
    fatura_id: Mapped[int | None] = mapped_column(ForeignKey("faturas.id"), nullable=True)
    medicao_id: Mapped[int | None] = mapped_column(ForeignKey("medicoes.id"), nullable=True)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    resolvido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolvido_por_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    obra: Mapped["Obra | None"] = relationship()
    fatura: Mapped["Fatura | None"] = relationship()
    medicao: Mapped["Medicao | None"] = relationship()
