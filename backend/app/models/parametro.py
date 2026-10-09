"""Parametros globais administrativos (chave/valor configuravel)."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ParametroGlobal(Base):
    __tablename__ = "parametros_globais"

    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[dict] = mapped_column(JSON, nullable=False)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
