from app.schemas.base import OrmModel


class ClienteBase(OrmModel):
    nome: str
    documento: str | None = None
    contato: str | None = None
    telefone: str | None = None
    email: str | None = None
    endereco: str | None = None


class ClienteCreate(ClienteBase):
    pass


class ClienteUpdate(OrmModel):
    nome: str | None = None
    documento: str | None = None
    contato: str | None = None
    telefone: str | None = None
    email: str | None = None
    endereco: str | None = None


class ClienteOut(ClienteBase):
    id: int
