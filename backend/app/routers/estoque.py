from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.estoque import Almoxarifado, EstoqueItem, Material
from app.models.usuario import Usuario
from app.schemas.estoque import (
    AlmoxarifadoCreate,
    AlmoxarifadoOut,
    EstoqueItemOut,
    EstoqueItemUpsert,
    MaterialCreate,
    MaterialOut,
    MaterialUpdate,
    MovimentacaoEstoqueCreate,
    MovimentacaoEstoqueOut,
)
from app.services.estoque_service import aplicar_movimentacao

router = APIRouter(tags=["Estoque e Almoxarifado"])


@router.get("/materiais", response_model=list[MaterialOut])
def listar_materiais(db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:read"))):
    return db.query(Material).order_by(Material.nome).all()


@router.post("/materiais", response_model=MaterialOut, status_code=status.HTTP_201_CREATED)
def criar_material(dados: MaterialCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:write"))):
    material = Material(**dados.model_dump())
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


@router.patch("/materiais/{material_id}", response_model=MaterialOut)
def atualizar_material(
    material_id: int, dados: MaterialUpdate, db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:write"))
):
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Material nao encontrado.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(material, campo, valor)
    db.commit()
    db.refresh(material)
    return material


@router.get("/almoxarifados", response_model=list[AlmoxarifadoOut])
def listar_almoxarifados(db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:read"))):
    return db.query(Almoxarifado).order_by(Almoxarifado.nome).all()


@router.post("/almoxarifados", response_model=AlmoxarifadoOut, status_code=status.HTTP_201_CREATED)
def criar_almoxarifado(
    dados: AlmoxarifadoCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:write"))
):
    almox = Almoxarifado(**dados.model_dump())
    db.add(almox)
    db.commit()
    db.refresh(almox)
    return almox


@router.get("/estoque", response_model=list[EstoqueItemOut])
def listar_estoque(
    almoxarifado_id: int | None = None,
    material_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("estoque:read")),
):
    query = db.query(EstoqueItem)
    if almoxarifado_id:
        query = query.filter(EstoqueItem.almoxarifado_id == almoxarifado_id)
    if material_id:
        query = query.filter(EstoqueItem.material_id == material_id)
    return query.all()


@router.put("/estoque", response_model=EstoqueItemOut)
def definir_saldo_estoque(
    dados: EstoqueItemUpsert, db: Session = Depends(get_db), _=Depends(requer_permissao("estoque:write"))
):
    """Cria ou atualiza o saldo de um material em um almoxarifado (upsert)."""
    item = (
        db.query(EstoqueItem)
        .filter(
            EstoqueItem.almoxarifado_id == dados.almoxarifado_id,
            EstoqueItem.material_id == dados.material_id,
        )
        .first()
    )
    if item:
        item.quantidade = dados.quantidade
    else:
        item = EstoqueItem(**dados.model_dump())
        db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/estoque/movimentacoes", response_model=list[MovimentacaoEstoqueOut])
def listar_movimentacoes(
    obra_id: int | None = None,
    material_id: int | None = None,
    almoxarifado_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("estoque:read")),
):
    query = db.query(MovimentacaoEstoque)
    if obra_id:
        query = query.filter(MovimentacaoEstoque.obra_id == obra_id)
    if material_id:
        query = query.filter(MovimentacaoEstoque.material_id == material_id)
    if almoxarifado_id:
        query = query.filter(MovimentacaoEstoque.almoxarifado_id == almoxarifado_id)
    return query.order_by(MovimentacaoEstoque.criado_em.desc()).all()


@router.post("/estoque/movimentacoes", response_model=MovimentacaoEstoqueOut, status_code=status.HTTP_201_CREATED)
def registrar_movimentacao(
    dados: MovimentacaoEstoqueCreate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("estoque:write")),
):
    """Registra entrada/saida de material e atualiza o saldo em EstoqueItem.
    Uma saida com obra_id e o jeito de registrar consumo de material por obra
    (usado no resumo agregado de GET /obras/{id}/resumo e valoriza o custo
    realizado da obra pelo custo medio do material)."""
    movimentacao = aplicar_movimentacao(db, usuario_id=ator.id, **dados.model_dump())
    db.commit()
    db.refresh(movimentacao)
    return movimentacao
