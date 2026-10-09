"""Ponto de entrada da API EletroGestor (FastAPI)."""
import logging

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import get_settings
from app.database import get_db
from app.middleware import ContextoSegurancaMiddleware
from app.observabilidade import configurar_logging, iniciar_sentry
from app.routers import (
    auditoria,
    auth,
    automacao,
    busca,
    clientes,
    compras,
    dashboard,
    equipes,
    estoque,
    faturamento,
    financeiro,
    frota,
    notificacoes,
    obras,
    painel,
    parametros,
    perfis,
    programacao,
    relatorios,
    supervisao,
    usuarios,
)

settings = get_settings()
configurar_logging(settings)
iniciar_sentry(settings)

# Em producao a API se recusa a subir com configuracao insegura (segredo padrao,
# banco local, CORS com localhost...). Falhar cedo e' melhor que rodar exposto.
_problemas = settings.validar_para_producao()
if _problemas:
    raise RuntimeError("Configuracao insegura para producao:\n - " + "\n - ".join(_problemas))

app = FastAPI(
    title="EletroGestor API",
    description="Backend REST do EletroGestor: usuarios/perfis, clientes, obras, programacao, "
    "estoque/compras, frota, faturamento/cobranca, painel unificado, notificacoes, busca global, "
    "relatorios, supervisao (empreiteiras e relatorios diarios de campo), auditoria, automacoes e parametros globais.",
    version="1.1.0",
    docs_url="/docs" if settings.DOCS_HABILITADO else None,
    redoc_url="/redoc" if settings.DOCS_HABILITADO else None,
    openapi_url="/openapi.json" if settings.DOCS_HABILITADO else None,
)

# API compartilhada; a interface central é servida por app.central.main:app,
# em outro processo, exclusivamente local.
from app.central.delegacao import router as governanca_router
app.include_router(governanca_router)

# Ordem: o ultimo add_middleware e' o mais externo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID", "X-Relatorio-Id", "X-Relatorio-Linhas"],
)
app.add_middleware(ContextoSegurancaMiddleware)
if settings.allowed_hosts_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)

for modulo in (
    auth, perfis, usuarios, clientes, equipes, obras, programacao, estoque, compras, financeiro,
    faturamento, frota, auditoria, parametros, automacao, dashboard, painel, notificacoes, busca, relatorios,
    supervisao,
):
    app.include_router(modulo.router)


@app.get("/", tags=["Saude"])
def raiz():
    return {"status": "ok", "servico": "EletroGestor API"}


@app.get("/saude", tags=["Saude"])
def saude():
    """Liveness: o processo esta de pe (nao toca no banco)."""
    return {"status": "ok"}


@app.get("/saude/pronto", tags=["Saude"])
def saude_pronto(db: Session = Depends(get_db)):
    """Readiness: o banco responde. Use no health check da plataforma/monitoramento."""
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("eletrogestor").error("readiness falhou: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Banco de dados indisponivel.") from exc
    return {"status": "ok", "banco": "ok"}
