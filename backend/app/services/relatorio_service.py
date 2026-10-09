"""Relatorios exportaveis (Excel/PDF) por periodo, obra e responsavel.

Cada tipo de relatorio e' uma funcao que devolve um `Tabela` (titulo, colunas,
linhas). Os renderizadores (`para_xlsx`, `para_pdf`) sao genericos, entao
adicionar um novo relatorio e' so' registrar uma funcao em REGISTRO.

Semantica dos filtros (a mesma em todos os tipos; `data_ref` varia):
- periodo (data_inicio/data_fim): aplicado sobre a "data de referencia" do tipo.
- obra_id: restringe a uma obra.
- responsavel_id (usuario): lider da equipe da obra/programacao/veiculo; no caso
  de medicoes, o responsavel da medicao; em movimentacoes de estoque, quem lancou.

Todo arquivo gerado traz no cabecalho quem gerou, quando e com quais filtros;
o registro persistente fica em RelatorioGerado (ver routers/relatorios.py)."""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO

from sqlalchemy import Date, cast, func
from sqlalchemy.orm import Session, joinedload

from app.models.estoque import MovimentacaoEstoque
from app.models.financeiro import Fatura, Medicao
from app.models.frota import ManutencaoVeiculo, Veiculo
from app.models.equipe import Equipe
from app.models.obra import Obra, Programacao

MAX_LINHAS_XLSX = 50_000
MAX_LINHAS_PDF = 3_000


class RelatorioMuitoGrande(Exception):
    pass


@dataclass
class Filtros:
    data_inicio: date | None = None
    data_fim: date | None = None
    obra_id: int | None = None
    responsavel_id: int | None = None

    def como_dict(self) -> dict:
        return {
            "data_inicio": self.data_inicio.isoformat() if self.data_inicio else None,
            "data_fim": self.data_fim.isoformat() if self.data_fim else None,
            "obra_id": self.obra_id,
            "responsavel_id": self.responsavel_id,
        }


@dataclass
class Tabela:
    titulo: str
    colunas: list[str]
    linhas: list[list] = field(default_factory=list)
    # Indices (0-based) de colunas monetarias / numericas, para formatacao.
    colunas_moeda: set[int] = field(default_factory=set)


@dataclass
class TipoRelatorio:
    chave: str
    nome: str
    descricao: str
    permissao_leitura: str  # alem de relatorios:export
    data_ref: str  # descricao humana da data usada no filtro de periodo
    gerar: object  # callable(db, Filtros) -> Tabela


def _inicio_dt(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _fim_dt_exclusivo(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time.min, tzinfo=timezone.utc)


def _fmt_data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _fmt_dt(d) -> str:
    return d.strftime("%d/%m/%Y %H:%M") if d else ""


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------
def rel_obras(db: Session, f: Filtros) -> Tabela:
    q = db.query(Obra).options(joinedload(Obra.cliente), joinedload(Obra.equipe))
    ref = func.coalesce(Obra.data_inicio, cast(Obra.criado_em, Date))
    if f.data_inicio:
        q = q.filter(ref >= f.data_inicio)
    if f.data_fim:
        q = q.filter(ref <= f.data_fim)
    if f.obra_id:
        q = q.filter(Obra.id == f.obra_id)
    if f.responsavel_id:
        q = q.join(Equipe, Obra.equipe_id == Equipe.id).filter(Equipe.lider_usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Obras", [
        "WL", "Descricao", "Regional", "Cliente", "Equipe", "Status", "Valor contrato (R$)",
        "Custo previsto (R$)", "Custo realizado (R$)", "Avanco previsto (%)", "Avanco realizado (%)",
        "NECs planej.", "NECs exec.", "NECs fat.", "Inicio", "Fim",
    ], colunas_moeda={6, 7, 8})
    for o in q.order_by(Obra.wl).all():
        t.linhas.append([
            o.wl, o.descricao or "", o.regional or "", o.cliente.nome if o.cliente else "",
            o.equipe.nome if o.equipe else "", o.status, float(o.valor_contrato), float(o.custo_previsto),
            float(o.custo_realizado), float(o.avanco_previsto), float(o.avanco_realizado),
            o.necs_planejados, o.necs_executados, o.necs_faturados, _fmt_data(o.data_inicio), _fmt_data(o.data_fim),
        ])
    return t


