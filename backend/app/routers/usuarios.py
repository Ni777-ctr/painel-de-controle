from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import requer_permissao
from app.models.usuario import RefreshToken, Usuario
from app.schemas.usuario import UsuarioOut, UsuarioUpdate
from app.security import hash_senha

router = APIRouter(prefix="/usuarios", tags=["Usuarios"])

# Criacao de usuario acontece via POST /auth/convite (o usuario define a
# propria senha). Este router cuida de listagem, edicao de perfil/dados e
# desativacao -- nunca de definir senha na criacao.


@router.get("", response_model=list[UsuarioOut])
def listar_usuarios(db: Session = Depends(get_db), _=Depends(requer_permissao("usuarios:read"))):
    return db.query(Usuario).order_by(Usuario.nome).all()


@router.patch("/{usuario_id}", response_model=UsuarioOut)
def atualizar_usuario(
    usuario_id: int,
    dados: UsuarioUpdate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("usuarios:write")),
):
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado.")

    dados_dict = dados.model_dump(exclude_unset=True)

    if "senha" in dados_dict:
        # Redefinicao administrativa (ex.: recuperacao de acesso). Forca a
        # troca no proximo login -- a senha definida pelo admin e sempre
        # tratada como temporaria. A criacao inicial da senha continua
        # sendo sempre por convite.
        usuario.senha_hash = hash_senha(dados_dict.pop("senha"))
        usuario.senha_alterada_em = datetime.now(timezone.utc)
        usuario.deve_trocar_senha = True
        registrar(db, usuario_id=ator.id, acao="senha_redefinida_por_admin", entidade="usuarios", entidade_id=str(usuario.id))

    if "perfil_id" in dados_dict and dados_dict["perfil_id"] != usuario.perfil_id:
        registrar(
            db,
            usuario_id=ator.id,
            acao="perfil_alterado",
            entidade="usuarios",
            entidade_id=str(usuario.id),
            antes={"perfil_id": usuario.perfil_id},
            depois={"perfil_id": dados_dict["perfil_id"]},
        )

    for campo, valor in dados_dict.items():
        setattr(usuario, campo, valor)

    db.commit()
    db.refresh(usuario)
    return usuario


@router.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def desativar_usuario(
    usuario_id: int, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("usuarios:write"))
):
    """Desligamento: desativa o usuario e revoga todas as sessoes ativas
    (refresh tokens). Como get_current_user e o /auth/refresh ja checam
    usuario.ativo em toda requisicao, o acesso e' cortado imediatamente;
    a revogacao explicita aqui e' so para deixar isso auditavel e explicito
    no banco (defesa em profundidade)."""
    usuario = db.get(Usuario, usuario_id)
    if not usuario:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado.")
    usuario.ativo = False

    sessoes_revogadas = (
        db.query(RefreshToken)
        .filter(RefreshToken.usuario_id == usuario.id, RefreshToken.revogado.is_(False))
        .update({RefreshToken.revogado: True})
    )

    registrar(db, usuario_id=ator.id, acao="usuario_desativado", entidade="usuarios", entidade_id=str(usuario.id))
    registrar(
        db,
        usuario_id=ator.id,
        acao="sessoes_revogadas",
        entidade="usuarios",
        entidade_id=str(usuario.id),
        depois={"quantidade": sessoes_revogadas},
    )
    db.commit()
