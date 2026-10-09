"""Logs de auditoria (trilha de acoes do sistema)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_criado_em", "criado_em"),
        Index("ix_audit_logs_categoria_criado_em", "categoria", "criado_em"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    bot: Mapped[str | None] = mapped_column(String(80), nullable=True)  # nome da automacao, se aplicavel
    acao: Mapped[str] = mapped_column(String(120), nullable=False)
    # login | falha_acesso | exportacao | exclusao | alteracao | sistema
    # (derivada da acao em app/auditoria_utils.py:classificar_acao)
    categoria: Mapped[str] = mapped_column(String(20), nullable=False, default="alteracao", server_default="alteracao")
    entidade: Mapped[str] = mapped_column(String(60), nullable=False)
    entidade_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    antes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    depois: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuario: Mapped["Usuario | None"] = relationship()
