"""Registro de cada exportacao de relatorio (quem gerou, quando, com quais filtros)."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RelatorioGerado(Base):
    __tablename__ = "relatorios_gerados"
    __table_args__ = (Index("ix_relatorios_tipo_criado_em", "tipo", "criado_em"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    formato: Mapped[str] = mapped_column(String(10), nullable=False)  # xlsx | pdf
    periodo_inicio: Mapped[date | None] = mapped_column(Date, nullable=True)
    periodo_fim: Mapped[date | None] = mapped_column(Date, nullable=True)
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obras.id"), nullable=True)
    responsavel_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    filtros: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    nome_arquivo: Mapped[str] = mapped_column(String(160), nullable=False)
    linhas: Mapped[int] = mapped_column(default=0, nullable=False)
    tamanho_bytes: Mapped[int] = mapped_column(default=0, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    usuario: Mapped["Usuario"] = relationship(foreign_keys=[usuario_id])
