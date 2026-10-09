from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models.usuario import Perfil
from app.schemas.usuario import PerfilOut

router = APIRouter(prefix="/perfis", tags=["Perfis e Permissoes"])


@router.get("", response_model=list[PerfilOut])
def listar_perfis(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return db.query(Perfil).order_by(Perfil.categoria, Perfil.nome).all()
