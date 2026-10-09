from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.obra import Programacao
from app.schemas.obra import ProgramacaoCreate, ProgramacaoOut, ProgramacaoUpdate

router = APIRouter(prefix="/programacao", tags=["Programacao de Obras"])


@router.get("", response_model=list[ProgramacaoOut])
def listar_programacao(
    data_inicio: date_type | None = None,
    data_fim: date_type | None = None,
    equipe_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("programacao:read")),
):
    query = db.query(Programacao)
    if data_inicio:
        query = query.filter(Programacao.data >= data_inicio)
    if data_fim:
        query = query.filter(Programacao.data <= data_fim)
    if equipe_id:
        query = query.filter(Programacao.equipe_id == equipe_id)
    return query.order_by(Programacao.data).all()


@router.post("", response_model=ProgramacaoOut, status_code=status.HTTP_201_CREATED)
def criar_programacao(
    dados: ProgramacaoCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("programacao:write"))
):
    item = Programacao(**dados.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/{programacao_id}", response_model=ProgramacaoOut)
def atualizar_programacao(
    programacao_id: int,
    dados: ProgramacaoUpdate,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("programacao:write")),
):
    item = db.get(Programacao, programacao_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Programacao nao encontrada.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{programacao_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_programacao(
    programacao_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("programacao:write"))
):
    item = db.get(Programacao, programacao_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Programacao nao encontrada.")
    db.delete(item)
    db.commit()
