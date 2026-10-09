"""Geracao de notificacoes internas a partir das pendencias e envio por e-mail.

- `gerar_notificacoes`: transforma Pendencias em Notificacoes, uma por usuario
  com a permissao de leitura correspondente. Idempotente: a chave_dedup +
  UniqueConstraint(usuario_id, chave_dedup) impedem repeticao.
- `notificar_evento`: notificacao pontual disparada por um evento (ex.: conta
  bloqueada) para quem tem determinada permissao.
- `enviar_emails_pendentes`: despacha os e-mails da fila (nivel atencao/critico,
  usuario com e-mail e preferencia ligada) com limite de tentativas.

Por design NAO falha a requisicao/rotina se o e-mail falhar: o erro fica
registrado na propria notificacao para nova tentativa."""
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.config import get_settings
from app.models.notificacao import Notificacao
from app.models.usuario import Usuario
from app.services import email_service
from app.services.pendencias_service import Pendencia, coletar_pendencias

logger = logging.getLogger("eletrogestor.notificacoes")

NIVEIS_COM_EMAIL = {"atencao", "critico"}


def _usuarios_com_permissao(db: Session, permissao: str) -> list[Usuario]:
    ativos = db.query(Usuario).filter(Usuario.ativo.is_(True)).all()
    saida = []
    for u in ativos:
        perms = set(u.perfil.permissoes or [])
        if "*" in perms or permissao in perms:
            saida.append(u)
    return saida


def _criar_se_nova(db: Session, usuario: Usuario, p: Pendencia, existentes: set[tuple[int, str]]) -> bool:
    if (usuario.id, p.chave_dedup) in existentes:
        return False
    quer_email = bool(usuario.email and usuario.notificacoes_email and p.nivel in NIVEIS_COM_EMAIL)
    db.add(Notificacao(
        usuario_id=usuario.id, tipo=p.tipo, modulo=p.modulo, nivel=p.nivel, titulo=p.titulo,
        mensagem=p.mensagem, entidade=p.entidade, entidade_id=p.entidade_id, chave_dedup=p.chave_dedup,
        email_status="pendente" if quer_email else None,
    ))
    existentes.add((usuario.id, p.chave_dedup))
    return True


def _chaves_existentes(db: Session, chaves: list[str]) -> set[tuple[int, str]]:
    if not chaves:
        return set()
    linhas = db.query(Notificacao.usuario_id, Notificacao.chave_dedup).filter(Notificacao.chave_dedup.in_(chaves)).all()
    return {(u, c) for u, c in linhas}


def gerar_notificacoes(db: Session, pendencias: list[Pendencia] | None = None) -> int:
    pendencias = coletar_pendencias(db) if pendencias is None else pendencias
    existentes = _chaves_existentes(db, [p.chave_dedup for p in pendencias])
    cache_destinatarios: dict[str, list[Usuario]] = {}
    novas = 0
    for p in pendencias:
        if p.permissao not in cache_destinatarios:
            cache_destinatarios[p.permissao] = _usuarios_com_permissao(db, p.permissao)
        for usuario in cache_destinatarios[p.permissao]:
            if _criar_se_nova(db, usuario, p, existentes):
                novas += 1
    db.flush()
    return novas


def notificar_evento(db: Session, p: Pendencia) -> int:
    """Notificacao pontual (nao vem do varredor de pendencias)."""
    existentes = _chaves_existentes(db, [p.chave_dedup])
    novas = 0
    for usuario in _usuarios_com_permissao(db, p.permissao):
        if _criar_se_nova(db, usuario, p, existentes):
            novas += 1
    db.flush()
    return novas


def _corpo_email(n: Notificacao) -> tuple[str, str, str]:
    s = get_settings()
    link = f"{s.FRONTEND_URL.rstrip('/')}/notificacoes"
    assunto = f"[EletroGestor] {n.titulo}"
    texto = f"{n.titulo}\n\n{n.mensagem}\n\nAbrir no sistema: {link}\n"
    html = (
        f"<h3>{_esc(n.titulo)}</h3><p>{_esc(n.mensagem)}</p>"
        f'<p><a href="{_esc(link)}">Abrir no sistema</a></p>'
    )
    return assunto, texto, html


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def enviar_emails_pendentes(db: Session, limite: int = 100) -> dict:
    s = get_settings()
    fila = (
        db.query(Notificacao)
        .filter(Notificacao.email_status.in_(("pendente", "falhou")), Notificacao.email_tentativas < s.EMAIL_MAX_TENTATIVAS)
        .order_by(Notificacao.id)
        .limit(limite)
        .all()
    )
    resultado = {"enviados": 0, "falhas": 0, "ignorados": 0}
    if not fila:
        return resultado

    if not email_service.email_disponivel():
        # Sem SMTP configurado: marca como ignorado em vez de reprocessar para sempre.
        for n in fila:
            n.email_status = "ignorado"
            n.email_erro = "Envio de e-mail desabilitado/nao configurado."
        resultado["ignorados"] = len(fila)
        db.flush()
        return resultado

    for n in fila:
        usuario = n.usuario
        if not usuario.email or not usuario.notificacoes_email:
            n.email_status = "ignorado"
            resultado["ignorados"] += 1
            continue
        assunto, texto, html = _corpo_email(n)
        n.email_tentativas += 1
        try:
            email_service.enviar_email(usuario.email, assunto, texto, html)
            n.email_status = "enviado"
            n.email_enviado_em = datetime.now(timezone.utc)
            n.email_erro = None
            resultado["enviados"] += 1
        except Exception as exc:  # noqa: BLE001
            n.email_status = "falhou"
            n.email_erro = f"{type(exc).__name__}: {exc}"[:255]
            resultado["falhas"] += 1
            logger.warning("falha ao enviar e-mail da notificacao %s: %s", n.id, exc)
    db.flush()
    return resultado


def processar(db: Session, usuario_id: int | None = None) -> dict:
    """Rotina completa (cron): gera notificacoes novas e despacha e-mails."""
    novas = gerar_notificacoes(db)
    emails = enviar_emails_pendentes(db)
    registrar(
        db, usuario_id=usuario_id, acao="notificacoes_processadas", entidade="notificacoes",
        depois={"novas": novas, **emails}, bot=None if usuario_id else "cron",
    )
    db.commit()
    return {"novas": novas, **emails}
