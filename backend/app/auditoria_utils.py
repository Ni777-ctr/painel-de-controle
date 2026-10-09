"""Helper para gravar entradas de auditoria a partir dos routers.

Cada entrada recebe uma `categoria` (login, falha_acesso, exportacao,
exclusao, alteracao, sistema) derivada do nome da acao, alem de IP e
user-agent da requisicao corrente (ver app/contexto.py). A tela "Historico do
sistema" filtra por essas categorias."""
from sqlalchemy.orm import Session

from app.contexto import obter_contexto
from app.models.auditoria import AuditLog

CATEGORIAS = ("login", "falha_acesso", "exportacao", "exclusao", "alteracao", "sistema")

# Acoes que representam falha/tentativa suspeita de acesso.
_FALHAS_ACESSO = {
    "login_falhou",
    "login_usuario_inexistente",
    "usuario_bloqueado",
    "mfa_codigo_invalido",
    "acesso_negado",
    "login_rate_limit",
    "login_bloqueado_mfa_obrigatorio",
}
_SISTEMA_PREFIXOS = ("notificacoes_", "alertas_financeiros_", "automacao_", "importacao_")
_EXCLUSAO_MARCAS = ("excluid", "removid", "desativad", "deletad", "revogad")


def classificar_acao(acao: str) -> str:
    a = (acao or "").lower()
    if a in _FALHAS_ACESSO:
        return "falha_acesso"
    if a.startswith("exportacao_"):
        return "exportacao"
    if a.startswith(("login_", "logout", "mfa_", "senha_", "sessao_", "usuario_desbloqueado")):
        return "login"
    if any(m in a for m in _EXCLUSAO_MARCAS):
        return "exclusao"
    if a.startswith(_SISTEMA_PREFIXOS):
        return "sistema"
    return "alteracao"


def registrar(
    db: Session,
    *,
    usuario_id: int | None,
    acao: str,
    entidade: str,
    entidade_id: str | None = None,
    antes: dict | None = None,
    depois: dict | None = None,
    bot: str | None = None,
) -> AuditLog:
    ctx = obter_contexto()
    log = AuditLog(
        usuario_id=usuario_id,
        bot=bot,
        acao=acao,
        categoria=classificar_acao(acao),
        entidade=entidade,
        entidade_id=entidade_id,
        antes=antes,
        depois=depois,
        ip=ctx.ip,
        user_agent=(ctx.user_agent or "")[:255] or None,
    )
    db.add(log)
    return log