def rel_faturas(db: Session, f: Filtros) -> Tabela:
    q = db.query(Fatura).options(joinedload(Fatura.obra), joinedload(Fatura.pagamentos))
    if f.data_inicio:
        q = q.filter(Fatura.vencimento >= f.data_inicio)
    if f.data_fim:
        q = q.filter(Fatura.vencimento <= f.data_fim)
    if f.obra_id:
        q = q.filter(Fatura.obra_id == f.obra_id)
    if f.responsavel_id:
        q = q.join(Medicao, Fatura.medicao_id == Medicao.id).filter(Medicao.responsavel_usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Faturas", [
        "Fatura", "Obra (WL)", "Valor (R$)", "Pago (R$)", "Saldo (R$)", "NECs", "Vencimento", "Status", "Emitida em",
    ], colunas_moeda={2, 3, 4})
    hoje = date.today()
    for fa in q.order_by(Fatura.vencimento).all():
        pago = sum(float(p.valor) for p in fa.pagamentos)
        status = "Atrasada" if fa.status != "Paga" and fa.vencimento < hoje else fa.status
        t.linhas.append([
            fa.id, fa.obra.wl, float(fa.valor), pago, float(fa.valor) - pago, fa.necs_faturados or 0,
            _fmt_data(fa.vencimento), status, _fmt_dt(fa.criado_em),
        ])
    return t


def rel_medicoes(db: Session, f: Filtros) -> Tabela:
    q = db.query(Medicao).options(joinedload(Medicao.obra), joinedload(Medicao.glosas))
    if f.data_inicio:
        q = q.filter(Medicao.criado_em >= _inicio_dt(f.data_inicio))
    if f.data_fim:
        q = q.filter(Medicao.criado_em < _fim_dt_exclusivo(f.data_fim))
    if f.obra_id:
        q = q.filter(Medicao.obra_id == f.obra_id)
    if f.responsavel_id:
        q = q.filter(Medicao.responsavel_usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Medicoes", [
        "Medicao", "Obra (WL)", "Contrato (R$)", "Percentual (%)", "NECs medidos", "Glosas (R$)", "Dias parada", "Status", "Criada em",
    ], colunas_moeda={2, 5})
    for m in q.order_by(Medicao.criado_em).all():
        t.linhas.append([
            m.id, m.obra.wl, float(m.contrato), float(m.percentual), m.necs_medidos,
            sum(float(g.valor) for g in m.glosas), m.dias_parada, m.status, _fmt_dt(m.criado_em),
        ])
    return t


def rel_programacao(db: Session, f: Filtros) -> Tabela:
    q = db.query(Programacao).options(joinedload(Programacao.obra), joinedload(Programacao.equipe))
    if f.data_inicio:
        q = q.filter(Programacao.data >= f.data_inicio)
    if f.data_fim:
        q = q.filter(Programacao.data <= f.data_fim)
    if f.obra_id:
        q = q.filter(Programacao.obra_id == f.obra_id)
    if f.responsavel_id:
        q = q.join(Equipe, Programacao.equipe_id == Equipe.id).filter(Equipe.lider_usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Programacao", ["Data", "Obra (WL)", "Equipe", "Turno", "Status", "Observacoes"])
    for p in q.order_by(Programacao.data).all():
        t.linhas.append([_fmt_data(p.data), p.obra.wl, p.equipe.nome, p.turno, p.status, p.observacoes or ""])
    return t


def rel_estoque_movimentacoes(db: Session, f: Filtros) -> Tabela:
    q = db.query(MovimentacaoEstoque).options(
        joinedload(MovimentacaoEstoque.material), joinedload(MovimentacaoEstoque.almoxarifado), joinedload(MovimentacaoEstoque.obra)
    )
    if f.data_inicio:
        q = q.filter(MovimentacaoEstoque.criado_em >= _inicio_dt(f.data_inicio))
    if f.data_fim:
        q = q.filter(MovimentacaoEstoque.criado_em < _fim_dt_exclusivo(f.data_fim))
    if f.obra_id:
        q = q.filter(MovimentacaoEstoque.obra_id == f.obra_id)
    if f.responsavel_id:
        q = q.filter(MovimentacaoEstoque.usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Movimentacoes de Estoque", [
        "Data", "Tipo", "Material", "Almoxarifado", "Obra (WL)", "Quantidade", "Valor unit. (R$)", "Observacao",
    ], colunas_moeda={6})
    for m in q.order_by(MovimentacaoEstoque.criado_em).all():
        t.linhas.append([
            _fmt_dt(m.criado_em), m.tipo, f"{m.material.codigo or ''} {m.material.nome}".strip(), m.almoxarifado.nome,
            m.obra.wl if m.obra else "", float(m.quantidade),
            float(m.valor_unitario) if m.valor_unitario is not None else "", m.observacao or "",
        ])
    return t


