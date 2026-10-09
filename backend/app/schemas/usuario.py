from datetime import datetime

from app.schemas.base import OrmModel


class PerfilOut(OrmModel):
    id: str
    nome: str
    descricao: str
    categoria: str
    permissoes: list[str]


class UsuarioUpdate(OrmModel):
    nome: str | None = None
    email: str | None = None
    senha: str | None = None
    perfil_id: str | None = None
    ativo: bool | None = None


class UsuarioOut(OrmModel):
    id: int
    nome: str
    usuario: str
    email: str | None = None
    perfil_id: str
    ativo: bool
    senha_definida: bool
    deve_trocar_senha: bool
    bloqueado_ate: datetime | None = None
    tentativas_login_falhas: int
    ultimo_login_em: datetime | None = None
    mfa_habilitado: bool
