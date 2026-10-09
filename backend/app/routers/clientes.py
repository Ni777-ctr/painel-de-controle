from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.cliente import Cliente
from app.schemas.cliente import ClienteCreate, ClienteOut, ClienteUpdate

router = APIRouter(prefix="/clientes", tags=["Clientes"])


@router.get("", response_model=list[ClienteOut])
def listar_clientes(db: Session = Depends(get_db), _=Depends(requer_permissao("clientes:read"))):
    return db.query(Cliente).order_by(Cliente.nome).all()


@router.post("", response_model=ClienteOut, status_code=status.HTTP_201_CREATED)
def criar_cliente(dados: ClienteCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("clientes:write"))):
    cliente = Cliente(**dados.model_dump())
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.patch("/{cliente_id}", response_model=ClienteOut)
def atualizar_cliente(
    cliente_id: int, dados: ClienteUpdate, db: Session = Depends(get_db), _=Depends(requer_permissao("clientes:write"))
):
    cliente = db.get(Cliente, cliente_id)
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(cliente, campo, valor)
    db.commit()
    db.refresh(cliente)
    return cliente


@router.delete("/{cliente_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_cliente(cliente_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("clientes:write"))):
    cliente = db.get(Cliente, cliente_id)
    if not cliente:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente nao encontrado.")
    db.delete(cliente)
    db.commit()
