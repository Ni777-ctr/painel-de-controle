from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.equipe import Equipe, EquipeMembro
from app.schemas.equipe import EquipeCreate, EquipeMembroCreate, EquipeMembroOut, EquipeOut, EquipeUpdate

router = APIRouter(prefix="/equipes", tags=["Equipes"])


@router.get("", response_model=list[EquipeOut])
def listar_equipes(db: Session = Depends(get_db), _=Depends(requer_permissao("equipes:read"))):
    return db.query(Equipe).order_by(Equipe.nome).all()


@router.post("", response_model=EquipeOut, status_code=status.HTTP_201_CREATED)
def criar_equipe(dados: EquipeCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("equipes:write"))):
    equipe = Equipe(**dados.model_dump())
    db.add(equipe)
    db.commit()
    db.refresh(equipe)
    return equipe


@router.patch("/{equipe_id}", response_model=EquipeOut)
def atualizar_equipe(
    equipe_id: int, dados: EquipeUpdate, db: Session = Depends(get_db), _=Depends(requer_permissao("equipes:write"))
):
    equipe = db.get(Equipe, equipe_id)
    if not equipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipe nao encontrada.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(equipe, campo, valor)
    db.commit()
    db.refresh(equipe)
    return equipe


@router.post("/{equipe_id}/membros", response_model=EquipeMembroOut, status_code=status.HTTP_201_CREATED)
def adicionar_membro(
    equipe_id: int,
    dados: EquipeMembroCreate,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("equipes:write")),
):
    if not db.get(Equipe, equipe_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Equipe nao encontrada.")
    membro = EquipeMembro(equipe_id=equipe_id, **dados.model_dump())
    db.add(membro)
    db.commit()
    db.refresh(membro)
    return membro


@router.delete("/{equipe_id}/membros/{membro_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_membro(
    equipe_id: int, membro_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("equipes:write"))
):
    membro = db.query(EquipeMembro).filter(EquipeMembro.id == membro_id, EquipeMembro.equipe_id == equipe_id).first()
    if not membro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro nao encontrado.")
    db.delete(membro)
    db.commit()
