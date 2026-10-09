"""Grava no banco o que `parsers.ler_planilhas` validou. Tudo em UMA transacao (o chamador
faz commit/rollback). Idempotente:

- clientes / equipes / obras: upsert por nome / wl. Obra existente so recebe campos que estao
  VAZIOS (dado editado a mao nao e' sobrescrito), salvo `sobrescrever=True`.
- medicoes, programacoes e as 4 tabelas novas: as linhas anteriores marcadas com `origem`
  "planilha:*" sao substituidas (reimportar nao duplica). Linhas criadas a mao nao sao tocadas.
"""
from datetime import datetime, time, timezone

from sqlalchemy.orm import Session

from app.auditoria_utils import registrar
from app.importacao.leitor import normalizar_chave
from app.importacao.modelos import D0, Dados
from app.importacao.parsers import MOTIVO_GLOSA_IMPORTADA, ORIGEM_MEDICAO, ORIGEM_PROGRAMACAO
from app.models.cliente import Cliente
from app.models.equipe import Equipe
from app.models.financeiro import Fatura, Glosa, Medicao
from app.models.obra import Obra, Programacao
from app.models.planilha import ExecucaoObra, GeradorProgramacao, InventarioObra, SigeoExtracao


class ImportacaoErro(Exception):
    pass


def _vazio(valor) -> bool:
    return valor is None or valor == "" or valor == 0 or valor == D0


