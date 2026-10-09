"""Pesquisa global: obra, contrato (= codigo WL da obra), veiculo, cliente,
fatura, medicao, material, fornecedor e equipe numa unica chamada.

Respeita o RBAC: so busca nos dominios que o perfil pode ler."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.deps import get_current_user, tem_permissao
from app.models.cliente import Cliente
from app.models.compras import Fornecedor
from app.models.equipe import Equipe
from app.models.estoque import Material
from app.models.financeiro import Fatura, Medicao
from app.models.frota import Veiculo
from app.models.obra import Obra
from app.models.usuario import Usuario
from app.schemas.busca import RespostaBusca, ResultadoBusca

router = APIRouter(tags=["Busca global"])

TIPOS = ("obra", "cliente", "veiculo", "fatura", "medicao", "material", "fornecedor", "equipe")


def _like(termo: str) -> str:
    """Escapa % _ \\ para o termo ser tratado literalmente."""
    esc = termo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


@router.get("/busca", response_model=RespostaBusca)
def busca_global(
    q: str = Query(..., min_length=2, max_length=80, description="Termo (codigo, nome, placa, numero...)"),
    tipos: str | None = Query(None, description="Lista separada por virgula para restringir (ex.: obra,veiculo)"),
    regional: str | None = None,
    limite_por_tipo: int = Query(8, ge=1, le=25),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    termo = q.strip()
    padrao = _like(termo)
    escolhidos = {t.strip() for t in tipos.split(",")} & set(TIPOS) if tipos else set(TIPOS)
    saida: list[ResultadoBusca] = []

    def ilike(col):
        return col.ilike(padrao, escape="\\")

    if "obra" in escolhidos and tem_permissao(usuario, "obras:read"):
        query = db.query(Obra).options(joinedload(Obra.cliente)).filter(
            ilike(Obra.wl) | ilike(func_coalesce(Obra.descricao))
        )
        if regional:
            query = query.filter(Obra.regional == regional)
        for o in query.order_by(Obra.wl).limit(limite_por_tipo).all():
            sub = " - ".join(x for x in (o.descricao, o.cliente.nome if o.cliente else None, o.status) if x)
            saida.append(ResultadoBusca(tipo="obra", id=o.id, titulo=o.wl, subtitulo=sub, rota=f"/obras/{o.id}"))

    if "cliente" in escolhidos and tem_permissao(usuario, "clientes:read"):
        for c in (
            db.query(Cliente)
            .filter(ilike(Cliente.nome) | ilike(func_coalesce(Cliente.documento)))
            .order_by(Cliente.nome)
            .limit(limite_por_tipo)
            .all()
        ):
            saida.append(ResultadoBusca(tipo="cliente", id=c.id, titulo=c.nome, subtitulo=c.documento, rota=f"/clientes/{c.id}"))

    if "veiculo" in escolhidos and tem_permissao(usuario, "frota:read"):
        query = db.query(Veiculo).filter(ilike(Veiculo.placa) | ilike(Veiculo.modelo))
        if regional:
            query = query.filter(Veiculo.regional == regional)
        for v in query.order_by(Veiculo.placa).limit(limite_por_tipo).all():
            saida.append(ResultadoBusca(tipo="veiculo", id=v.id, titulo=v.placa, subtitulo=f"{v.modelo} - {v.status}", rota=f"/frota/{v.id}"))

    if "fatura" in escolhidos and tem_permissao(usuario, "financeiro:read"):
        query = db.query(Fatura).join(Obra).options(joinedload(Fatura.obra)).filter(
            ilike(cast(Fatura.id, String)) | ilike(Obra.wl)
        )
        if regional:
            query = query.filter(Obra.regional == regional)
        for f in query.order_by(Fatura.id.desc()).limit(limite_por_tipo).all():
            saida.append(ResultadoBusca(
                tipo="fatura", id=f.id, titulo=f"Fatura #{f.id}",
                subtitulo=f"{f.obra.wl} - R$ {float(f.valor):.2f} - {f.status}", rota=f"/faturamento/faturas/{f.id}",
            ))

    if "medicao" in escolhidos and tem_permissao(usuario, "financeiro:read"):
        query = db.query(Medicao).join(Obra).options(joinedload(Medicao.obra)).filter(
            ilike(cast(Medicao.id, String)) | ilike(Obra.wl)
        )
        if regional:
            query = query.filter(Obra.regional == regional)
        for m in query.order_by(Medicao.id.desc()).limit(limite_por_tipo).all():
            saida.append(ResultadoBusca(
                tipo="medicao", id=m.id, titulo=f"Medicao #{m.id}", subtitulo=f"{m.obra.wl} - {m.status}",
                rota=f"/faturamento/medicoes/{m.id}",
            ))

    if "material" in escolhidos and tem_permissao(usuario, "estoque:read"):
        for m in (
            db.query(Material).filter(ilike(Material.nome) | ilike(func_coalesce(Material.codigo))).order_by(Material.nome).limit(limite_por_tipo).all()
        ):
            saida.append(ResultadoBusca(tipo="material", id=m.id, titulo=m.nome, subtitulo=m.codigo, rota=f"/estoque/materiais/{m.id}"))

    if "fornecedor" in escolhidos and tem_permissao(usuario, "compras:read"):
        for fo in db.query(Fornecedor).filter(ilike(Fornecedor.nome)).order_by(Fornecedor.nome).limit(limite_por_tipo).all():
            saida.append(ResultadoBusca(tipo="fornecedor", id=fo.id, titulo=fo.nome, subtitulo=fo.contato, rota=f"/compras/fornecedores/{fo.id}"))

    if "equipe" in escolhidos and tem_permissao(usuario, "equipes:read"):
        for e in db.query(Equipe).filter(ilike(Equipe.nome)).order_by(Equipe.nome).limit(limite_por_tipo).all():
            saida.append(ResultadoBusca(tipo="equipe", id=e.id, titulo=e.nome, subtitulo="ativa" if e.ativa else "inativa", rota=f"/equipes/{e.id}"))

    return RespostaBusca(termo=termo, total=len(saida), resultados=saida)


def func_coalesce(col):
    """coalesce(col, '') para ilike nao devolver NULL em colunas anulaveis."""
    from sqlalchemy import func

    return func.coalesce(col, "")
