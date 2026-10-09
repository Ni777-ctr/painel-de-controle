from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import get_current_user, requer_permissao, tem_permissao
from app.models.compras import RequisicaoCompra
from app.models.estoque import Material, MovimentacaoEstoque
from app.models.financeiro import Fatura, Medicao
from app.models.obra import HistoricoStatusObra, Obra, Programacao
from app.models.usuario import Usuario
from app.schemas.obra import (
    HistoricoStatusOut,
    MaterialConsumidoResumo,
    ObraCreate,
    ObraOut,
    ObraResumoOut,
    ObraUpdate,
    ResumoCompras,
    ResumoFinanceiro,
    ResumoProgramacao,
)

router = APIRouter(prefix="/obras", tags=["Obras"])

# Maquina de estados: de qual status a obra pode ir para quais outros.
TRANSICOES_VALIDAS: dict[str, set[str]] = {
    "proposta": {"contratada", "cancelada"},
    "contratada": {"em_execucao", "cancelada"},
    "em_execucao": {"concluida", "cancelada"},
    "concluida": set(),
    "cancelada": set(),
}


def _serializar(obra: Obra) -> ObraOut:
    """Serializa explicitamente (em vez de ObraOut.model_validate(obra)) porque
    o schema tem um campo 'equipe' (nome da equipe, str) com o mesmo nome do
    relacionamento ORM 'equipe' (objeto Equipe) -- from_attributes tentaria
    validar o objeto Equipe como string e falharia."""
    return ObraOut(
        id=obra.id,
        wl=obra.wl,
        descricao=obra.descricao,
        regional=obra.regional,
        cliente_id=obra.cliente_id,
        equipe_id=obra.equipe_id,
        equipe=obra.equipe.nome if obra.equipe else None,
        status=obra.status,
        valor_contrato=obra.valor_contrato,
        custo_previsto=obra.custo_previsto,
        custo_realizado=obra.custo_realizado,
        avanco_previsto=obra.avanco_previsto,
        avanco_realizado=obra.avanco_realizado,
        necs_planejados=float(obra.necs_planejados or 0),
        necs_executados=float(obra.necs_executados or 0),
        necs_faturados=float(obra.necs_faturados or 0),
        dias_contratada=obra.dias_contratada,
        data_inicio=obra.data_inicio,
        data_fim=obra.data_fim,
        observacoes=obra.observacoes,
    )


@router.get("", response_model=list[ObraOut])
def listar_obras(
    regional: str | None = None,
    status_obra: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("obras:read")),
):
    query = db.query(Obra).options(joinedload(Obra.equipe))
    if regional:
        query = query.filter(Obra.regional == regional)
    if status_obra:
        query = query.filter(Obra.status == status_obra)
    return [_serializar(o) for o in query.order_by(Obra.wl).all()]


@router.get("/{obra_id}", response_model=ObraOut)
def obter_obra(obra_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("obras:read"))):
    obra = db.query(Obra).options(joinedload(Obra.equipe)).filter(Obra.id == obra_id).first()
    if not obra:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")
    return _serializar(obra)


@router.post("", response_model=ObraOut, status_code=status.HTTP_201_CREATED)
def criar_obra(
    dados: ObraCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("obras:write"))
):
    if db.query(Obra).filter(Obra.wl == dados.wl).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ja existe uma obra com esse codigo (wl).")
    obra = Obra(**dados.model_dump())
    db.add(obra)
    db.flush()  # obtem obra.id
    db.add(HistoricoStatusObra(obra_id=obra.id, status_anterior=None, status_novo=obra.status, usuario_id=ator.id))
    registrar(db, usuario_id=ator.id, acao="obra_criada", entidade="obras", entidade_id=str(obra.id))
    db.commit()
    db.refresh(obra)
    return _serializar(obra)


