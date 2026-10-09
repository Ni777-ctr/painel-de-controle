"""Exportacao de relatorios em Excel/PDF por periodo, obra e responsavel, com
registro de quem gerou e quando (RelatorioGerado + auditoria)."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import get_current_user, requer_permissao, tem_permissao
from app.models.obra import Obra
from app.models.relatorio import RelatorioGerado
from app.models.usuario import Usuario
from app.schemas.relatorio import HistoricoRelatorios, RelatorioGeradoOut, TipoRelatorioOut
from app.services import relatorio_service as rs

router = APIRouter(prefix="/relatorios", tags=["Relatorios e exportacao"])


def _tipo_ou_404(chave: str) -> rs.TipoRelatorio:
    t = rs.REGISTRO.get(chave)
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tipo de relatorio desconhecido: {chave}.")
    return t


@router.get("/tipos", response_model=list[TipoRelatorioOut])
def listar_tipos(usuario: Usuario = Depends(requer_permissao("relatorios:export"))):
    """Tipos que o usuario pode exportar (exige relatorios:export + leitura do dominio)."""
    return [
        TipoRelatorioOut(chave=t.chave, nome=t.nome, descricao=t.descricao, data_referencia=t.data_ref, formatos=list(rs.RENDERIZADORES))
        for t in rs.REGISTRO.values()
        if tem_permissao(usuario, t.permissao_leitura)
    ]


@router.get("/exportar/{tipo}")
def exportar(
    tipo: str,
    formato: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    data_inicio: date | None = None,
    data_fim: date | None = None,
    obra_id: int | None = None,
    responsavel_id: int | None = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(requer_permissao("relatorios:export")),
):
    t = _tipo_ou_404(tipo)
    if not tem_permissao(usuario, t.permissao_leitura):
        registrar(db, usuario_id=usuario.id, acao="acesso_negado", entidade="relatorios", entidade_id=tipo,
                  depois={"permissao_necessaria": t.permissao_leitura})
        db.commit()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao pode exportar este relatorio.")
    if data_inicio and data_fim and data_inicio > data_fim:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="data_inicio deve ser anterior a data_fim.")

    rotulos: dict = {}
    if obra_id:
        obra = db.get(Obra, obra_id)
        if not obra:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")
        rotulos["obra"] = obra.wl
    if responsavel_id:
        resp = db.get(Usuario, responsavel_id)
        if not resp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Responsavel nao encontrado.")
        rotulos["responsavel"] = resp.nome

    filtros = rs.Filtros(data_inicio, data_fim, obra_id, responsavel_id)
    tabela = t.gerar(db, filtros)
    agora = datetime.now(timezone.utc)
    try:
        conteudo = rs.RENDERIZADORES[formato](tabela, gerado_por=usuario.nome, gerado_em=agora, filtros=filtros, rotulos=rotulos)
    except rs.RelatorioMuitoGrande as exc:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc

    nome_arquivo = f"{t.chave}_{agora:%Y%m%d_%H%M%S}.{formato}"
    registro = RelatorioGerado(
        usuario_id=usuario.id, tipo=t.chave, formato=formato, periodo_inicio=data_inicio, periodo_fim=data_fim,
        obra_id=obra_id, responsavel_usuario_id=responsavel_id, filtros=filtros.como_dict(),
        nome_arquivo=nome_arquivo, linhas=len(tabela.linhas), tamanho_bytes=len(conteudo),
    )
    db.add(registro)
    db.flush()
    registrar(
        db, usuario_id=usuario.id, acao=f"exportacao_{t.chave}", entidade="relatorios", entidade_id=str(registro.id),
        depois={"formato": formato, "linhas": len(tabela.linhas), **filtros.como_dict()},
    )
    db.commit()

    return Response(
        content=conteudo,
        media_type=rs.CONTENT_TYPES[formato],
        headers={
            "Content-Disposition": f'attachment; filename="{nome_arquivo}"',
            "X-Relatorio-Id": str(registro.id),
            "X-Relatorio-Linhas": str(len(tabela.linhas)),
            "Cache-Control": "no-store",
        },
    )


@router.get("/historico", response_model=HistoricoRelatorios)
def historico(
    tipo: str | None = None,
    usuario_id: int | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    limite: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(requer_permissao("relatorios:export")),
):
    """Quem gerou o que e quando. Quem tem auditoria:read ve de todos; os demais, so os proprios."""
    q = db.query(RelatorioGerado)
    if not tem_permissao(usuario, "auditoria:read"):
        q = q.filter(RelatorioGerado.usuario_id == usuario.id)
    elif usuario_id:
        q = q.filter(RelatorioGerado.usuario_id == usuario_id)
    if tipo:
        q = q.filter(RelatorioGerado.tipo == tipo)
    if data_inicio:
        q = q.filter(RelatorioGerado.criado_em >= datetime.combine(data_inicio, datetime.min.time(), tzinfo=timezone.utc))
    if data_fim:
        from datetime import timedelta

        q = q.filter(RelatorioGerado.criado_em < datetime.combine(data_fim + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    total = q.count()
    itens = q.order_by(RelatorioGerado.criado_em.desc(), RelatorioGerado.id.desc()).offset(offset).limit(limite).all()
    saida = []
    for r in itens:
        d = RelatorioGeradoOut.model_validate(r)
        d.usuario_nome = r.usuario.nome if r.usuario else None
        saida.append(d)
    return HistoricoRelatorios(total=total, itens=saida)
