"""Supervisao: empreiteiras e Relatorios Diarios de Campo.

Registrado como os demais routers (sem prefixo global): /supervisao/empreiteiras
e /supervisao/relatorios. Leitura exige `supervisao:read`; escrita, `supervisao:write`."""
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import requer_permissao
from app.models.supervisao import Empreiteira, RelatorioSupervisao
from app.models.usuario import Usuario
from app.schemas.supervisao import (
    EmpreiteiraCreate,
    EmpreiteiraOut,
    EmpreiteiraUpdate,
    RelatorioSupervisaoCreate,
    RelatorioSupervisaoOut,
    RelatorioSupervisaoUpdate,
    StatusRelatorio,
)

router = APIRouter(prefix="/supervisao", tags=["Supervisao"])


def _like(termo: str) -> str:
    """Termo literal para LIKE (escapa % _ \\)."""
    return "%" + termo.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _json_safe(valor):
    if isinstance(valor, (date, time)):
        return valor.isoformat()
    return valor


def _commit_ou_409(db: Session, detalhe: str) -> None:
    """Commit que converte violacao de integridade (corrida entre checagem e gravacao:
    CNPJ duplicado ou empreiteira recem-vinculada a relatorio) em 409 em vez de 500."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detalhe) from exc


# ---------------------------------------------------------------------------
# Empreiteiras
# ---------------------------------------------------------------------------
def _empreiteira_ou_404(db: Session, empreiteira_id: int) -> Empreiteira:
    e = db.get(Empreiteira, empreiteira_id)
    if not e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empreiteira nao encontrada.")
    return e


@router.get("/empreiteiras", response_model=list[EmpreiteiraOut])
def listar_empreiteiras(
    ativo: bool | None = None,
    q: str | None = Query(None, description="Busca no nome/razao social, CNPJ ou codigo do contrato"),
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("supervisao:read")),
):
    query = db.query(Empreiteira)
    if ativo is not None:
        query = query.filter(Empreiteira.ativo.is_(ativo))
    if q and q.strip():
        like = _like(q)
        query = query.filter(
            Empreiteira.nome_razao_social.ilike(like, escape="\\")
            | func.coalesce(Empreiteira.cnpj, "").ilike(like, escape="\\")
            | func.coalesce(Empreiteira.codigo_contrato, "").ilike(like, escape="\\")
        )
    return query.order_by(Empreiteira.nome_razao_social).all()


@router.post("/empreiteiras", response_model=EmpreiteiraOut, status_code=status.HTTP_201_CREATED)
def criar_empreiteira(
    dados: EmpreiteiraCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("supervisao:write"))
):
    if dados.cnpj and db.query(Empreiteira.id).filter(Empreiteira.cnpj == dados.cnpj).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ja existe uma empreiteira com este CNPJ.")
    e = Empreiteira(**dados.model_dump())
    db.add(e)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="empreiteira_criada", entidade="empreiteiras", entidade_id=str(e.id),
              depois={"nome_razao_social": e.nome_razao_social, "cnpj": e.cnpj})
    _commit_ou_409(db, "Ja existe uma empreiteira com este CNPJ.")
    db.refresh(e)
    return e


@router.get("/empreiteiras/{empreiteira_id}", response_model=EmpreiteiraOut)
def obter_empreiteira(empreiteira_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("supervisao:read"))):
    return _empreiteira_ou_404(db, empreiteira_id)


@router.patch("/empreiteiras/{empreiteira_id}", response_model=EmpreiteiraOut)
def atualizar_empreiteira(
    empreiteira_id: int,
    dados: EmpreiteiraUpdate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("supervisao:write")),
):
    e = _empreiteira_ou_404(db, empreiteira_id)
    mudancas = dados.model_dump(exclude_unset=True)
    if mudancas.get("nome_razao_social", "x") is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="nome_razao_social nao pode ser nulo.")
    if mudancas.get("ativo", True) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ativo nao pode ser nulo.")
    novo_cnpj = mudancas.get("cnpj")
    if novo_cnpj and db.query(Empreiteira.id).filter(Empreiteira.cnpj == novo_cnpj, Empreiteira.id != e.id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ja existe uma empreiteira com este CNPJ.")
    antes = {k: getattr(e, k) for k in mudancas}
    for campo, valor in mudancas.items():
        setattr(e, campo, valor)
    registrar(db, usuario_id=ator.id, acao="empreiteira_atualizada", entidade="empreiteiras", entidade_id=str(e.id),
              antes=antes, depois=mudancas)
    _commit_ou_409(db, "Ja existe uma empreiteira com este CNPJ.")
    db.refresh(e)
    return e


@router.delete("/empreiteiras/{empreiteira_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_empreiteira(
    empreiteira_id: int, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("supervisao:write"))
):
    e = _empreiteira_ou_404(db, empreiteira_id)
    if db.query(RelatorioSupervisao.id).filter(RelatorioSupervisao.empreiteira_id == e.id).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Empreiteira possui relatorios vinculados e nao pode ser excluida; desative-a (ativo=false).",
        )
    registrar(db, usuario_id=ator.id, acao="empreiteira_excluida", entidade="empreiteiras", entidade_id=str(e.id),
              antes={"nome_razao_social": e.nome_razao_social, "cnpj": e.cnpj})
    db.delete(e)
    _commit_ou_409(
        db, "Empreiteira possui relatorios vinculados e nao pode ser excluida; desative-a (ativo=false)."
    )


# ---------------------------------------------------------------------------
# Relatorios de supervisao
# ---------------------------------------------------------------------------
def _serializar(r: RelatorioSupervisao) -> RelatorioSupervisaoOut:
    out = RelatorioSupervisaoOut.model_validate(r)
    out.empreiteira_nome = r.empreiteira.nome_razao_social if r.empreiteira else r.empreiteira_nome_customizado
    return out


def _relatorio_ou_404(db: Session, relatorio_id: int) -> RelatorioSupervisao:
    r = db.query(RelatorioSupervisao).options(joinedload(RelatorioSupervisao.empreiteira)).filter(
        RelatorioSupervisao.id == relatorio_id
    ).first()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatorio nao encontrado.")
    return r


def _validar_empreiteira(db: Session, empreiteira_id: int | None) -> None:
    if empreiteira_id is not None and not db.get(Empreiteira, empreiteira_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empreiteira_id inexistente.")


@router.get("/relatorios", response_model=list[RelatorioSupervisaoOut])
def listar_relatorios(
    data: date | None = Query(None, description="Dia exato"),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    municipio: str | None = None,
    status_relatorio: StatusRelatorio | None = Query(None, alias="status"),
    empreiteira_id: int | None = None,
    empreiteira: str | None = Query(None, description="Texto no nome da empreiteira (cadastrada ou customizada)"),
    responsavel: str | None = None,
    limite: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("supervisao:read")),
):
    if data_inicio and data_fim and data_inicio > data_fim:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="data_inicio deve ser anterior a data_fim.")
    q = db.query(RelatorioSupervisao).options(joinedload(RelatorioSupervisao.empreiteira))
    if data:
        q = q.filter(RelatorioSupervisao.data_relatorio == data)
    if data_inicio:
        q = q.filter(RelatorioSupervisao.data_relatorio >= data_inicio)
    if data_fim:
        q = q.filter(RelatorioSupervisao.data_relatorio <= data_fim)
    if municipio and municipio.strip():
        q = q.filter(RelatorioSupervisao.municipio.ilike(_like(municipio), escape="\\"))
    if status_relatorio:
        q = q.filter(RelatorioSupervisao.status == status_relatorio)
    if empreiteira_id is not None:
        q = q.filter(RelatorioSupervisao.empreiteira_id == empreiteira_id)
    if responsavel and responsavel.strip():
        q = q.filter(RelatorioSupervisao.responsavel.ilike(_like(responsavel), escape="\\"))
    if empreiteira and empreiteira.strip():
        like = _like(empreiteira)
        q = q.outerjoin(Empreiteira, RelatorioSupervisao.empreiteira_id == Empreiteira.id).filter(
            Empreiteira.nome_razao_social.ilike(like, escape="\\")
            | func.coalesce(RelatorioSupervisao.empreiteira_nome_customizado, "").ilike(like, escape="\\")
        )
    rows = q.order_by(RelatorioSupervisao.data_relatorio.desc(), RelatorioSupervisao.id.desc()).offset(offset).limit(limite).all()
    return [_serializar(r) for r in rows]


@router.post("/relatorios", response_model=RelatorioSupervisaoOut, status_code=status.HTTP_201_CREATED)
def criar_relatorio(
    dados: RelatorioSupervisaoCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("supervisao:write"))
):
    _validar_empreiteira(db, dados.empreiteira_id)
    r = RelatorioSupervisao(**dados.model_dump(), criado_por_id=ator.id)
    db.add(r)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="relatorio_supervisao_criado", entidade="relatorios_supervisao", entidade_id=str(r.id),
              depois={"data_relatorio": r.data_relatorio.isoformat(), "projeto_atividade": r.projeto_atividade, "status": r.status})
    db.commit()
    return _serializar(_relatorio_ou_404(db, r.id))


@router.get("/relatorios/{relatorio_id}", response_model=RelatorioSupervisaoOut)
def obter_relatorio(relatorio_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("supervisao:read"))):
    return _serializar(_relatorio_ou_404(db, relatorio_id))


@router.put("/relatorios/{relatorio_id}", response_model=RelatorioSupervisaoOut)
def atualizar_relatorio(
    relatorio_id: int,
    dados: RelatorioSupervisaoUpdate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(requer_permissao("supervisao:write")),
):
    r = _relatorio_ou_404(db, relatorio_id)
    _validar_empreiteira(db, dados.empreiteira_id)
    novos = dados.model_dump()
    antes, depois = {}, {}
    for campo, valor in novos.items():
        atual = getattr(r, campo)
        if atual != valor:
            antes[campo] = _json_safe(atual)
            depois[campo] = _json_safe(valor)
        setattr(r, campo, valor)
    registrar(db, usuario_id=ator.id, acao="relatorio_supervisao_atualizado", entidade="relatorios_supervisao",
              entidade_id=str(r.id), antes=antes or None, depois=depois or None)
    db.commit()
    db.expire_all()
    return _serializar(_relatorio_ou_404(db, relatorio_id))
