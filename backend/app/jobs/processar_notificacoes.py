"""Rotina agendada (cron): gera notificacoes e envia e-mails.

Uso:   python -m app.jobs.processar_notificacoes
Agende de hora em hora (Render Cron Job, ver render.yaml). E' idempotente."""
import json
import logging

from app.database import SessionLocal
from app.services import notificacao_service


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    db = SessionLocal()
    try:
        resultado = notificacao_service.processar(db, usuario_id=None)
        print(json.dumps(resultado))
        return 0
    except Exception:  # noqa: BLE001
        logging.exception("falha ao processar notificacoes")
        db.rollback()
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
