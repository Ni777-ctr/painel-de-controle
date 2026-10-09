"""Tabelas alimentadas pela importacao das planilhas FATURAMENTO.xlsx e
PROGRAMACAO_TEES (ver app/importacao/ e docs/IMPORTACAO_PLANILHAS.md).

Todas guardam o codigo do projeto como veio (`projeto_codigo`) e a `obra_id`
quando a obra existe -- linhas de projetos sem obra cadastrada sao mantidas
como historico, sem criar obra automaticamente. Colunas da planilha sem campo
proprio vao para `dados_extras` (nada e' descartado)."""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class _LinhaImportada:
    """Colunas comuns de linha importada de planilha."""

    id: Mapped[int] = mapped_column(primary_key=True)
    obra_id: Mapped[int | None] = mapped_column(ForeignKey("obras.id"), nullable=True, index=True)
    projeto_codigo: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    linha_origem: Mapped[int | None] = mapped_column(nullable=True)  # numero da linha na aba
    origem: Mapped[str] = mapped_column(String(40), nullable=False, default="planilha", index=True)
    dados_extras: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    importado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InventarioObra(_LinhaImportada, Base):
    __tablename__ = "inventarios_obra"

    familia: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valor_orcado: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_inventario: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    diferenca_saldo: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_parcial_solicitado: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    valor_pago_parcial: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    data_solicitacao_parcial: Mapped[date | None] = mapped_column(Date, nullable=True)
    conclusao: Mapped[str | None] = mapped_column(String(80), nullable=True)
    data_inventario: Mapped[date | None] = mapped_column(Date, nullable=True)
    enviado_faturamento_enel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tecnico_responsavel: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    observacao: Mapped[str | None] = mapped_column(Text, nullable=True)
    ciclo_medicao: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ExecucaoObra(_LinhaImportada, Base):
    __tablename__ = "execucoes_obra"

    data: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    circuito: Mapped[str | None] = mapped_column(String(80), nullable=True)
    familia: Mapped[str | None] = mapped_column(String(40), nullable=True)
    percentual_executado: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    nec_orcado: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    nec_programada: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    nec_executada: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    empresa: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    atraso: Mapped[str | None] = mapped_column(String(60), nullable=True)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    intervencao: Mapped[str | None] = mapped_column(String(80), nullable=True)
    obra_eletricamente_concluida: Mapped[str | None] = mapped_column(String(40), nullable=True)
    data_envio_conclusao: Mapped[date | None] = mapped_column(Date, nullable=True)
    qtde_lv: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    qtde_lm: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    inventario_aprovado: Mapped[str | None] = mapped_column(String(40), nullable=True)
    motivo_reprova: Mapped[str | None] = mapped_column(Text, nullable=True)
    medicao: Mapped[str | None] = mapped_column(String(60), nullable=True)


class SigeoExtracao(_LinhaImportada, Base):
    __tablename__ = "sigeo_extracoes"

    data_programacao: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    status_programacao: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tipo_intervencao: Mapped[str | None] = mapped_column(String(80), nullable=True)
    numero_poweron: Mapped[str | None] = mapped_column(String(60), nullable=True)
    equipamentos: Mapped[str | None] = mapped_column(Text, nullable=True)
    chi: Mapped[float | None] = mapped_column(Numeric(14, 3), nullable=True)
    horario_inicio: Mapped[str | None] = mapped_column(String(8), nullable=True)
    horario_fim: Mapped[str | None] = mapped_column(String(8), nullable=True)
    contratada: Mapped[str | None] = mapped_column(String(80), nullable=True)


class GeradorProgramacao(_LinhaImportada, Base):
    __tablename__ = "geradores_programacao"

    id_origem: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str | None] = mapped_column(String(60), nullable=True)
    regional: Mapped[str | None] = mapped_column(String(60), nullable=True)
    area: Mapped[str | None] = mapped_column(String(60), nullable=True)
    contratada_propria: Mapped[str | None] = mapped_column(String(60), nullable=True)
    tecnico_pre_operacao: Mapped[str | None] = mapped_column(String(120), nullable=True)
    circuito: Mapped[str | None] = mapped_column(String(80), nullable=True)
    equipamento_seccionador: Mapped[str | None] = mapped_column(String(80), nullable=True)
    numero: Mapped[str | None] = mapped_column(String(60), nullable=True)
    endereco: Mapped[str | None] = mapped_column(String(255), nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
