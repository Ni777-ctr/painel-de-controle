"""Frota: veiculos e manutencoes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import requer_permissao
from app.models.frota import ManutencaoVeiculo, Veiculo
from app.models.usuario import Usuario
from app.schemas.frota import (
    ManutencaoCreate,
    ManutencaoOut,
    ManutencaoUpdate,
    VeiculoCreate,
    VeiculoOut,
    VeiculoUpdate,
)

router = APIRouter(tags=["Frota"])


def _normalizar_placa(placa: str) -> str:
    return placa.strip().upper().replace(" ", "")


def _veiculo_ou_404(db: Session, veiculo_id: int) -> Veiculo:
    v = db.get(Veiculo, veiculo_id)
    if not v:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Veiculo nao encontrado.")
    return v


@router.get("/veiculos", response_model=list[VeiculoOut])
def listar_veiculos(
    regional: str | None = None,
    status_veiculo: str | None = None,
    q: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("frota:read")),
):
    query = db.query(Veiculo)
    if regional:
        query = query.filter(Veiculo.regional == regional)
    if status_veiculo:
        query = query.filter(Veiculo.status == status_veiculo)
    if q:
        like = f"%{q.strip().upper()}%"
        query = query.filter(Veiculo.placa.like(like) | Veiculo.modelo.ilike(f"%{q.strip()}%"))
    return query.order_by(Veiculo.placa).all()


@router.get("/veiculos/{veiculo_id}", response_model=VeiculoOut)
def obter_veiculo(veiculo_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("frota:read"))):
    return _veiculo_ou_404(db, veiculo_id)


@router.post("/veiculos", response_model=VeiculoOut, status_code=status.HTTP_201_CREATED)
def criar_veiculo(dados: VeiculoCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("frota:write"))):
    placa = _normalizar_placa(dados.placa)
    if db.query(Veiculo).filter(Veiculo.placa == placa).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ja existe um veiculo com essa placa.")
    v = Veiculo(**{**dados.model_dump(), "placa": placa})
    db.add(v)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="veiculo_criado", entidade="veiculos", entidade_id=str(v.id), depois={"placa": placa})
    db.commit()
    db.refresh(v)
    return v


@router.patch("/veiculos/{veiculo_id}", response_model=VeiculoOut)
def atualizar_veiculo(
    veiculo_id: int, dados: VeiculoUpdate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("frota:write"))
):
    v = _veiculo_ou_404(db, veiculo_id)
    mudancas = dados.model_dump(exclude_unset=True)
    antes = {k: str(getattr(v, k)) for k in mudancas}
    for campo, valor in mudancas.items():
        setattr(v, campo, valor)
    registrar(
        db, usuario_id=ator.id, acao="veiculo_atualizado", entidade="veiculos", entidade_id=str(v.id),
        antes=antes, depois={k: str(x) for k, x in mudancas.items()},
    )
    db.commit()
    db.refresh(v)
    return v


@router.delete("/veiculos/{veiculo_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_veiculo(veiculo_id: int, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("frota:write"))):
    v = _veiculo_ou_404(db, veiculo_id)
    registrar(db, usuario_id=ator.id, acao="veiculo_excluido", entidade="veiculos", entidade_id=str(v.id), antes={"placa": v.placa})
    db.delete(v)
    db.commit()


# ---------- Manutencoes ----------
@router.get("/veiculos/{veiculo_id}/manutencoes", response_model=list[ManutencaoOut])
def listar_manutencoes(veiculo_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("frota:read"))):
    _veiculo_ou_404(db, veiculo_id)
    return (
        db.query(ManutencaoVeiculo)
        .filter(ManutencaoVeiculo.veiculo_id == veiculo_id)
        .order_by(ManutencaoVeiculo.data_prevista.desc())
        .all()
    )


@router.post("/veiculos/{veiculo_id}/manutencoes", response_model=ManutencaoOut, status_code=status.HTTP_201_CREATED)
def criar_manutencao(
    veiculo_id: int, dados: ManutencaoCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("frota:write"))
):
    _veiculo_ou_404(db, veiculo_id)
    m = ManutencaoVeiculo(veiculo_id=veiculo_id, **dados.model_dump())
    db.add(m)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="manutencao_criada", entidade="manutencoes_veiculo", entidade_id=str(m.id))
    db.commit()
    db.refresh(m)
    return m


@router.patch("/manutencoes/{manutencao_id}", response_model=ManutencaoOut)
def atualizar_manutencao(
    manutencao_id: int, dados: ManutencaoUpdate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("frota:write"))
):
    m = db.get(ManutencaoVeiculo, manutencao_id)
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manutencao nao encontrada.")
    mudancas = dados.model_dump(exclude_unset=True)
    for campo, valor in mudancas.items():
        setattr(m, campo, valor)
    # Concluir sem informar a data de realizacao assume hoje; ao concluir tambem atualiza o km do veiculo.
    if mudancas.get("status") == "Concluida":
        from datetime import date

        if not m.data_realizada:
            m.data_realizada = date.today()
        if m.km and m.km > m.veiculo.km_atual:
            m.veiculo.km_atual = m.km
    registrar(
        db, usuario_id=ator.id, acao="manutencao_atualizada", entidade="manutencoes_veiculo", entidade_id=str(m.id),
        depois={k: str(v) for k, v in mudancas.items()},
    )
    db.commit()
    db.refresh(m)
    return m
