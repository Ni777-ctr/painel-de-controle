from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

CARGOS = ('dono', 'gerente', 'coordenador', 'colaborador')

class ContaCentral(Base):
    __tablename__ = 'central_contas'
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'), primary_key=True)
    cargo: Mapped[str] = mapped_column(String(20), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    criado_por: Mapped[int | None] = mapped_column(ForeignKey('usuarios.id'))
    versao_sessao: Mapped[int] = mapped_column(default=0)

class Setor(Base):
    __tablename__ = 'central_setores'
    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(100), unique=True)
    descricao: Mapped[str] = mapped_column(String(500), default='')
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    modulos: Mapped[list] = mapped_column(JSON, default=list)
    cargos: Mapped[list] = mapped_column(JSON, default=list)

class Vinculo(Base):
    __tablename__ = 'central_vinculos'
    __table_args__ = (UniqueConstraint('usuario_id', 'setor_id'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    setor_id: Mapped[int] = mapped_column(ForeignKey('central_setores.id'))
    cargo: Mapped[str] = mapped_column(String(20))
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey('usuarios.id'))

class Limite(Base):
    __tablename__ = 'central_limites'
    cargo: Mapped[str] = mapped_column(String(20), primary_key=True)
    # 0 = empresa; demais valores são IDs validados de setores.
    setor_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habilitado: Mapped[bool] = mapped_column(Boolean)
    maximo: Mapped[int] = mapped_column(Integer)
    alerta_percentual: Mapped[int] = mapped_column(Integer, default=80)
    pode_cadastrar: Mapped[bool] = mapped_column(Boolean, default=False)

class Regra(Base):
    __tablename__ = 'central_regras'
    setor_id: Mapped[int] = mapped_column(ForeignKey('central_setores.id'), primary_key=True)
    cargo: Mapped[str] = mapped_column(String(20), primary_key=True)
    permissao: Mapped[str] = mapped_column(String(100), primary_key=True)
    permitido: Mapped[bool] = mapped_column(Boolean)

class Excecao(Base):
    __tablename__ = 'central_excecoes'
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'), primary_key=True)
    setor_id: Mapped[int] = mapped_column(ForeignKey('central_setores.id'), primary_key=True)
    permissao: Mapped[str] = mapped_column(String(100), primary_key=True)
    permitido: Mapped[bool] = mapped_column(Boolean)

class Sessao(Base):
    __tablename__ = 'central_sessoes'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'))
    csrf: Mapped[str] = mapped_column(String(64))
    versao: Mapped[int] = mapped_column(default=0)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class VersaoAutenticacao(Base):
    __tablename__ = 'central_versoes_auth'
    usuario_id: Mapped[int] = mapped_column(ForeignKey('usuarios.id'), primary_key=True)
    versao: Mapped[int] = mapped_column(default=0)
