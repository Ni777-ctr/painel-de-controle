"""Notificacoes internas (sino do sistema) com fila de envio por e-mail."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Notificacao(Base):
    __tablename__ = "notificacoes"
    __table_args__ = (
        # Garante que o mesmo evento (chave_dedup) notifica cada usuario uma unica vez.
        UniqueConstraint("usuario_id", "chave_dedup", name="uq_notificacao_usuario_chave"),
        Index("ix_notificacoes_usuario_lida", "usuario_id", "lida"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(50), nullable=False)
    modulo: Mapped[str] = mapped_column(String(30), nullable=False)  # faturamento|obras|frota|programacao|automacao|estoque|seguranca
    nivel: Mapped[str] = mapped_column(String(20), nullable=False, default="atencao")  # info | atencao | critico
    titulo: Mapped[str] = mapped_column(String(160), nullable=False)
    mensagem: Mapped[str] = mapped_column(Text, nullable=False)
    entidade: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entidade_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    chave_dedup: Mapped[str] = mapped_column(String(120), nullable=False)
    lida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # E-mail: None (nao aplicavel) | pendente | enviado | falhou | ignorado
    email_status: Mapped[str | None] = mapped_column(String(15), nullable=True)
    email_tentativas: Mapped[int] = mapped_column(default=0, nullable=False)
    email_enviado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    email_erro: Mapped[str | None] = mapped_column(String(255), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuario: Mapped["Usuario"] = relationship()
