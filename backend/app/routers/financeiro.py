from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.database import get_db
from app.deps import get_current_user, requer_permissao, tem_permissao
from app.models.financeiro import Fatura, Glosa, Medicao, Pagamento
from app.models.obra import Obra
from app.models.usuario import Usuario
from app.schemas.financeiro import (
    FaturaCreate,
    FaturaOut,
    FaturaUpdate,
    GlosaCreate,
    GlosaOut,
    MedicaoCreate,
    MedicaoOut,
    MedicaoUpdate,
    PagamentoCreate,
    PagamentoOut,
    ResumoCobranca,
)

router = APIRouter(tags=["Medicoes, Faturas e Cobranca"])

# Maquina de estados da medicao (mesmo padrao de Obra/PedidoCompra).
TRANSICOES_MEDICAO: dict[str, set[str]] = {
    "Rascunho": {"Aprovada", "Reprovada"},
    "Aprovada": set(),
    "Reprovada": {"Rascunho"},  # pode ser corrigida e reenviada
}


# ---------- Medicoes ----------
@router.get("/medicoes", response_model=list[MedicaoOut])
def listar_medicoes(
    obra_id: int | None = None,
    status_medicao: str | None = None,
    db: Session = Depends(get_db),
    _=Depends(requer_permissao("financeiro:read")),
):
    query = db.query(Medicao)
    if obra_id:
        query = query.filter(Medicao.obra_id == obra_id)
    if status_medicao:
        query = query.filter(Medicao.status == status_medicao)
    return query.order_by(Medicao.criado_em.desc()).all()


@router.post("/medicoes", response_model=MedicaoOut, status_code=status.HTTP_201_CREATED)
def criar_medicao(
    dados: MedicaoCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    medicao = Medicao(**dados.model_dump())
    db.add(medicao)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="medicao_criada", entidade="medicoes", entidade_id=str(medicao.id))
    db.commit()
    db.refresh(medicao)
    return medicao


