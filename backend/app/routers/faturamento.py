"""Estrutura de faturamento/medicao para alimentar a tela de acompanhamento
financeiro do frontend (ainda mockada). Reaproveita Obra/Medicao/Fatura --
nao duplica nenhuma entidade."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import requer_permissao
from app.models.financeiro import AlertaFinanceiro
from app.models.usuario import Usuario
from app.schemas.financeiro import (
    AlertaFinanceiroOut,
    ConfiguracaoFaturamento,
    GerarAlertasResponse,
    ItemCarteira,
    ItemEvolucaoMensal,
    ResumoFaturamento,
)
from app.services import faturamento_service

router = APIRouter(prefix="/faturamento", tags=["Faturamento (resumo, carteira, alertas)"])


# ---------- Configuracao ----------
@router.get("/configuracao", response_model=ConfiguracaoFaturamento)
def obter_configuracao(db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    return faturamento_service.obter_configuracao(db)


@router.put("/configuracao", response_model=ConfiguracaoFaturamento)
def definir_configuracao(
    dados: ConfiguracaoFaturamento,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("financeiro:write")),
):
    resultado = faturamento_service.definir_configuracao(db, dados)
    registrar(db, usuario_id=ator.id, acao="faturamento_configuracao_alterada", entidade="parametros_globais", entidade_id="faturamento_configuracao", depois=dados.model_dump())
    db.commit()
    return resultado


# ---------- Resumo / evolucao ----------
@router.get("/resumo", response_model=ResumoFaturamento)
def resumo(db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    return faturamento_service.calcular_resumo(db)


@router.get("/evolucao-mensal", response_model=list[ItemEvolucaoMensal])
def evolucao_mensal(meses: int = 6, db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    if meses < 1 or meses > 24:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="meses deve estar entre 1 e 24.")
    return faturamento_service.calcular_evolucao_mensal(db, meses=meses)


# ---------- Carteira de obras/contratos ----------
@router.get("/carteira", response_model=list[ItemCarteira])
def carteira(db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    return faturamento_service.calcular_carteira(db)


# ---------- Alertas financeiros ----------
@router.get("/alertas", response_model=list[AlertaFinanceiroOut])
def listar_alertas(
    tipo: str | None = None,
    resolvido: bool | None = False,
    obra_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("financeiro:read")),
):
    query = db.query(AlertaFinanceiro)
    if tipo:
        query = query.filter(AlertaFinanceiro.tipo == tipo)
    if resolvido is not None:
        query = query.filter(AlertaFinanceiro.resolvido == resolvido)
    if obra_id:
        query = query.filter(AlertaFinanceiro.obra_id == obra_id)
    return query.order_by(AlertaFinanceiro.criado_em.desc()).all()


@router.post("/alertas/gerar", response_model=GerarAlertasResponse)
def gerar_alertas(db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))):
    """Recalcula os alertas com base no estado atual (saldo de contrato,
    vencimentos, medicoes sem fatura, faturas vencidas, glosas pendentes).
    NAO envia e-mail real -- apenas persiste e audita uma simulacao de
    notificacao com os e-mails configurados."""
    novos, ativos = faturamento_service.gerar_alertas(db, ator.id)
    db.commit()
    return GerarAlertasResponse(total_ativos=len(ativos), novos=novos, alertas=ativos)


@router.patch("/alertas/{alerta_id}/resolver", response_model=AlertaFinanceiroOut)
def resolver_alerta(
    alerta_id: int, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    alerta = db.get(AlertaFinanceiro, alerta_id)
    if not alerta:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alerta nao encontrado.")
    alerta.resolvido = True
    alerta.resolvido_em = datetime.now(timezone.utc)
    alerta.resolvido_por_usuario_id = ator.id
    registrar(db, usuario_id=ator.id, acao="alerta_financeiro_resolvido", entidade="alertas_financeiros", entidade_id=str(alerta.id))
    db.commit()
    db.refresh(alerta)
    return alerta
