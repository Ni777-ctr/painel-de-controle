"""Equipes de campo e seus integrantes."""
from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Equipe(Base):
    __tablename__ = "equipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), nullable=False)
    lider_usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    ativa: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    membros: Mapped[list["EquipeMembro"]] = relationship(back_populates="equipe", cascade="all, delete-orphan")


class EquipeMembro(Base):
    __tablename__ = "equipe_membros"

    id: Mapped[int] = mapped_column(primary_key=True)
    equipe_id: Mapped[int] = mapped_column(ForeignKey("equipes.id"), nullable=False)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    funcao: Mapped[str | None] = mapped_column(String(60), nullable=True)  # ex: Encarregado, Eletricista

    equipe: Mapped["Equipe"] = relationship(back_populates="membros")
