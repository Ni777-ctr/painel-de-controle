"""Automacoes: cadastro generico + o dominio de automacao de rede eletrica
(painel, self-healing/FLISR, subestacoes, vegetacao) ja consumido pelo
frontend em src/lib/api.ts."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import requer_permissao
from app.models.automacao import Automacao, EventoSelfHealing, ExecucaoAutomacao, LeituraSubestacao, PontoVegetacao, Subestacao
from app.schemas.automacao import (
    AutomacaoCreate,
    AutomacaoOut,
    AutomacaoUpdate,
    ExecucaoAutomacaoCreate,
    ExecucaoAutomacaoOut,
    IndicadoresSelfHealing,
    PainelAutomacao,
    PontoVegetacaoOut,
    StatusSubestacao,
)

router = APIRouter(tags=["Automacoes"])


# ---------- Automacoes genericas (configuraveis) ----------
@router.get("/automacoes", response_model=list[AutomacaoOut])
def listar_automacoes(db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:read"))):
    return db.query(Automacao).order_by(Automacao.nome).all()


@router.post("/automacoes", response_model=AutomacaoOut, status_code=status.HTTP_201_CREATED)
def criar_automacao(
    dados: AutomacaoCreate, db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:write"))
):
    automacao = Automacao(**dados.model_dump())
    db.add(automacao)
    db.commit()
    db.refresh(automacao)
    return automacao


@router.patch("/automacoes/{automacao_id}", response_model=AutomacaoOut)
def atualizar_automacao(
    automacao_id: int,
    dados: AutomacaoUpdate,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("automacoes:write")),
):
    automacao = db.get(Automacao, automacao_id)
    if not automacao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automacao nao encontrada.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(automacao, campo, valor)
    db.commit()
    db.refresh(automacao)
    return automacao


# ---------- Execucoes (reportadas pelos bots) ----------
@router.post("/automacoes/{automacao_id}/execucoes", response_model=ExecucaoAutomacaoOut, status_code=status.HTTP_201_CREATED)
def registrar_execucao(
    automacao_id: int,
    dados: ExecucaoAutomacaoCreate,
    db: Session = Depends(get_db),
    ator=Depends(requer_permissao("automacoes:write")),
):
    """O bot/automacao reporta o resultado de cada execucao. Falhas aparecem no
    painel unificado e geram notificacao para quem tem automacoes:read."""
    automacao = db.get(Automacao, automacao_id)
    if not automacao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Automacao nao encontrada.")
    execucao = ExecucaoAutomacao(automacao_id=automacao_id, **dados.model_dump())
    db.add(execucao)
    db.flush()
    registrar(
        db, usuario_id=ator.id, acao=f"automacao_execucao_{dados.status}", entidade="automacoes",
        entidade_id=str(automacao_id), depois={"mensagem": (dados.mensagem or "")[:200]}, bot=automacao.nome[:80],
    )
    db.commit()
    db.refresh(execucao)
    return execucao


@router.get("/automacoes/{automacao_id}/execucoes", response_model=list[ExecucaoAutomacaoOut])
def listar_execucoes(
    automacao_id: int,
    status_execucao: str | None = None,
    limite: int = 50,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("automacoes:read")),
):
    q = db.query(ExecucaoAutomacao).filter(ExecucaoAutomacao.automacao_id == automacao_id)
    if status_execucao:
        q = q.filter(ExecucaoAutomacao.status == status_execucao)
    return q.order_by(ExecucaoAutomacao.iniciado_em.desc(), ExecucaoAutomacao.id.desc()).limit(min(limite, 200)).all()


# ---------- GET /automacao/painel ----------
@router.get("/automacao/painel", response_model=PainelAutomacao)
def painel_automacao(db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:read"))):
    total_eventos = db.query(func.count(EventoSelfHealing.id)).scalar() or 0
    resolvidos = (
        db.query(func.count(EventoSelfHealing.id)).filter(EventoSelfHealing.resolvido_automaticamente.is_(True)).scalar()
        or 0
    )
    percentual = round((resolvidos / total_eventos) * 100, 2) if total_eventos else 0.0

    return PainelAutomacao(
        dispositivos_automacao=db.query(func.count(Subestacao.id)).scalar() or 0,
        subestacoes_digitais=db.query(func.count(Subestacao.id)).filter(Subestacao.operacao_remota_ativa.is_(True)).scalar()
        or 0,
        eventos_self_healing=total_eventos,
        percentual_restabelecimento_automatico=percentual,
        pontos_criticos_vegetacao_abertos=db.query(func.count(PontoVegetacao.id)).filter(PontoVegetacao.resolvido.is_(False)).scalar()
        or 0,
    )


# ---------- GET /automacao/self-healing/indicadores ----------
@router.get("/automacao/self-healing/indicadores", response_model=IndicadoresSelfHealing)
def indicadores_self_healing(db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:read"))):
    eventos = db.query(EventoSelfHealing).all()
    total = len(eventos)
    resolvidos = [e for e in eventos if e.resolvido_automaticamente]
    tempos = [e.tempo_restauracao_segundos for e in resolvidos if e.tempo_restauracao_segundos is not None]

    return IndicadoresSelfHealing(
        total_eventos=total,
        resolvidos_automaticamente=len(resolvidos),
        percentual_resolucao_automatica=round((len(resolvidos) / total) * 100, 2) if total else 0.0,
        tempo_medio_restauracao_segundos=(sum(tempos) / len(tempos)) if tempos else None,
    )


# ---------- GET /subestacoes/{id}/status ----------
@router.get("/subestacoes/{subestacao_id}/status", response_model=StatusSubestacao)
def status_subestacao(
    subestacao_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:read"))
):
    subestacao = db.get(Subestacao, subestacao_id)
    if not subestacao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subestacao nao encontrada.")

    ultima_leitura = subestacao.leituras[0] if subestacao.leituras else None
    alertas = []
    if ultima_leitura and ultima_leitura.alerta_gerado:
        alertas.append("Leitura fora dos parametros normais")

    return StatusSubestacao(
        subestacao=subestacao.nome,
        operacao_remota_ativa=subestacao.operacao_remota_ativa,
        ultima_leitura=ultima_leitura,
        alertas_ativos=alertas,
    )


# ---------- GET /vegetacao/pontos-criticos ----------
@router.get("/vegetacao/pontos-criticos", response_model=list[PontoVegetacaoOut])
def pontos_criticos_vegetacao(db: Session = Depends(get_db), _=Depends(requer_permissao("automacoes:read"))):
    return db.query(PontoVegetacao).filter(PontoVegetacao.resolvido.is_(False)).all()
