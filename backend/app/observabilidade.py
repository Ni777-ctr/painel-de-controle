"""Logging estruturado (JSON opcional), request-id e integracao opcional com Sentry."""
import json
import logging
import sys
from datetime import datetime, timezone

from app.config import Settings
from app.contexto import obter_contexto


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        dados = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": obter_contexto().request_id,
        }
        extra = getattr(record, "extra_dados", None)
        if extra:
            dados.update(extra)
        if record.exc_info:
            dados["erro"] = self.formatException(record.exc_info)
        return json.dumps(dados, ensure_ascii=False)


class FormatoTexto(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = obter_contexto().request_id
        base = f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        return f"{base} [{rid}]" if rid else base


def configurar_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(FormatoJson() if settings.LOG_JSON else FormatoTexto())
    raiz = logging.getLogger()
    raiz.handlers = [handler]
    raiz.setLevel(settings.LOG_LEVEL.upper())
    # O access log proprio (middleware) substitui o do uvicorn.
    logging.getLogger("uvicorn.access").disabled = True


def iniciar_sentry(settings: Settings) -> bool:
    if not settings.SENTRY_DSN:
        return False
    try:
        import sentry_sdk  # type: ignore
    except ImportError:
        logging.getLogger("eletrogestor").warning("SENTRY_DSN definido, mas sentry-sdk nao esta instalado.")
        return False
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.0,
        send_default_pii=False,  # nunca enviar dados pessoais/credenciais ao Sentry
    )
    return True
