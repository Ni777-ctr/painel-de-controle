"""API compartilhada para convites delegados; não serve o site administrativo."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_current_user
from app.models.usuario import Perfil
from app.central.models import ContaCentral, Vinculo, Limite
from app.central.policy import central_admin, deny, mutation
from app.central.main import UserInput, save_user_transaction

router = APIRouter(prefix='/governanca', tags=['Governança'])

@router.post('/convites', status_code=201)
def invite(data: UserInput, actor=Depends(get_current_user), db: Session = Depends(get_db)):
    with mutation(db):
        if not central_admin(actor):
            account = db.get(ContaCentral, actor.id)
            hierarchy = {'dono': {'gerente'}, 'gerente': {'coordenador', 'colaborador'}, 'coordenador': {'colaborador'}, 'colaborador': set()}
            if not account or data.cargo not in hierarchy[account.cargo]:
                deny(db, actor, 'Seu cargo não pode cadastrar este cargo.')
            limit = db.get(Limite, (account.cargo, 0))
            if not limit or not limit.pode_cadastrar:
                deny(db, actor, 'Delegação de cadastro não habilitada.')
            profile = db.get(Perfil, data.perfil_id)
            if not profile or '*' in profile.permissoes or data.perfil_id == 'administrador':
                deny(db, actor, 'Delegação não pode conceder um perfil privilegiado.')
            if not data.vinculos:
                deny(db, actor, 'Cadastro delegado exige um setor autorizado.')
            for link in data.vinculos:
                mine = db.query(Vinculo).filter_by(usuario_id=actor.id, setor_id=link.setor_id).first()
                if not mine or link.cargo != data.cargo or data.cargo not in hierarchy[mine.cargo]:
                    deny(db, actor, 'Setor ou cargo fora do seu escopo de delegação.')
                if mine.cargo == 'coordenador' and link.responsavel_id != actor.id:
                    deny(db, actor, 'Coordenador só cadastra colaboradores de sua responsabilidade.')
                allowed_parents = {actor.id}
                # A equipe é calculada no servidor, dentro do mesmo setor.
                changed = True
                while changed:
                    changed = False
                    for candidate in db.query(Vinculo).filter_by(setor_id=link.setor_id):
                        if candidate.responsavel_id in allowed_parents and candidate.usuario_id not in allowed_parents:
                            allowed_parents.add(candidate.usuario_id)
                            changed = True
                if link.responsavel_id not in allowed_parents:
                    deny(db, actor, 'Responsável fora da sua equipe autorizada.')
        try:
            return save_user_transaction(db, actor, 0, data)
        except HTTPException as error:
            deny(db, actor, str(error.detail))

@router.get('/contextos/{sid}/permissoes')
def permissions(sid: int, actor=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.central.main import catalog
    from app.central.policy import effective
    if not db.query(Vinculo).filter_by(usuario_id=actor.id, setor_id=sid).first():
        deny(db, actor, 'Usuário não vinculado ao setor solicitado.')
    return [{'permissao': k, 'permitido': effective(db, actor, sid, k)[0], 'origem': effective(db, actor, sid, k)[1]} for k in catalog(db)]
