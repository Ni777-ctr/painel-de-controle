"""Automacoes gerais e o dominio de automacao de rede eletrica
(self-healing/FLISR, subestacoes digitais, gestao de vegetacao) ja
referenciado pelo frontend em src/lib/api.ts."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Automacao(Base):
    """Automacao generica configuravel (ex.: alerta de fatura, gatilho de e-mail)."""

    __tablename__ = "automacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    gatilho: Mapped[str] = mapped_column(String(80), nullable=False)  # ex: "fatura.atrasada"
    acao: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExecucaoAutomacao(Base):
    """Registro de cada execucao de uma automacao/bot (sucesso ou falha). Os
    bots (ex.: SIGEOhelper, Playwright) reportam aqui via
    POST /automacoes/{id}/execucoes; o painel unificado e as notificacoes usam
    a ultima execucao para apontar automacoes falhando."""

    __tablename__ = "execucoes_automacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    automacao_id: Mapped[int] = mapped_column(ForeignKey("automacoes.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)  # sucesso | falha
    mensagem: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duracao_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    iniciado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    automacao: Mapped["Automacao"] = relationship()


class Subestacao(Base):
    __tablename__ = "subestacoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    operacao_remota_ativa: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    leituras: Mapped[list["LeituraSubestacao"]] = relationship(
        back_populates="subestacao", order_by="LeituraSubestacao.registrado_em.desc()"
    )


class LeituraSubestacao(Base):
    __tablename__ = "leituras_subestacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    subestacao_id: Mapped[int] = mapped_column(ForeignKey("subestacoes.id"), nullable=False)
    registrado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    temperatura_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    carga_percentual: Mapped[float | None] = mapped_column(Float, nullable=True)
    vibracao_mm_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    alerta_gerado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    subestacao: Mapped["Subestacao"] = relationship(back_populates="leituras")


class PontoVegetacao(Base):
    """Ponto critico de vegetacao proximo a rede (poda/risco de interferencia)."""

    __tablename__ = "pontos_vegetacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    descricao: Mapped[str | None] = mapped_column(String(255), nullable=True)
    risco: Mapped[str] = mapped_column(String(20), nullable=False, default="baixo")  # baixo|medio|alto
    resolvido: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class EventoSelfHealing(Base):
    """Evento de auto-restabelecimento (FLISR) da rede."""

    __tablename__ = "eventos_self_healing"

    id: Mapped[int] = mapped_column(primary_key=True)
    subestacao_id: Mapped[int | None] = mapped_column(ForeignKey("subestacoes.id"), nullable=True)
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolvido_automaticamente: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tempo_restauracao_segundos: Mapped[int | None] = mapped_column(Integer, nullable=True)
