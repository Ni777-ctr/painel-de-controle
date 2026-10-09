from app.schemas.base import OrmModel


class EquipeCreate(OrmModel):
    nome: str
    lider_usuario_id: int | None = None
    ativa: bool = True


class EquipeUpdate(OrmModel):
    nome: str | None = None
    lider_usuario_id: int | None = None
    ativa: bool | None = None


class EquipeOut(OrmModel):
    id: int
    nome: str
    lider_usuario_id: int | None = None
    ativa: bool


class EquipeMembroCreate(OrmModel):
    usuario_id: int
    funcao: str | None = None


class EquipeMembroOut(OrmModel):
    id: int
    equipe_id: int
    usuario_id: int
    funcao: str | None = None
