"""Supervisao: cadastro de empreiteiras e Relatorios Diarios de Campo."""
from datetime import date, datetime, time

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Empreiteira(Base):
    __tablename__ = "empreiteiras"
    __table_args__ = (Index("uq_empreiteiras_cnpj", "cnpj", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    nome_razao_social: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    # Gravado formatado (00.000.000/0000-00). Unico quando informado (NULL pode repetir):
    # ver o indice uq_empreiteiras_cnpj em __table_args__.
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    codigo_contrato: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=true())
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RelatorioSupervisao(Base):
    __tablename__ = "relatorios_supervisao"
    __table_args__ = (
        Index("ix_relatorios_supervisao_data_municipio", "data_relatorio", "municipio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    data_relatorio: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    projeto_atividade: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ordem: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Concluído | Parcial | Cancelado | Sem status  (String validada no schema, como os demais status do projeto)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Sem status", server_default="Sem status", index=True)
    porcentagem_execucao: Mapped[int | None] = mapped_column(Integer, nullable=True)

    empreiteira_id: Mapped[int | None] = mapped_column(ForeignKey("empreiteiras.id"), nullable=True, index=True)
    # Texto livre para empreiteira que ainda nao esta cadastrada.
    empreiteira_nome_customizado: Mapped[str | None] = mapped_column(String(160), nullable=True)

    contato: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lv_lm: Mapped[str | None] = mapped_column(String(20), nullable=True)
    responsavel: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    codigo_placa: Mapped[str | None] = mapped_column(String(40), nullable=True)
    supervisor_beq: Mapped[str | None] = mapped_column(String(120), nullable=True)

    endereco: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bairro: Mapped[str | None] = mapped_column(String(120), nullable=True)
    municipio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # Lista de integrantes: [{"nome": "...", "funcao": "..."}]
    composicao_equipe: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    servicos_executados: Mapped[str | None] = mapped_column(Text, nullable=True)
    pendencias: Mapped[str | None] = mapped_column(Text, nullable=True)

    horario_saida_base: Mapped[time | None] = mapped_column(Time, nullable=True)
    horario_chegada_obra: Mapped[time | None] = mapped_column(Time, nullable=True)
    horario_saida_obra: Mapped[time | None] = mapped_column(Time, nullable=True)
    horario_chegada_base: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Lista de fotos: [{"url": "...", "legenda": "..."}]
    fotos: Mapped[list | None] = mapped_column(JSON(none_as_null=True), nullable=True)

    criado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    empreiteira: Mapped["Empreiteira | None"] = relationship()
