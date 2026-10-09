"""Notificacoes internas (sino) do usuario logado + processamento (cron/admin)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, requer_permissao
from app.models.notificacao import Notificacao
from app.models.usuario import Usuario
from app.schemas.notificacao import (
    ContagemNaoLidas,
    NotificacaoOut,
    PreferenciasNotificacao,
    ProcessamentoResultado,
)
from app.services import notificacao_service

router = APIRouter(prefix="/notificacoes", tags=["Notificacoes"])


@router.get("", response_model=list[NotificacaoOut])
def minhas_notificacoes(
    somente_nao_lidas: bool = False,
    modulo: str | None = None,
    nivel: str | None = None,
    limite: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    q = db.query(Notificacao).filter(Notificacao.usuario_id == usuario.id)
    if somente_nao_lidas:
        q = q.filter(Notificacao.lida.is_(False))
    if modulo:
        q = q.filter(Notificacao.modulo == modulo)
    if nivel:
        q = q.filter(Notificacao.nivel == nivel)
    return q.order_by(Notificacao.criado_em.desc(), Notificacao.id.desc()).offset(offset).limit(limite).all()


@router.get("/contagem", response_model=ContagemNaoLidas)
def contagem_nao_lidas(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    base = db.query(func.count(Notificacao.id)).filter(Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False))
    return ContagemNaoLidas(nao_lidas=base.scalar() or 0, criticas=base.filter(Notificacao.nivel == "critico").scalar() or 0)


@router.post("/marcar-todas-lidas", response_model=ContagemNaoLidas)
def marcar_todas_lidas(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    db.query(Notificacao).filter(Notificacao.usuario_id == usuario.id, Notificacao.lida.is_(False)).update(
        {Notificacao.lida: True, Notificacao.lida_em: datetime.now(timezone.utc)}
    )
    db.commit()
    return ContagemNaoLidas(nao_lidas=0, criticas=0)


@router.patch("/{notificacao_id}/lida", response_model=NotificacaoOut)
def marcar_lida(notificacao_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    # Filtra por usuario: ninguem le/altera notificacao de outra pessoa.
    n = db.query(Notificacao).filter(Notificacao.id == notificacao_id, Notificacao.usuario_id == usuario.id).first()
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notificacao nao encontrada.")
    if not n.lida:
        n.lida = True
        n.lida_em = datetime.now(timezone.utc)
        db.commit()
        db.refresh(n)
    return n


@router.get("/preferencias", response_model=PreferenciasNotificacao)
def obter_preferencias(usuario: Usuario = Depends(get_current_user)):
    return PreferenciasNotificacao(notificacoes_email=usuario.notificacoes_email)


@router.put("/preferencias", response_model=PreferenciasNotificacao)
def definir_preferencias(
    dados: PreferenciasNotificacao, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
):
    usuario.notificacoes_email = dados.notificacoes_email
    db.commit()
    return PreferenciasNotificacao(notificacoes_email=usuario.notificacoes_email)


@router.post("/processar", response_model=ProcessamentoResultado)
def processar(db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("notificacoes:processar"))):
    """Gera notificacoes novas a partir das pendencias e despacha e-mails. Mesma
    rotina do cron (`python -m app.jobs.processar_notificacoes`)."""
    return notificacao_service.processar(db, usuario_id=ator.id)
