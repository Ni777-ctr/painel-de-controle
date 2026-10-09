"""Painel inicial unificado para a gerencia: alertas e KPIs de todas as areas.

Usa a MESMA deteccao das notificacoes (services/pendencias_service.py). Cada
secao so aparece se o perfil tem a permissao de leitura do modulo."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import requer_permissao, tem_permissao
from app.models.automacao import Automacao, ExecucaoAutomacao
from app.models.financeiro import Fatura
from app.models.frota import Veiculo
from app.models.obra import Obra
from app.models.usuario import Usuario
from app.schemas.painel import AlertaPainel, PainelGerencia
from app.services import faturamento_service
from app.services.pendencias_service import AUTOMACAO_FALHA_JANELA_HORAS, coletar_pendencias

router = APIRouter(prefix="/painel", tags=["Painel unificado"])

LIMITE_ALERTAS = 100


@router.get("/gerencia", response_model=PainelGerencia)
def painel_gerencia(
    modulo: str | None = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(requer_permissao("dashboard:read")),
):
    hoje = date.today()
    visiveis = [p for p in coletar_pendencias(db, hoje) if tem_permissao(usuario, p.permissao)]
    if modulo:
        visiveis = [p for p in visiveis if p.modulo == modulo]
    por_tipo = Counter(p.tipo for p in visiveis)

    painel = PainelGerencia(
        gerado_em=datetime.now(timezone.utc).isoformat(),
        totais_por_nivel=dict(Counter(p.nivel for p in visiveis)),
        totais_por_modulo=dict(Counter(p.modulo for p in visiveis)),
        alertas=[AlertaPainel(**{k: getattr(p, k) for k in AlertaPainel.model_fields}) for p in visiveis[:LIMITE_ALERTAS]],
    )

    if tem_permissao(usuario, "financeiro:read"):
        resumo = faturamento_service.calcular_resumo(db)
        painel.faturamento = {
            "meta_mensal_nec": resumo.meta_mensal_nec,
            "nec_realizado_mes": resumo.nec_realizado_mes,
            "percentual_meta": resumo.percentual_meta,
            "faturas_atrasadas": resumo.faturas_atrasadas,
            "faturas_vencendo": por_tipo.get("fatura_vencendo", 0),
            "valor_pendente_total": resumo.valor_pendente_total,
            "medicoes_sem_fatura": por_tipo.get("medicao_sem_fatura", 0),
            "glosas_pendentes": por_tipo.get("glosa_pendente", 0),
        }
    if tem_permissao(usuario, "obras:read"):
        ativas = db.query(Obra).filter(Obra.status.notin_(("concluida", "cancelada")))
        painel.obras = {
            "total": db.query(func.count(Obra.id)).scalar() or 0,
            "em_execucao": db.query(func.count(Obra.id)).filter(Obra.status == "em_execucao").scalar() or 0,
            "ativas": ativas.count(),
            "atrasadas": por_tipo.get("obra_atrasada", 0),
            "prazo_proximo": por_tipo.get("obra_prazo_proximo", 0),
        }
    if tem_permissao(usuario, "frota:read"):
        painel.frota = {
            "veiculos": db.query(func.count(Veiculo.id)).scalar() or 0,
            "em_manutencao": db.query(func.count(Veiculo.id)).filter(Veiculo.status == "Manutencao").scalar() or 0,
            "manutencoes_atrasadas": por_tipo.get("manutencao_vencida", 0),
            "manutencoes_proximas": por_tipo.get("manutencao_proxima", 0),
            "documentos_vencidos": por_tipo.get("licenciamento_vencido", 0) + por_tipo.get("seguro_vencido", 0),
            "documentos_vencendo": por_tipo.get("licenciamento_vencendo", 0) + por_tipo.get("seguro_vencendo", 0),
            "exportacao_mensal_pendente": por_tipo.get("frota_exportacao_mensal", 0) > 0,
        }
    if tem_permissao(usuario, "programacao:read"):
        painel.programacao = {
            "programacoes_sem_fechamento": por_tipo.get("programacao_pendente", 0),
            "obras_sem_programacao": por_tipo.get("obra_sem_programacao", 0),
        }
    if tem_permissao(usuario, "automacoes:read"):
        painel.automacoes = {
            "ativas": db.query(func.count(Automacao.id)).filter(Automacao.ativo.is_(True)).scalar() or 0,
            "com_falha": por_tipo.get("automacao_falhou", 0),
            "janela_horas": AUTOMACAO_FALHA_JANELA_HORAS,
            "execucoes_falhas_na_janela": db.query(func.count(ExecucaoAutomacao.id))
            .filter(
                ExecucaoAutomacao.status == "falha",
                ExecucaoAutomacao.iniciado_em >= datetime.now(timezone.utc) - timedelta(hours=AUTOMACAO_FALHA_JANELA_HORAS),
            )
            .scalar()
            or 0,
        }
    if tem_permissao(usuario, "estoque:read"):
        painel.estoque = {"itens_abaixo_minimo": por_tipo.get("estoque_abaixo_minimo", 0)}
    return painel