def rel_frota(db: Session, f: Filtros) -> Tabela:
    """Frota: uma linha por manutencao (data prevista no periodo) + veiculos sem manutencao no periodo nao aparecem."""
    q = db.query(ManutencaoVeiculo).join(Veiculo).options(joinedload(ManutencaoVeiculo.veiculo))
    ref = func.coalesce(ManutencaoVeiculo.data_realizada, ManutencaoVeiculo.data_prevista)
    if f.data_inicio:
        q = q.filter(ref >= f.data_inicio)
    if f.data_fim:
        q = q.filter(ref <= f.data_fim)
    if f.responsavel_id:
        q = q.join(Equipe, Veiculo.equipe_id == Equipe.id).filter(Equipe.lider_usuario_id == f.responsavel_id)
    t = Tabela("Relatorio de Frota e Manutencoes", [
        "Placa", "Modelo", "Regional", "Status veiculo", "Km atual", "Manutencao", "Descricao",
        "Prevista", "Realizada", "Custo (R$)", "Status manutencao", "Licenciamento vence", "Seguro vence",
    ], colunas_moeda={9})
    for m in q.order_by(Veiculo.placa, ref).all():
        v = m.veiculo
        t.linhas.append([
            v.placa, v.modelo, v.regional or "", v.status, v.km_atual, m.tipo, m.descricao,
            _fmt_data(m.data_prevista), _fmt_data(m.data_realizada), float(m.custo), m.status,
            _fmt_data(v.licenciamento_vence_em), _fmt_data(v.seguro_vence_em),
        ])
    return t


REGISTRO: dict[str, TipoRelatorio] = {r.chave: r for r in [
    TipoRelatorio("obras", "Obras", "Carteira de obras com custos, avanco e NECs.", "obras:read", "data de inicio (ou criacao)", rel_obras),
    TipoRelatorio("faturas", "Faturas", "Faturas, pagamentos e saldo.", "financeiro:read", "vencimento", rel_faturas),
    TipoRelatorio("medicoes", "Medicoes", "Medicoes, NECs medidos e glosas.", "financeiro:read", "data de criacao", rel_medicoes),
    TipoRelatorio("programacao", "Programacao", "Programacao diaria de obras e equipes.", "programacao:read", "data da programacao", rel_programacao),
    TipoRelatorio("estoque_movimentacoes", "Movimentacoes de estoque", "Entradas e saidas de material (consumo por obra).", "estoque:read", "data da movimentacao", rel_estoque_movimentacoes),
    TipoRelatorio("frota", "Frota e manutencoes", "Veiculos, manutencoes e vencimento de documentos.", "frota:read", "data realizada (ou prevista) da manutencao", rel_frota),
]}


# ---------------------------------------------------------------------------
# Renderizacao
# ---------------------------------------------------------------------------
def _linhas_cabecalho(tabela: Tabela, gerado_por: str, gerado_em: datetime, filtros: Filtros, rotulos: dict) -> list[str]:
    partes = []
    if filtros.data_inicio or filtros.data_fim:
        partes.append(f"Periodo: {_fmt_data(filtros.data_inicio) or '...'} a {_fmt_data(filtros.data_fim) or '...'}")
    if filtros.obra_id:
        partes.append(f"Obra: {rotulos.get('obra', filtros.obra_id)}")
    if filtros.responsavel_id:
        partes.append(f"Responsavel: {rotulos.get('responsavel', filtros.responsavel_id)}")
    return [
        f"Gerado por {gerado_por} em {gerado_em.astimezone().strftime('%d/%m/%Y %H:%M')}",
        "Filtros: " + (" | ".join(partes) if partes else "nenhum (todos os registros)"),
        f"Total de linhas: {len(tabela.linhas)}",
    ]


