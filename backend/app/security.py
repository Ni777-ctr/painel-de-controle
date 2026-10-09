"""Hash de senha, emissao/validacao de tokens JWT, tokens opacos
(refresh token / convite de senha) armazenados apenas como hash, e 2FA via
TOTP (compativel com Google Authenticator, Authy etc. -- sem depender de
e-mail/SMS externos)."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Perfis que exigem 2FA (usuario pode logar sem, mas o front deve sinalizar
# a pendencia de configuracao -- ver UsuarioPublico.mfa_obrigatorio).
PERFIS_COM_2FA_OBRIGATORIO = {"administrador", "desenvolvedor", "tester", "gerencia-geral", "administrativo"}

MFA_ISSUER = "EletroGestor"


def gerar_token_opaco() -> str:
    """Gera um token aleatorio seguro (refresh token / convite). Cru, enviado
    uma unica vez ao cliente -- apenas o hash e persistido no banco."""
    return secrets.token_urlsafe(32)


def hash_token_opaco(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_senha(senha: str) -> str:
    return pwd_context.hash(senha)


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return pwd_context.verify(senha, senha_hash)


def criar_token_temporario(subject: str, minutos: int, extra_claims: dict | None = None) -> str:
    expira_em = datetime.now(timezone.utc) + timedelta(minutes=minutos)
    payload = {"sub": subject, "exp": expira_em}
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def criar_access_token(subject: str, extra_claims: dict | None = None) -> str:
    return criar_token_temporario(subject, settings.ACCESS_TOKEN_EXPIRE_MINUTES, extra_claims)


def decodificar_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ---------- 2FA / TOTP ----------
def gerar_mfa_secret() -> str:
    return pyotp.random_base32()


def gerar_provisioning_uri(secret: str, identificador: str) -> str:
    """URI otpauth:// para gerar o QR code no app autenticador (Google
    Authenticator, Authy, etc.)."""
    return pyotp.TOTP(secret).provisioning_uri(name=identificador, issuer_name=MFA_ISSUER)


def verificar_codigo_totp(secret: str, codigo: str) -> bool:
    if not secret or not codigo:
        return False
    # valid_window=1 tolera deriva de +-1 intervalo de 30s entre servidor e celular.
    return pyotp.TOTP(secret).verify(codigo, valid_window=1)


# ---------- Rate limit simples (janela deslizante, em memoria do processo) ----------
import threading
import time
from collections import defaultdict, deque


class LimitadorJanela:
    """Limita N eventos por chave (ex.: IP) numa janela de S segundos.
    Em memoria: vale por processo/worker. Com varios workers o limite efetivo
    e' N x workers -- suficiente como freio basico contra forca bruta; o
    bloqueio por conta (5 tentativas) continua sendo a defesa principal."""

    def __init__(self) -> None:
        self._eventos: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def excedeu(self, chave: str, maximo: int, janela_s: int) -> bool:
        agora = time.monotonic()
        with self._lock:
            fila = self._eventos[chave]
            while fila and agora - fila[0] > janela_s:
                fila.popleft()
            if len(fila) >= maximo:
                return True
            fila.append(agora)
            return False

    def resetar(self) -> None:
        with self._lock:
            self._eventos.clear()


limitador_login = LimitadorJanela()
