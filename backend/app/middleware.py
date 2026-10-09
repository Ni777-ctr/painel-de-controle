"""Middlewares de producao: contexto da requisicao (IP/UA/request-id), redirect
HTTPS, cabecalhos de seguranca e access log."""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.config import get_settings
from app.contexto import ContextoRequisicao, definir_contexto, restaurar_contexto

logger = logging.getLogger("eletrogestor.acesso")

CAMINHOS_DOCS = ("/docs", "/redoc", "/openapi.json")
CAMINHOS_SEM_REDIRECT = ("/saude",)


def ip_do_cliente(request: Request, confiar_proxy: bool) -> str | None:
    if confiar_proxy:
        # Cloudflare informa o IP real nesse cabecalho; senao, usa o primeiro IP do X-Forwarded-For.
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()[:45]
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


class ContextoSegurancaMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        s = get_settings()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request_id = "".join(ch for ch in request_id if ch.isalnum() or ch in "-_")[:40] or uuid.uuid4().hex[:16]
        ip = ip_do_cliente(request, s.TRUST_PROXY)
        token = definir_contexto(ContextoRequisicao(ip=ip, user_agent=request.headers.get("user-agent"), request_id=request_id))
        inicio = time.perf_counter()

        try:
            if s.FORCE_HTTPS and not request.url.path.startswith(CAMINHOS_SEM_REDIRECT):
                proto = request.headers.get("x-forwarded-proto", request.url.scheme) if s.TRUST_PROXY else request.url.scheme
                if proto != "https":
                    destino = request.url.replace(scheme="https")
                    return RedirectResponse(str(destino), status_code=308)

            try:
                response: Response = await call_next(request)
            except Exception:
                logger.exception("erro nao tratado em %s %s", request.method, request.url.path)
                raise

            self._cabecalhos(response, request, s)
            duracao_ms = round((time.perf_counter() - inicio) * 1000, 1)
            if request.url.path not in ("/saude", "/saude/pronto"):
                logger.info(
                    "%s %s -> %s (%sms)", request.method, request.url.path, response.status_code, duracao_ms,
                    extra={"extra_dados": {"metodo": request.method, "caminho": request.url.path, "status": response.status_code, "ms": duracao_ms, "ip": ip}},
                )
            return response
        finally:
            restaurar_contexto(token)

    @staticmethod
    def _cabecalhos(response: Response, request: Request, s) -> None:
        h = response.headers
        h["X-Request-ID"] = ""  # sobrescrito abaixo
        from app.contexto import obter_contexto

        h["X-Request-ID"] = obter_contexto().request_id or ""
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if s.FORCE_HTTPS or s.em_producao:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if not request.url.path.startswith(CAMINHOS_DOCS):
            h["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.url.path.startswith("/auth"):
            h["Cache-Control"] = "no-store"
