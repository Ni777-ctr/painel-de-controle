"""Frota: veiculos e suas manutencoes (preventivas/corretivas) e vencimentos
de documentos (licenciamento, seguro)."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Veiculo(Base):
    __tablename__ = "veiculos"

    id: Mapped[int] = mapped_column(primary_key=True)
    placa: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    modelo: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo: Mapped[str | None] = mapped_column(String(40), nullable=True)  # Caminhao, Utilitario, Cesto aereo...
    ano: Mapped[int | None] = mapped_column(nullable=True)
    regional: Mapped[str | None] = mapped_column(String(60), nullable=True)
    equipe_id: Mapped[int | None] = mapped_column(ForeignKey("equipes.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Ativo")  # Ativo | Manutencao | Inativo
    km_atual: Mapped[int] = mapped_column(default=0)
    licenciamento_vence_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    seguro_vence_em: Mapped[date | None] = mapped_column(Date, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    equipe: Mapped["Equipe | None"] = relationship()
    manutencoes: Mapped[list["ManutencaoVeiculo"]] = relationship(
        back_populates="veiculo", cascade="all, delete-orphan"
    )


class ManutencaoVeiculo(Base):
    __tablename__ = "manutencoes_veiculo"

    id: Mapped[int] = mapped_column(primary_key=True)
    veiculo_id: Mapped[int] = mapped_column(ForeignKey("veiculos.id"), nullable=False, index=True)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False, default="Preventiva")  # Preventiva | Corretiva
    descricao: Mapped[str] = mapped_column(String(255), nullable=False)
    data_prevista: Mapped[date | None] = mapped_column(Date, nullable=True)
    data_realizada: Mapped[date | None] = mapped_column(Date, nullable=True)
    km: Mapped[int | None] = mapped_column(nullable=True)
    custo: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Agendada")  # Agendada | Concluida | Cancelada
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    veiculo: Mapped["Veiculo"] = relationship(back_populates="manutencoes")
