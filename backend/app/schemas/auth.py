from datetime import datetime

from app.schemas.base import OrmModel


class LoginRequest(OrmModel):
    usuario: str
    senha: str


class RefreshRequest(OrmModel):
    refresh_token: str


class LogoutRequest(OrmModel):
    refresh_token: str


class UsuarioPublico(OrmModel):
    id: int
    nome: str
    usuario: str
    email: str | None = None
    ativo: bool
    perfil_id: str
    mfa_habilitado: bool = False
    mfa_obrigatorio: bool = False  # perfil exige 2FA mas ainda nao foi configurado/habilitado


class TokenResponse(OrmModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    usuario: UsuarioPublico


class LoginResponse(OrmModel):
    """Resposta de POST /auth/login. Quatro formatos possiveis, nesta ordem
    de precedencia quando mais de uma condicao se aplica:
    1. senha_pendente=True -- senha temporaria (primeiro acesso) ou expirada
       pela politica de validade; troque em POST /auth/trocar-senha-obrigatoria
       usando senha_pendente_token.
    2. mfa_pendente=True -- 2FA habilitado; valide em POST /auth/mfa/validar
       usando mfa_token.
    3. Nenhum dos dois: tokens finais (access_token/refresh_token/usuario)."""

    senha_pendente: bool = False
    senha_pendente_token: str | None = None
    senha_pendente_motivo: str | None = None  # "primeiro_acesso" | "expirada"

    # 2FA obrigatorio para o perfil (MFA_OBRIGATORIO_ENFORCE) mas ainda nao
    # configurado: use mfa_setup_token (Bearer) SOMENTE em /auth/mfa/iniciar e
    # /auth/mfa/confirmar; depois faca login de novo.
    mfa_configuracao_pendente: bool = False
    mfa_setup_token: str | None = None

    mfa_pendente: bool = False
    mfa_token: str | None = None

    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"
    usuario: UsuarioPublico | None = None


class ConviteCreate(OrmModel):
    nome: str
    usuario: str
    email: str | None = None
    perfil_id: str


class ConviteResponse(OrmModel):
    usuario_id: int
    convite_token: str
    expira_em: datetime


class DefinirSenhaConvite(OrmModel):
    convite_token: str
    senha: str


class TrocarSenhaObrigatoriaRequest(OrmModel):
    senha_pendente_token: str
    nova_senha: str


class TrocarSenhaRequest(OrmModel):
    senha_atual: str
    nova_senha: str


# ---------- 2FA ----------
class MfaIniciarResponse(OrmModel):
    secret: str
    otpauth_uri: str


class MfaConfirmarRequest(OrmModel):
    codigo: str


class MfaDesabilitarRequest(OrmModel):
    senha: str


class MfaValidarRequest(OrmModel):
    mfa_token: str
    codigo: str
