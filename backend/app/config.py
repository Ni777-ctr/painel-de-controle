"""Configuracoes da aplicacao, lidas de variaveis de ambiente (.env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg2://eletrogestor:eletrogestor@localhost:5432/eletrogestor"
    JWT_SECRET_KEY: str = "troque-esta-chave-antes-de-ir-para-producao"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DIAS: int = 7
    MAX_TENTATIVAS_LOGIN: int = 5
    BLOQUEIO_MINUTOS: int = 30
    CONVITE_EXPIRA_HORAS: int = 72
    MFA_TOKEN_EXPIRE_MINUTOS: int = 5
    SENHA_PENDENTE_TOKEN_EXPIRE_MINUTOS: int = 15
    CORS_ORIGINS: str = "http://localhost:8081,http://localhost:5173,http://localhost:3000"

    # ---- Publicacao / seguranca ----
    # "development" (padrao) | "production". Em producao a API se recusa a subir com
    # configuracao insegura (ver validar_para_producao abaixo).
    ENVIRONMENT: str = "development"
    # Atras de proxy (Render, Cloudflare): confia em X-Forwarded-For/-Proto.
    TRUST_PROXY: bool = False
    # Redireciona http -> https (so faz sentido em producao atras de proxy).
    FORCE_HTTPS: bool = False
    # Lista (separada por virgula) de Hosts aceitos; vazio = aceita qualquer.
    ALLOWED_HOSTS: str = ""
    # Esconde /docs, /redoc e /openapi.json (recomendado em producao).
    DOCS_HABILITADO: bool = True
    # IDs autorizados ao painel local; não altera os hosts/CORS do site principal.
    CENTRAL_ADMIN_IDS: str = ''
    CENTRAL_LOGIN_USER_ID: int = 0
    CENTRAL_PASSWORD_HASH: str = ''
    # Exige 2FA para os perfis em PERFIS_COM_2FA_OBRIGATORIO (app/security.py).
    MFA_OBRIGATORIO_ENFORCE: bool = False
    # Limite de tentativas de login por IP (janela deslizante, em memoria do processo).
    LOGIN_RATE_LIMIT_MAX: int = 20
    LOGIN_RATE_LIMIT_JANELA_SEGUNDOS: int = 60
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False
    SENTRY_DSN: str = ""

    # ---- Notificacoes por e-mail (SMTP; o Resend tambem expoe SMTP) ----
    EMAIL_HABILITADO: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USUARIO: str = ""
    SMTP_SENHA: str = ""
    SMTP_USAR_TLS: bool = True  # STARTTLS na porta 587; use SMTP_USAR_SSL para 465
    SMTP_USAR_SSL: bool = False
    EMAIL_REMETENTE: str = "EletroGestor <nao-responder@eletrogestor.local>"
    EMAIL_MAX_TENTATIVAS: int = 3
    # Base do frontend, usada nos links dos e-mails.
    FRONTEND_URL: str = "http://localhost:8081"

    @property
    def em_producao(self) -> bool:
        return self.ENVIRONMENT.strip().lower() in {"production", "producao", "prod"}

    @property
    def allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.ALLOWED_HOSTS.split(",") if h.strip()]

    @property
    def database_url_normalizada(self) -> str:
        """Aceita a URL "crua" do Neon/Render (postgres:// ou postgresql://) e a
        converte para o driver instalado (psycopg2)."""
        url = self.DATABASE_URL.strip()
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        if url.startswith("postgresql://"):
            url = "postgresql+psycopg2://" + url[len("postgresql://"):]
        return url

    def validar_para_producao(self) -> list[str]:
        """Retorna a lista de problemas de configuracao que impedem subir em
        producao. Vazia = ok (ou nao esta em producao)."""
        if not self.em_producao:
            return []
        problemas: list[str] = []
        if self.JWT_SECRET_KEY.startswith("troque-esta-chave") or len(self.JWT_SECRET_KEY) < 32:
            problemas.append("JWT_SECRET_KEY fraca/padrao (use >= 32 caracteres aleatorios).")
        if "eletrogestor:eletrogestor@localhost" in self.DATABASE_URL or self.DATABASE_URL.startswith("sqlite"):
            problemas.append("DATABASE_URL aponta para banco local/de desenvolvimento.")
        if not self.cors_origins_list or any("localhost" in o for o in self.cors_origins_list):
            problemas.append("CORS_ORIGINS vazio ou com localhost (defina a URL real do frontend).")
        return problemas

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
