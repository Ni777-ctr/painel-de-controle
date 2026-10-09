from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.estoque import EstoqueItem, Material
from app.models.financeiro import Fatura
from app.models.obra import Obra
from app.schemas.automacao import (
    DashboardFaturamento,
    DashboardMateriais,
    DashboardObras,
    DashboardOut,
    DashboardProdutividadeEquipe,
)

router = APIRouter(tags=["Dashboard"])

STATUS_PENDENTES = ("proposta", "contratada")


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(
    regional: str | None = None, db: Session = Depends(get_db), _=Depends(requer_permissao("dashboard:read"))
):
    query = db.query(Obra)
    if regional:
        query = query.filter(Obra.regional == regional)
    obras = query.all()

    total_itens = db.query(func.count(Material.id)).scalar() or 0
    saldo_total = db.query(func.coalesce(func.sum(EstoqueItem.quantidade), 0)).scalar() or 0
    pendencias_faturas = db.query(func.count(Fatura.id)).filter(Fatura.status != "Paga").scalar() or 0

    produtividade: dict[str, dict[str, int]] = {}
    for obra in obras:
        nome_equipe = obra.equipe.nome if obra.equipe else "Sem equipe"
        registro = produtividade.setdefault(nome_equipe, {"total": 0, "concluidas": 0})
        registro["total"] += 1
        if obra.status == "concluida":
            registro["concluidas"] += 1

    return DashboardOut(
        obras=DashboardObras(
            total=len(obras),
            concluidas=len([o for o in obras if o.status == "concluida"]),
            pendentes=len([o for o in obras if o.status in STATUS_PENDENTES]),
            em_execucao=len([o for o in obras if o.status == "em_execucao"]),
            # nao ha um modulo de inventario dedicado ainda; mantido em 0 por enquanto.
            aguardando_inventario=0,
        ),
        materiais=DashboardMateriais(total_itens=total_itens, saldo_total=float(saldo_total)),
        produtividade_por_equipe=[
            DashboardProdutividadeEquipe(equipe=nome, total=dados["total"], concluidas=dados["concluidas"])
            for nome, dados in produtividade.items()
        ],
        faturamento=DashboardFaturamento(pendencias_abertas=pendencias_faturas),
    )


@router.get("/relatorios/resumo-diario")
def resumo_diario(db: Session = Depends(get_db), _=Depends(requer_permissao("dashboard:read"))):
    """Resumo textual/numerico do dia, usado nos relatorios automaticos."""
    total_obras = db.query(func.count(Obra.id)).scalar() or 0
    obras_em_execucao = db.query(func.count(Obra.id)).filter(Obra.status == "em_execucao").scalar() or 0
    faturas_atrasadas = db.query(func.count(Fatura.id)).filter(Fatura.status == "Atrasada").scalar() or 0
    return {
        "total_obras": total_obras,
        "obras_em_execucao": obras_em_execucao,
        "faturas_atrasadas": faturas_atrasadas,
    }