def aplicar(db: Session, dados: Dados, *, sobrescrever: bool = False, glosas_resolvidas: bool = True) -> dict:
    resumo: dict = {}

    # ---- Guarda: nao reimportar medicoes que ja tem fatura emitida no sistema ----
    ids_importadas = db.query(Medicao.id).filter(Medicao.origem == ORIGEM_MEDICAO)
    if db.query(Fatura.id).filter(Fatura.medicao_id.in_(ids_importadas)).first():
        raise ImportacaoErro(
            "Existem faturas vinculadas a medicoes importadas anteriormente; a reimportacao das medicoes "
            "foi bloqueada para nao perder esse vinculo. Resolva as faturas antes."
        )

    # ---- Clientes e equipes ----
    clientes = {normalizar_chave(c.nome): c for c in db.query(Cliente).all()}
    novos = 0
    for chave, nome in dados.clientes.items():
        if chave not in clientes:
            clientes[chave] = Cliente(nome=nome)
            db.add(clientes[chave])
            novos += 1
    resumo["clientes_criados"] = novos

    equipes = {normalizar_chave(e.nome): e for e in db.query(Equipe).all()}
    novos = 0
    for chave, nome in dados.equipes.items():
        if chave not in equipes:
            equipes[chave] = Equipe(nome=nome)
            db.add(equipes[chave])
            novos += 1
    resumo["equipes_criadas"] = novos
    db.flush()

    # ---- Obras ----
    existentes = {o.wl: o for o in db.query(Obra).all()}
    criadas = atualizadas = 0
    for wl, d in dados.obras.items():
        cliente = clientes.get(normalizar_chave(d["cliente_nome"])) if d["cliente_nome"] else None
        obra = existentes.get(wl)
        if obra is None:
            obra = Obra(
                wl=wl, regional=d["regional"], necs_planejados=d["necs_planejados"] or 0,
                avanco_realizado=d["avanco_realizado"] or 0, data_fim=d["data_fim"], observacoes=d["observacoes"],
                cliente_id=cliente.id if cliente else None, dados_planilha=d["dados_planilha"] or None,
            )
            db.add(obra)
            existentes[wl] = obra
            criadas += 1
            continue
        mudou = False
        for campo, novo in (
            ("regional", d["regional"]), ("necs_planejados", d["necs_planejados"]),
            ("avanco_realizado", d["avanco_realizado"]), ("data_fim", d["data_fim"]),
            ("observacoes", d["observacoes"]), ("cliente_id", cliente.id if cliente else None),
        ):
            if novo is None:
                continue
            if sobrescrever or _vazio(getattr(obra, campo)):
                if getattr(obra, campo) != novo:
                    setattr(obra, campo, novo)
                    mudou = True
        if d["dados_planilha"]:
            obra.dados_planilha = {**(obra.dados_planilha or {}), **d["dados_planilha"]}
            mudou = True
        atualizadas += int(mudou)
    resumo["obras_criadas"] = criadas
    resumo["obras_atualizadas"] = atualizadas

    arquivadas = 0
    sem_obra = []
    for wl in dados.arquivados:
        o = existentes.get(wl)
        if o is None:
            sem_obra.append(wl)
        elif not o.arquivada:
            o.arquivada = True
            arquivadas += 1
    resumo["obras_arquivadas"] = arquivadas
    resumo["arquivo_morto_sem_obra"] = len(sem_obra)
    db.flush()

    # ---- Substitui o que veio de importacao anterior ----
    db.query(Glosa).filter(Glosa.medicao_id.in_(ids_importadas)).delete(synchronize_session=False)
    db.query(Medicao).filter(Medicao.origem == ORIGEM_MEDICAO).delete(synchronize_session=False)
    db.query(Programacao).filter(Programacao.origem == ORIGEM_PROGRAMACAO).delete(synchronize_session=False)
    for modelo in (InventarioObra, ExecucaoObra, SigeoExtracao, GeradorProgramacao):
        db.query(modelo).filter(modelo.origem.like("planilha:%")).delete(synchronize_session=False)

    # ---- Medicoes (+ glosas) ----
    objs = []
    for m in dados.medicoes:
        criado = datetime.combine(m["data_emissao_nf"], time(12, 0), tzinfo=timezone.utc) if m["data_emissao_nf"] else None
        obj = Medicao(
            obra_id=existentes[m["wl"]].id, contrato=0, percentual=m["percentual"], necs_medidos=m["necs_medidos"],
            status="Rascunho", dias_parada=0, ciclo_medicao=m["ciclo"], area=m["area"], familia=m["familia"],
            valor_faturado=m["valor_faturado"], emitida_nf=m["emitida_nf"], data_emissao_nf=m["data_emissao_nf"],
            necs_orcados=m["necs_orcados"], necs_inventariados=m["necs_inventariados"],
            divergencia_necs=m["divergencia_necs"], valor_pago_por_nec=m["valor_pago_por_nec"], origem=ORIGEM_MEDICAO,
        )
        if criado:
            obj.criado_em = criado
        objs.append((m, obj))
        db.add(obj)
    db.flush()
    glosas = 0
    por_obra: dict = {}
    for m, obj in objs:
        if m["glosado"]:
            db.add(Glosa(medicao_id=obj.id, valor=m["glosado"], motivo=MOTIVO_GLOSA_IMPORTADA, resolvida=glosas_resolvidas))
            glosas += 1
        por_obra[m["wl"]] = por_obra.get(m["wl"], D0) + (m["necs_medidos"] or D0)
    for wl, total in por_obra.items():
        o = existentes[wl]
        if total > 0 and (sobrescrever or _vazio(o.necs_faturados)):
            o.necs_faturados = total
    resumo["medicoes"] = len(objs)
    resumo["glosas"] = glosas

    # ---- Programacoes ----
    n = 0
    for p in dados.programacoes:
        db.add(Programacao(
            obra_id=existentes[p["wl"]].id, equipe_id=equipes[p["equipe_chave"]].id, data=p["data"], turno=p["turno"],
            status=p["status"], observacoes=p["observacoes"], origem=ORIGEM_PROGRAMACAO, dados_planilha=p["dados_planilha"],
        ))
        n += 1
    resumo["programacoes"] = n

    # ---- Tabelas novas ----
    def inserir(modelo, linhas):
        rows = []
        for r in linhas:
            r = dict(r)
            r.pop("tem_obra", None)
            obra = existentes.get(r["projeto_codigo"])
            r["obra_id"] = obra.id if obra else None
            rows.append(r)
        if rows:
            db.bulk_insert_mappings(modelo, rows)
        return len(rows)

    db.flush()
    resumo["inventarios_obra"] = inserir(InventarioObra, dados.inventarios)
    resumo["execucoes_obra"] = inserir(ExecucaoObra, dados.execucoes)
    resumo["sigeo_extracoes"] = inserir(SigeoExtracao, dados.sigeo)
    resumo["geradores_programacao"] = inserir(GeradorProgramacao, dados.geradores)

    registrar(db, usuario_id=None, bot="importacao_planilhas", acao="importacao_planilhas", entidade="obras", depois=resumo)
    return resumo
