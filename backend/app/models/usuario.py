"""Perfis (papeis/permissoes) e Usuarios."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Perfil(Base):
    """Perfil de acesso (papel). Ex.: administrador, programacao, almoxarifado."""

    __tablename__ = "perfis"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # slug, ex: "administrador"
    nome: Mapped[str] = mapped_column(String(80), nullable=False)
    descricao: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    categoria: Mapped[str] = mapped_column(String(20), nullable=False)  # GESTAO/OPERACAO/SUPORTE/TECNICO
    # Lista de chaves de permissao, ex: ["obras:read", "obras:write"]. "*" = acesso total.
    permissoes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    usuarios: Mapped[list["Usuario"]] = relationship(back_populates="perfil")


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    usuario: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)
    senha_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    perfil_id: Mapped[str] = mapped_column(ForeignKey("perfis.id"), nullable=False)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # ---- Login: tentativas/bloqueio ----
    tentativas_login_falhas: Mapped[int] = mapped_column(default=0, nullable=False)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_login_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- Senha por convite ----
    senha_definida: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    convite_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    convite_expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- Troca de senha obrigatoria (primeiro acesso com senha temporaria,
    # ou expiracao por politica -- ver ParametroGlobal "senha_validade_dias") ----
    deve_trocar_senha: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    senha_alterada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- Preferencias ----
    # Recebe e-mail das notificacoes de nivel atencao/critico (o sino no sistema
    # e' sempre ativo).
    notificacoes_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, server_default=true())

    # ---- 2FA (preparado, sem integracao externa ainda) ----
    mfa_habilitado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    perfil: Mapped["Perfil"] = relationship(back_populates="usuarios")


class RefreshToken(Base):
    """Refresh tokens de longa duracao, revogaveis (armazenamos apenas o hash)."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revogado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    usuario: Mapped["Usuario"] = relationship()