@router.patch("/medicoes/{medicao_id}", response_model=MedicaoOut)
def atualizar_medicao(
    medicao_id: int,
    dados: MedicaoUpdate,
    db: Session = Depends(get_db),
    ator: Usuario = Depends(get_current_user),
):
    medicao = db.get(Medicao, medicao_id)
    if not medicao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicao nao encontrada.")

    dados_dict = dados.model_dump(exclude_unset=True)
    novo_status = dados_dict.get("status")
    havera_transicao = bool(novo_status) and novo_status != medicao.status

    if havera_transicao:
        permitidos = TRANSICOES_MEDICAO.get(medicao.status, set())
        if novo_status not in permitidos:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Transicao de status invalida: '{medicao.status}' -> '{novo_status}'.",
            )
        chave_permissao = f"financeiro:transicao:{medicao.status}:{novo_status}"
        campos_fora_da_transicao = set(dados_dict) - {"status"}
        if not tem_permissao(ator, chave_permissao) and not tem_permissao(ator, "financeiro:write"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Seu perfil nao tem permissao para a transicao '{medicao.status}' -> '{novo_status}'.",
            )
        if campos_fora_da_transicao and not tem_permissao(ator, "financeiro:write"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao tem permissao para esta acao.")

        registrar(
            db, usuario_id=ator.id, acao="medicao_status_alterado", entidade="medicoes", entidade_id=str(medicao.id),
            antes={"status": medicao.status}, depois={"status": novo_status},
        )
    elif not tem_permissao(ator, "financeiro:write"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Seu perfil nao tem permissao para esta acao.")

    for campo, valor in dados_dict.items():
        setattr(medicao, campo, valor)
    db.commit()
    db.refresh(medicao)
    return medicao


# ---------- Glosas (vinculadas a uma medicao) ----------
@router.get("/medicoes/{medicao_id}/glosas", response_model=list[GlosaOut])
def listar_glosas(medicao_id: int, db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    if not db.get(Medicao, medicao_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicao nao encontrada.")
    return db.query(Glosa).filter(Glosa.medicao_id == medicao_id).order_by(Glosa.criado_em.desc()).all()


@router.post("/medicoes/{medicao_id}/glosas", response_model=GlosaOut, status_code=status.HTTP_201_CREATED)
def registrar_glosa(
    medicao_id: int, dados: GlosaCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    medicao = db.get(Medicao, medicao_id)
    if not medicao:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medicao nao encontrada.")
    glosa = Glosa(medicao_id=medicao_id, **dados.model_dump())
    db.add(glosa)
    db.flush()
    registrar(db, usuario_id=ator.id, acao="glosa_registrada", entidade="medicoes", entidade_id=str(medicao_id), depois={"glosa_id": glosa.id, "valor": dados.valor})
    db.commit()
    db.refresh(glosa)
    return glosa


@router.patch("/glosas/{glosa_id}/resolver", response_model=GlosaOut)
def resolver_glosa(glosa_id: int, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))):
    glosa = db.get(Glosa, glosa_id)
    if not glosa:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glosa nao encontrada.")
    glosa.resolvida = True
    registrar(db, usuario_id=ator.id, acao="glosa_resolvida", entidade="medicoes", entidade_id=str(glosa.medicao_id))
    db.commit()
    db.refresh(glosa)
    return glosa


# ---------- Faturas ----------
def _serializar_fatura(fatura: Fatura) -> FaturaOut:
    saida = FaturaOut.model_validate(fatura)
    if fatura.status != "Paga" and fatura.vencimento < date.today():
        saida.dias_atraso = (date.today() - fatura.vencimento).days
    else:
        saida.dias_atraso = 0
    return saida


@router.get("/faturas", response_model=list[FaturaOut])
def listar_faturas(
    obra_id: int | None = None, db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))
):
    query = db.query(Fatura)
    if obra_id:
        query = query.filter(Fatura.obra_id == obra_id)
    return [_serializar_fatura(f) for f in query.order_by(Fatura.vencimento).all()]


@router.post("/faturas", response_model=FaturaOut, status_code=status.HTTP_201_CREATED)
def criar_fatura(
    dados: FaturaCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    """Emite uma fatura. Se necs_faturados for informado, soma automaticamente
    em Obra.necs_faturados (nao editar esse campo da obra diretamente)."""
    obra = db.get(Obra, dados.obra_id)
    if not obra:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Obra nao encontrada.")

    fatura = Fatura(**dados.model_dump())
    db.add(fatura)
    if dados.necs_faturados:
        obra.necs_faturados = float(obra.necs_faturados or 0) + dados.necs_faturados
    registrar(db, usuario_id=ator.id, acao="fatura_emitida", entidade="obras", entidade_id=str(obra.id), depois={"valor": dados.valor, "vencimento": dados.vencimento.isoformat()})
    db.commit()
    db.refresh(fatura)
    return _serializar_fatura(fatura)


@router.patch("/faturas/{fatura_id}", response_model=FaturaOut)
def atualizar_fatura(
    fatura_id: int, dados: FaturaUpdate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    fatura = db.get(Fatura, fatura_id)
    if not fatura:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fatura nao encontrada.")
    for campo, valor in dados.model_dump(exclude_unset=True).items():
        setattr(fatura, campo, valor)
    registrar(db, usuario_id=ator.id, acao="fatura_atualizada", entidade="obras", entidade_id=str(fatura.obra_id))
    db.commit()
    db.refresh(fatura)
    return _serializar_fatura(fatura)


# ---------- Pagamentos ----------
@router.get("/pagamentos", response_model=list[PagamentoOut])
def listar_pagamentos(db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    return db.query(Pagamento).order_by(Pagamento.data_pagamento.desc()).all()


@router.post("/pagamentos", response_model=PagamentoOut, status_code=status.HTTP_201_CREATED)
def registrar_pagamento(
    dados: PagamentoCreate, db: Session = Depends(get_db), ator: Usuario = Depends(requer_permissao("financeiro:write"))
):
    fatura = db.get(Fatura, dados.fatura_id)
    if not fatura:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fatura nao encontrada.")
    pagamento = Pagamento(**dados.model_dump())
    db.add(pagamento)

    total_pago = sum(p.valor for p in fatura.pagamentos) + dados.valor
    if total_pago >= float(fatura.valor):
        fatura.status = "Paga"
        fatura.percentual_pago = 100
    else:
        fatura.percentual_pago = round((total_pago / float(fatura.valor)) * 100, 2)

    registrar(db, usuario_id=ator.id, acao="pagamento_registrado", entidade="obras", entidade_id=str(fatura.obra_id), depois={"valor": dados.valor})
    db.commit()
    db.refresh(pagamento)
    return pagamento


# ---------- Cobranca (resumo) ----------
@router.get("/cobranca/resumo", response_model=ResumoCobranca)
def resumo_cobranca(db: Session = Depends(get_db), _=Depends(requer_permissao("financeiro:read"))):
    faturas = db.query(Fatura).all()
    hoje = date.today()

    atrasadas = [f for f in faturas if f.status != "Paga" and f.vencimento < hoje]
    pagas = [f for f in faturas if f.status == "Paga"]
    recuperadas = [f for f in pagas if f.vencimento < hoje]  # pagas que estiveram vencidas

    recuperacao = (len(recuperadas) / (len(recuperadas) + len(atrasadas)) * 100) if (recuperadas or atrasadas) else 0.0
    pendente = sum(float(f.valor) for f in faturas if f.status != "Paga")
    pago = sum(float(f.valor) for f in pagas)

    faixas = {"ate_10": 0, "11_a_30": 0, "acima_30": 0}
    for f in atrasadas:
        dias = (hoje - f.vencimento).days
        if dias <= 10:
            faixas["ate_10"] += 1
        elif dias <= 30:
            faixas["11_a_30"] += 1
        else:
            faixas["acima_30"] += 1

    return ResumoCobranca(
        recuperacao_percentual=round(recuperacao, 2),
        tempo_medio_dias=7,
        valor_pendente=pendente,
        valor_pago=pago,
        faixas_atraso=faixas,
    )