@router.patch("/{obra_id}", response_model=ObraOut)
def atualizar_obra(
    obra_id: int,
    dados: ObraUpdate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(get_current_user),
):
    obra = db.get(Obra, obra_id)
    if not obra:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")

    dados_dict = dados.model_dump(exclude_unset=True)
    novo_status = dados_dict.get("status")
    havera_transicao = bool(novo_status) and novo_status != obra.status

    if havera_transicao:
        # Campos alem de status/equipe_id exigem obras:write "cheio"; a
        # permissao especifica da transicao e checada mais abaixo.
        campos_fora_da_transicao = set(dados_dict) - {"status", "equipe_id"}
        if campos_fora_da_transicao and not tem_permissao(ator, "obras:write"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao tem permissao para esta acao.")
    elif not tem_permissao(ator, "obras:write"):
        # Sem transicao de status real, qualquer edicao (inclusive PATCH
        # vazio ou so com equipe_id) exige a permissao geral de escrita.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao tem permissao para esta acao.")

    if havera_transicao:
        permitidos = TRANSICOES_VALIDAS.get(obra.status, set())
        if novo_status not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Transicao de status invalida: '{obra.status}' -> '{novo_status}'.",
            )
        chave_permissao = f"obras:transicao:{obra.status}:{novo_status}"
        if not tem_permissao(ator, chave_permissao) and not tem_permissao(ator, "obras:write"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Seu perfil nao tem permissao para a transicao '{obra.status}' -> '{novo_status}'.",
            )
        equipe_final = dados_dict.get("equipe_id", obra.equipe_id)
        if novo_status == "em_execucao" and not equipe_final:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nao e possivel iniciar a execucao sem uma equipe responsavel (equipe_id).",
            )
        db.add(
            HistoricoStatusObra(
                obra_id=obra.id, status_anterior=obra.status, status_novo=novo_status, usuario_id=ator.id
            )
        )
        registrar(
            db,
            usuario_id=ator.id,
            acao="obra_status_alterado",
            entidade="obras",
            entidade_id=str(obra.id),
            antes={"status": obra.status},
            depois={"status": novo_status},
        )

    for campo, valor in dados_dict.items():
        setattr(obra, campo, valor)

    db.commit()
    db.refresh(obra)
    return _serializar(obra)


@router.delete("/{obra_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_obra(obra_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("obras:write"))):
    obra = db.get(Obra, obra_id)
    if not obra:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")
    db.delete(obra)
    db.commit()


@router.get("/{obra_id}/resumo", response_model=ObraResumoOut)
def resumo_obra(obra_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("obras:read"))):
    """Visao agregada da obra como entidade central: programacao, financeiro,
    compras, consumo de materiais e historico de status -- sem duplicar
    nenhuma das tabelas, apenas consultando o que ja referencia obra_id."""
    obra = db.query(Obra).options(joinedload(Obra.equipe), joinedload(Obra.cliente)).filter(Obra.id == obra_id).first()
    if not obra:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")

    programacoes = db.query(Programacao).filter(Programacao.obra_id == obra_id).all()
    prog_por_status: dict[str, int] = {}
    for p in programacoes:
        prog_por_status[p.status] = prog_por_status.get(p.status, 0) + 1

    medicoes = db.query(Medicao).filter(Medicao.obra_id == obra_id).all()
    faturas = db.query(Fatura).filter(Fatura.obra_id == obra_id).all()
    valor_faturado = sum(float(f.valor) for f in faturas)
    valor_pago = sum(float(f.valor) for f in faturas if f.status == "Paga")

    requisicoes = db.query(RequisicaoCompra).filter(RequisicaoCompra.obra_id == obra_id).all()
    req_por_status: dict[str, int] = {}
    for r in requisicoes:
        req_por_status[r.status] = req_por_status.get(r.status, 0) + 1

    consumo = (
        db.query(
            MovimentacaoEstoque.material_id,
            Material.nome,
            func.coalesce(func.sum(MovimentacaoEstoque.quantidade), 0),
        )
        .join(Material, Material.id == MovimentacaoEstoque.material_id)
        .filter(MovimentacaoEstoque.obra_id == obra_id, MovimentacaoEstoque.tipo == "saida")
        .group_by(MovimentacaoEstoque.material_id, Material.nome)
        .all()
    )

    historico = db.query(HistoricoStatusObra).filter(HistoricoStatusObra.obra_id == obra_id).order_by(
        HistoricoStatusObra.criado_em.desc()
    ).all()

    return ObraResumoOut(
        obra=_serializar(obra),
        cliente_nome=obra.cliente.nome if obra.cliente else None,
        programacao=ResumoProgramacao(total=len(programacoes), por_status=prog_por_status),
        financeiro=ResumoFinanceiro(
            medicoes_total=len(medicoes),
            faturas_total=len(faturas),
            valor_faturado=valor_faturado,
            valor_pago=valor_pago,
            valor_pendente=valor_faturado - valor_pago,
        ),
        compras=ResumoCompras(requisicoes_total=len(requisicoes), por_status=req_por_status),
        materiais_consumidos=[
            MaterialConsumidoResumo(material_id=mid, material_nome=nome, quantidade_saida=float(qtd))
            for mid, nome, qtd in consumo
        ],
        historico_status=[HistoricoStatusOut.model_validate(h) for h in historico],
    )
