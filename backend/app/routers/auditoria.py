"""Historico do sistema (tela do administrador): logins, alteracoes, exclusoes,
exportacoes e falhas de acesso, com filtros e paginacao. Somente leitura +
inclusao -- nao existe edicao/exclusao de log."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auditoria_utils import CATEGORIAS, registrar
from app.database import get_db
from app.deps import get_current_user, requer_permissao
from app.models.auditoria import AuditLog
from app.models.usuario import Usuario
from app.schemas.auditoria import AuditLogCreate, AuditLogOut, AuditLogPagina, ResumoAuditoria

router = APIRouter(prefix="/auditoria", tags=["Auditoria"])


def _serializar(log: AuditLog) -> AuditLogOut:
    out = AuditLogOut.model_validate(log)
    out.usuario_nome = log.usuario.nome if log.usuario else None
    return out


def _filtrar(query, *, entidade, categoria, acao, usuario_id, ip, data_inicio, data_fim):
    if entidade:
        query = query.filter(AuditLog.entidade == entidade)
    if categoria:
        query = query.filter(AuditLog.categoria == categoria)
    if acao:
        query = query.filter(AuditLog.acao.ilike(f"%{acao}%"))
    if usuario_id:
        query = query.filter(AuditLog.usuario_id == usuario_id)
    if ip:
        query = query.filter(AuditLog.ip == ip)
    if data_inicio:
        query = query.filter(AuditLog.criado_em >= datetime.combine(data_inicio, datetime.min.time(), tzinfo=timezone.utc))
    if data_fim:
        query = query.filter(AuditLog.criado_em < datetime.combine(data_fim + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    return query


@router.get("", response_model=list[AuditLogOut])
def listar_logs(
    entidade: str | None = None,
    categoria: str | None = Query(None, description="login | falha_acesso | exportacao | exclusao | alteracao | sistema"),
    acao: str | None = None,
    usuario_id: int | None = None,
    ip: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limite: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("auditoria:read")),
):
    """Lista simples (compativel com o frontend atual). Para total/paginacao use /auditoria/pagina."""
    if categoria and categoria not in CATEGORIAS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"categoria deve ser uma de {CATEGORIAS}.")
    q = _filtrar(
        db.query(AuditLog).options(joinedload(AuditLog.usuario)),
        entidade=entidade, categoria=categoria, acao=acao, usuario_id=usuario_id, ip=ip, data_inicio=data_inicio, data_fim=data_fim,
    )
    logs = q.order_by(AuditLog.criado_em.desc(), AuditLog.id.desc()).offset(offset).limit(limite).all()
    return [_serializar(x) for x in logs]


@router.get("/pagina", response_model=AuditLogPagina)
def listar_logs_paginado(
    entidade: str | None = None,
    categoria: str | None = None,
    acao: str | None = None,
    usuario_id: int | None = None,
    ip: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limite: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("auditoria:read")),
):
    if categoria and categoria not in CATEGORIAS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"categoria deve ser uma de {CATEGORIAS}.")
    q = _filtrar(
        db.query(AuditLog), entidade=entidade, categoria=categoria, acao=acao, usuario_id=usuario_id, ip=ip,
        data_inicio=data_inicio, data_fim=data_fim,
    )
    total = q.count()
    logs = (
        q.options(joinedload(AuditLog.usuario))
        .order_by(AuditLog.criado_em.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limite)
        .all()
    )
    return AuditLogPagina(total=total, limite=limite, offset=offset, itens=[_serializar(x) for x in logs])


@router.get("/resumo", response_model=ResumoAuditoria)
def resumo(
    dias: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("auditoria:read")),
):
    """Visao rapida do periodo: volume por categoria, acoes mais frequentes e IPs com mais falhas de acesso."""
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    base = db.query(AuditLog).filter(AuditLog.criado_em >= desde)
    por_categoria = dict(
        base.with_entities(AuditLog.categoria, func.count(AuditLog.id)).group_by(AuditLog.categoria).all()
    )
    top = (
        base.with_entities(AuditLog.acao, func.count(AuditLog.id).label("n"))
        .group_by(AuditLog.acao)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )
    falhas_ip = (
        base.filter(AuditLog.categoria == "falha_acesso", AuditLog.ip.isnot(None))
        .with_entities(AuditLog.ip, func.count(AuditLog.id).label("n"))
        .group_by(AuditLog.ip)
        .order_by(func.count(AuditLog.id).desc())
        .limit(10)
        .all()
    )
    return ResumoAuditoria(
        desde=desde,
        por_categoria={c: por_categoria.get(c, 0) for c in CATEGORIAS},
        top_acoes=[{"acao": a, "total": n} for a, n in top],
        falhas_acesso_por_ip=[{"ip": i, "total": n} for i, n in falhas_ip],
    )


@router.post("", response_model=AuditLogOut, status_code=status.HTTP_201_CREATED)
def registrar_log(
    dados: AuditLogCreate, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)
):
    """Qualquer usuario autenticado pode registrar um log da propria acao."""
    log = registrar(db, usuario_id=usuario.id, **dados.model_dump())
    db.commit()
    db.refresh(log)
    return _serializar(log)
