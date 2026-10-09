from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao
from app.models.parametro import ParametroGlobal
from app.schemas.parametro import ParametroOut, ParametroUpsert

router = APIRouter(prefix="/parametros", tags=["Parametros Globais"])


@router.get("", response_model=list[ParametroOut])
def listar_parametros(db: Session = Depends(get_db), _=Depends(requer_permissao("parametros:read"))):
    return db.query(ParametroGlobal).order_by(ParametroGlobal.chave).all()


@router.get("/{chave}", response_model=ParametroOut)
def obter_parametro(chave: str, db: Session = Depends(get_db), _=Depends(requer_permissao("parametros:read"))):
    parametro = db.get(ParametroGlobal, chave)
    if not parametro:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parametro nao encontrado.")
    return parametro


@router.put("/{chave}", response_model=ParametroOut)
def definir_parametro(
    chave: str, dados: ParametroUpsert, db: Session = Depends(get_db), _=Depends(requer_permissao("parametros:write"))
):
    """Cria ou atualiza um parametro global (upsert por chave)."""
    parametro = db.get(ParametroGlobal, chave)
    if parametro:
        parametro.valor = dados.valor
        parametro.descricao = dados.descricao
    else:
        parametro = ParametroGlobal(chave=chave, valor=dados.valor, descricao=dados.descricao)
        db.add(parametro)
    db.commit()
    db.refresh(parametro)
    return parametro
