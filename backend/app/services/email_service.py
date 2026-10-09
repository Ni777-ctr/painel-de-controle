"""Envio de e-mail via SMTP (o Resend tambem expoe SMTP: host smtp.resend.com,
usuario 'resend', senha = API key). Isolado aqui para ser trocado/mockado."""
import smtplib
import ssl
from email.message import EmailMessage

from app.config import get_settings


class EmailNaoConfigurado(Exception):
    pass


def email_disponivel() -> bool:
    s = get_settings()
    return bool(s.EMAIL_HABILITADO and s.SMTP_HOST)


def enviar_email(destinatario: str, assunto: str, corpo_texto: str, corpo_html: str | None = None) -> None:
    s = get_settings()
    if not email_disponivel():
        raise EmailNaoConfigurado("EMAIL_HABILITADO/SMTP_HOST nao configurados.")

    msg = EmailMessage()
    msg["From"] = s.EMAIL_REMETENTE
    msg["To"] = destinatario
    msg["Subject"] = assunto
    msg.set_content(corpo_texto)
    if corpo_html:
        msg.add_alternative(corpo_html, subtype="html")

    contexto = ssl.create_default_context()
    if s.SMTP_USAR_SSL:
        servidor = smtplib.SMTP_SSL(s.SMTP_HOST, s.SMTP_PORT, timeout=20, context=contexto)
    else:
        servidor = smtplib.SMTP(s.SMTP_HOST, s.SMTP_PORT, timeout=20)
    try:
        if not s.SMTP_USAR_SSL and s.SMTP_USAR_TLS:
            servidor.starttls(context=contexto)
        if s.SMTP_USUARIO:
            servidor.login(s.SMTP_USUARIO, s.SMTP_SENHA)
        servidor.send_message(msg)
    finally:
        try:
            servidor.quit()
        except Exception:  # noqa: BLE001
            pass