def para_xlsx(tabela: Tabela, *, gerado_por: str, gerado_em: datetime, filtros: Filtros, rotulos: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    if len(tabela.linhas) > MAX_LINHAS_XLSX:
        raise RelatorioMuitoGrande(f"Mais de {MAX_LINHAS_XLSX} linhas; restrinja o periodo.")

    wb = Workbook()
    ws = wb.active
    ws.title = tabela.titulo[:31]
    ws["A1"] = tabela.titulo
    ws["A1"].font = Font(bold=True, size=14)
    meta = _linhas_cabecalho(tabela, gerado_por, gerado_em, filtros, rotulos)
    for i, texto in enumerate(meta, start=2):
        ws.cell(row=i, column=1, value=texto).font = Font(italic=True, color="555555")
    linha_cab = len(meta) + 3
    preench = PatternFill("solid", fgColor="E8590C")
    for c, nome in enumerate(tabela.colunas, start=1):
        cel = ws.cell(row=linha_cab, column=c, value=nome)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = preench
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    larguras = [len(n) for n in tabela.colunas]
    for r, linha in enumerate(tabela.linhas, start=linha_cab + 1):
        for c, valor in enumerate(linha, start=1):
            # Evita injecao de formula (CSV/Excel injection) em textos vindos do usuario.
            if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@"):
                valor = "'" + valor
            cel = ws.cell(row=r, column=c, value=valor)
            if (c - 1) in tabela.colunas_moeda and isinstance(valor, (int, float)):
                cel.number_format = '#,##0.00'
            larguras[c - 1] = max(larguras[c - 1], min(len(str(valor)), 50))
    for c, w in enumerate(larguras, start=1):
        ws.column_dimensions[get_column_letter(c)].width = w + 3
    ws.freeze_panes = ws.cell(row=linha_cab + 1, column=1)
    if tabela.linhas:
        ws.auto_filter.ref = f"A{linha_cab}:{get_column_letter(len(tabela.colunas))}{linha_cab + len(tabela.linhas)}"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def para_pdf(tabela: Tabela, *, gerado_por: str, gerado_em: datetime, filtros: Filtros, rotulos: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    if len(tabela.linhas) > MAX_LINHAS_PDF:
        raise RelatorioMuitoGrande(f"Mais de {MAX_LINHAS_PDF} linhas para PDF; use Excel ou restrinja o periodo.")

    estilos = getSampleStyleSheet()
    celula = ParagraphStyle("cel", parent=estilos["BodyText"], fontSize=6.5, leading=8)
    cab = ParagraphStyle("cab", parent=celula, textColor=colors.white, fontName="Helvetica-Bold")

    def fmt(c, v):
        if isinstance(v, float) and c in tabela.colunas_moeda:
            return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return "" if v is None else str(v)

    dados = [[Paragraph(n, cab) for n in tabela.colunas]]
    for linha in tabela.linhas:
        dados.append([Paragraph(_esc(fmt(c, v)), celula) for c, v in enumerate(linha)])

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
        title=tabela.titulo, author=gerado_por,
    )
    elementos = [Paragraph(tabela.titulo, estilos["Title"])]
    for texto in _linhas_cabecalho(tabela, gerado_por, gerado_em, filtros, rotulos):
        elementos.append(Paragraph(_esc(texto), estilos["Normal"]))
    elementos.append(Spacer(1, 6 * mm))
    if tabela.linhas:
        largura = landscape(A4)[0] - 20 * mm
        tbl = Table(dados, colWidths=[largura / len(tabela.colunas)] * len(tabela.colunas), repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8590C")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF4E6")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elementos.append(tbl)
    else:
        elementos.append(Paragraph("Nenhum registro para os filtros informados.", estilos["Normal"]))

    def rodape(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(10 * mm, 8 * mm, f"EletroGestor - gerado por {gerado_por}")
        canvas.drawRightString(landscape(A4)[0] - 10 * mm, 8 * mm, f"Pagina {d.page}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


RENDERIZADORES = {"xlsx": para_xlsx, "pdf": para_pdf}
CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
