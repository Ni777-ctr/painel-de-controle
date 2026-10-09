"""Leitura + validacao das abas -> `Dados` (estruturas puras, SEM banco).

Decisoes padrao (D1-D10 do relatorio de analise; detalhes em docs/IMPORTACAO_PLANILHAS.md):
 D1 Medicao NAO cria Fatura (a planilha nao tem vencimento nem numero de NF): valor/NF/data
    ficam na propria Medicao. Glosa com motivo fixo declarado. NECs decimais. Status Rascunho.
 D2 Cliente so com nome real ("-"/vazio -> sem cliente; ENEL nao e' criado).
 D3 Equipe = nome do encarregado, sem membros.
 D4 MONITORAMENTO nao e' importado (layout nao documentado no relatorio).
 D6 ARQUIVO MORTO -> Obra.arquivada=True (status inalterado).
 D7 Abas ocultas (MANUTENCAO, PROG. NOITE NOVO) ficam de fora.
 D8 Regional lida do codigo. D9 Codigo fora do padrao: rejeitar e listar.
"""
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.importacao.codigos import codigo_valido, normalizar_codigo, parece_codigo, regional_do_codigo
from app.importacao.leitor import (
    AbaNaoEncontrada,
    CabecalhoNaoEncontrado,
    Planilha,
    Tabela,
    normalizar_chave,
    para_bool_sim_nao,
    para_data,
    para_decimal,
    para_hora,
    pegar,
    sem_acentos,
    texto_limpo,
    valor_e_texto,
)
from app.importacao.modelos import D0, Dados, EstatAba

ORIGEM_MEDICAO = "planilha:faturamento:medicao"
ORIGEM_PROGRAMACAO = "planilha:tees:programacao"
MOTIVO_GLOSA_IMPORTADA = "Importado da planilha, sem motivo informado"

PROJETO = ["PROJETO"]

# ---------------------------------------------------------------------------
# Especificacoes (campo -> aliases de cabecalho, ja normalizados; `*` = curinga)
# ---------------------------------------------------------------------------
SPEC_OBRA = {
    "projeto": PROJETO,
    "necs_planejados": ["UPS ORCADO*", "NEC", "NECS"],
    "avanco": ["% EXEC"],
    "data_fim": ["DATA TERMINO*"],
    "observacoes": ["OBSERVACOES*"],
    "cliente": ["CLIENTE"],
}
SPEC_MEDICAO = {
    "projeto": PROJETO,
    "ciclo": ["CICLO DE MEDICAO", "CICLO*"],
    "area": ["AREA*"],
    "familia": ["FAMILIA"],
    "necs_faturada": ["QTDE NECS FATURADA*", "QTDE*NEC*FATURAD*"],
    "valor_faturado": ["VALOR*FATURADO*"],
    "emitida_nf": ["EMITIDA NF*"],
    "data_emissao": ["DATA DA EMISSAO*", "DATA*EMISSAO*"],
    "necs_orcado": ["NECS ORCADO*"],
    "necs_inventariado": ["NECS INVENTARIADO*"],
    "divergencia": ["DIVERGENCIAS*"],
    "valor_pago_por_nec": ["VALOR PAGO*"],
    "glosado": ["SUBTOTAL*GLOSADO*"],
}
SPEC_INVENTARIO = {
    "projeto": PROJETO,
    "familia": ("texto", ["FAMILIA"]),
    "valor_orcado": ("dec", ["VALOR ORCADO"]),
    "valor_inventario": ("dec", ["VALOR INVENTARIO"]),
    "diferenca_saldo": ("dec", ["DIFERENCA DE SALDO"]),
    "valor_parcial_solicitado": ("dec", ["VALOR PARCIAL SOLICITADO"]),
    "valor_pago_parcial": ("dec", ["VALOR PAGO PARCIAL"]),
    "data_solicitacao_parcial": ("data", ["DATA SOLICITACAO PARCIAL"]),
    "conclusao": ("texto", ["CONCLUSAO"]),
    "data_inventario": ("data", ["DATA INVENTARIO"]),
    "enviado_faturamento_enel": ("texto", ["ENVIADO PARA FATUR ENEL", "ENVIADO PARA FATUR*"]),
    "tecnico_responsavel": ("texto", ["TEC RESPONSAVEL", "TEC*RESPONSAVEL*"]),
    "status": ("texto", ["STATUS"]),
    "observacao": ("texto", ["OBSERVACAO", "OBSERVACOES"]),
    "ciclo_medicao": ("texto", ["CICLO DE MEDICAO", "CICLO*"]),
}
SPEC_EXECUCAO = {
    "projeto": PROJETO,
    "data": ("data", ["DATA"]),
    "circuito": ("texto", ["CIRCUITO"]),
    "familia": ("texto", ["FAMILIA"]),
    "percentual_executado": ("dec", ["% EXECUTADO", "% EXEC"]),
    "nec_orcado": ("dec", ["NEC ORCADO*", "NEC ORCADA*"]),
    "nec_programada": ("dec", ["NEC PROGRAMADA*", "NEC PROG*"]),
    "nec_executada": ("dec", ["NEC EXECUTADA*", "NEC EXEC*"]),
    "empresa": ("texto", ["EMPRESA"]),
    "status": ("texto", ["STATUS"]),
    "atraso": ("texto", ["ATRASO"]),
    "observacoes": ("texto", ["OBSERVACOES", "OBSERVACAO"]),
    "intervencao": ("texto", ["INTERVENCAO", "TIPO INTERVENCAO"]),
    "obra_eletricamente_concluida": ("texto", ["OBRA ELETRICAMENTE CONCLUIDA*"]),
    "data_envio_conclusao": ("data", ["DATA DE ENVIO DA CONCLUSAO*", "DATA*ENVIO*CONCLUSAO*"]),
    "qtde_lv": ("dec", ["QTDE LV", "QTD LV"]),
    "qtde_lm": ("dec", ["QTDE LM", "QTD LM"]),
    "inventario_aprovado": ("texto", ["INVENTARIO APROVADO*"]),
    "motivo_reprova": ("texto", ["MOTIVO DA REPROVA*", "MOTIVO*REPROVA*"]),
    "medicao": ("texto", ["MEDICAO"]),
}
SPEC_SIGEO = {
    "projeto": PROJETO,
    "data_programacao": ("data", ["DATA PROGRAMACAO", "DATA PROG*"]),
    "status_programacao": ("texto", ["STATUS PROGRAMACAO", "STATUS PROG*"]),
    "tipo_intervencao": ("texto", ["TIPO INTERVENCAO", "TIPO DE INTERVENCAO"]),
    "numero_poweron": ("texto", ["NUMERO POWERON", "NUMERO POWER ON", "N POWERON"]),
    "equipamentos": ("texto", ["EQUIPAMENTOS", "EQUIPAMENTO"]),
    "chi": ("dec", ["CHI"]),
    "horario_inicio": ("hora", ["HORARIO INICIO", "HORA INICIO"]),
    "horario_fim": ("hora", ["HORARIO FIM", "HORA FIM"]),
    "contratada": ("texto", ["CONTRATADA"]),
}
# Colunas auxiliares (formulas) da EXTRACAO SIGEO: ignoradas de proposito.
IGNORAR_SIGEO = {"CONCATENAR", "COLUNA 1", "COLUNA1"}
SPEC_GERADOR = {
    "projeto": PROJETO,
    "id_origem": ("texto", ["ID"]),
    "status": ("texto", ["STATUS"]),
    "regional": ("texto", ["REGIONAL"]),
    "area": ("texto", ["AREA"]),
    "contratada_propria": ("texto", ["CONTRATADA PROPRIA", "CONTRATADA*PROPRIA*"]),
    "tecnico_pre_operacao": ("texto", ["TECNICO PRE OPERACAO*", "TECNICO PRE*"]),
    "circuito": ("texto", ["CIRCUITO"]),
    "equipamento_seccionador": ("texto", ["EQUIPAMENTO SECCIONADOR*"]),
    "numero": ("texto", ["NUMERO"]),
    "endereco": ("texto", ["ENDERECO"]),
    "link": ("texto", ["LINK"]),
}
SPEC_PROGRAMACAO = {
    "projeto": PROJETO,
    "data": ["DATA"],
    "equipe": ["EQUIPE", "ENCARREGADO"],
    "status": ["STATUS", "STATUS PROG"],
    "turno": ["TURNO", "PERIODO"],
    "observacoes": ["OBSERVACOES"],
    "pct_prog": ["% PROG"],
}

STATUS_PROGRAMACAO = {
    "PROGRAMADO": "Programada", "PROGRAMADA": "Programada",
    "EM EXECUCAO": "Em execucao", "EM ANDAMENTO": "Em execucao",
    "EXECUTADO": "Concluida", "EXECUTADA": "Concluida", "CONCLUIDO": "Concluida", "CONCLUIDA": "Concluida",
    "CANCELADO": "Cancelada", "CANCELADA": "Cancelada",
}
FAMILIAS_AREA = {"CONSTRUCAO", "MANUTENCAO"}


def _q2(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _q3(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _dec(quantizador, valor) -> Decimal | None:
    d = para_decimal(valor)
    return quantizador(d) if d is not None else None


def _spec_aliases(spec: dict) -> dict:
    """Aceita spec simples (lista) ou (tipo, lista)."""
    return {k: (v[1] if isinstance(v, tuple) else v) for k, v in spec.items()}


def _abrir(plan: Planilha | None, dados: Dados, nomes, obrigatorios, destino) -> tuple[Tabela | None, EstatAba | None]:
    if plan is None:
        return None, None
    est = EstatAba(plan.nome, nomes[0], destino)
    dados.estat.append(est)
    try:
        tab = plan.tabela(list(nomes), obrigatorios)
    except (AbaNaoEncontrada, CabecalhoNaoEncontrado) as exc:
        est.erro = str(exc)
        return None, est
    est.aba = tab.aba
    return tab, est


def _conv(tipo: str, v):
    if tipo == "dec":
        return para_decimal(v)
    if tipo == "data":
        return para_data(v)
    if tipo == "hora":
        return para_hora(v)
    return texto_limpo(v)


def _codigo_da_linha(dados: Dados, est: EstatAba, num: int, bruto) -> str | None:
    """Normaliza + valida o codigo. Registra rejeicao e devolve None se invalido; None tambem se vazio."""
    codigo = normalizar_codigo(bruto)
    if codigo is None:
        est.sem_projeto += 1
        return None
    est.lidas += 1
    if not codigo_valido(codigo):
        dados.rejeitar(est, num, codigo, "codigo fora do padrao")
        return None
    return codigo


# ---------------------------------------------------------------------------
# OBRAS (CGO, Carteiras, SIGEO)
# ---------------------------------------------------------------------------
def _acumular_obra(dados: Dados, wl: str, fonte: str, campos: dict, extras: dict, vistos: set, est: EstatAba, num: int) -> None:
    if (fonte, wl) in vistos:
        est.aceitas -= 1  # ja contada como aceita; a repetida nao soma
        dados.rejeitar(est, num, wl, "codigo repetido na mesma aba", "a primeira ocorrencia foi mantida")
        return
    vistos.add((fonte, wl))
    o = dados.obras.setdefault(wl, {
        "wl": wl, "regional": regional_do_codigo(wl), "necs_planejados": None, "avanco_realizado": None,
        "data_fim": None, "observacoes": None, "cliente_nome": None, "dados_planilha": {}, "fontes": [],
    })
    for campo, valor in campos.items():
        if valor is None:
            continue
        atual = o[campo]
        if atual is None:
            o[campo] = valor
        elif atual != valor:
            dados.total_conflitos += 1
            if len(dados.conflitos) < 200:
                dados.conflitos.append({"projeto": wl, "campo": campo, "mantido": str(atual), "ignorado": str(valor), "fonte": fonte})
    if extras:
        o["dados_planilha"][fonte] = extras
    o["fontes"].append(fonte)


def _ler_fonte_obra(dados: Dados, plan: Planilha | None, nomes: list[str], fonte: str, vistos: set, so_codigo: bool = False) -> None:
    tab, est = _abrir(plan, dados, nomes, [PROJETO], "obras")
    if not tab:
        return
    cols = tab.mapear({"projeto": PROJETO} if so_codigo else SPEC_OBRA)
    est.colunas_usadas = {k: str(tab.cabecalhos_orig[i]) for k, i in cols.items() if i is not None}
    ignorar = {i for i, h in enumerate(tab.cabecalhos_norm) if h in IGNORAR_SIGEO}
    for num, linha in tab.linhas():
        wl = _codigo_da_linha(dados, est, num, pegar(linha, cols["projeto"]))
        if wl is None:
            continue
        est.aceitas += 1
        campos: dict = {}
        if not so_codigo:
            necs = para_decimal(pegar(linha, cols["necs_planejados"]))
            campos["necs_planejados"] = _q3(necs) if necs is not None and necs >= 0 else None
            av = para_decimal(pegar(linha, cols["avanco"]))
            if av is not None:
                if D0 <= av <= 1:
                    campos["avanco_realizado"] = _q2(av * 100)
                else:
                    dados.avisos[f"{fonte}: % EXEC fora de 0-1 (ignorado)"] += 1
            campos["data_fim"] = para_data(pegar(linha, cols["data_fim"]))
            campos["observacoes"] = texto_limpo(pegar(linha, cols["observacoes"]))
            cliente = texto_limpo(pegar(linha, cols["cliente"]))  # "-" e vazio -> None (D2)
            if cliente:
                cliente = cliente[:160]
                dados.clientes.setdefault(normalizar_chave(cliente), cliente)
                campos["cliente_nome"] = cliente
        extras = {} if so_codigo else tab.extras(linha, ignorar)
        _acumular_obra(dados, wl, fonte, campos, extras, vistos, est, num)
    est.colunas_nao_mapeadas = [] if so_codigo else tab.nao_mapeadas()


def ler_obras(dados: Dados, fat: Planilha | None, prog: Planilha | None) -> None:
    # Prioridade de valores: CGO > CARTEIRA SOT > CARTEIRA DE OBRAS > SIGEO. A aba CGO e' a mesma nos dois arquivos.
    vistos: set = set()
    cgo_no_faturamento = fat is not None and fat.tem_aba("CGO")
    _ler_fonte_obra(dados, fat, ["CGO"], "CGO", vistos)
    if not cgo_no_faturamento:
        _ler_fonte_obra(dados, prog, ["CGO"], "CGO", vistos)
    elif prog is not None and prog.tem_aba("CGO"):
        dados.avisos["CGO do arquivo de programacao nao lido (e' o mesmo do FATURAMENTO)"] += 1
    _ler_fonte_obra(dados, fat, ["CARTEIRA SOT"], "CARTEIRA_SOT", vistos)
    _ler_fonte_obra(dados, prog, ["CARTEIRA DE OBRAS"], "CARTEIRA_OBRAS", vistos)
    _ler_fonte_obra(dados, prog, ["EXTRACAO SIGEO"], "SIGEO", vistos, so_codigo=True)


def ler_arquivo_morto(dados: Dados, fat: Planilha | None) -> None:
    if fat is None or not fat.tem_aba("ARQUIVO MORTO"):
        return
    est = EstatAba(fat.nome, "ARQUIVO MORTO", "obras.arquivada")
    dados.estat.append(est)
    _, brutas = fat.linhas_brutas("ARQUIVO MORTO")
    for i, linha in enumerate(brutas, start=1):
        for v in linha:
            if not isinstance(v, str):
                continue
            c = normalizar_codigo(v)
            if not c:
                continue
            if codigo_valido(c):
                est.lidas += 1
                est.aceitas += 1
                dados.arquivados.add(c)
            elif parece_codigo(c):
                est.lidas += 1
                dados.rejeitar(est, i, c, "codigo fora do padrao")


# ---------------------------------------------------------------------------
# MEDICAO
# ---------------------------------------------------------------------------
def ler_medicao(dados: Dados, fat: Planilha | None) -> None:
    tab, est = _abrir(fat, dados, ["MEDICAO"], [PROJETO, ["CICLO DE MEDICAO", "CICLO*"]], "medicoes (+glosas)")
    totais = {"lido_numerico": D0, "lido_texto": D0, "celulas_texto": 0, "aceito": D0, "nf_sim_sem_data": 0, "celulas_erro": 0}
    dados.totais_medicao = totais
    if not tab:
        return
    cols = tab.mapear(SPEC_MEDICAO)
    est.colunas_usadas = {k: str(tab.cabecalhos_orig[i]) for k, i in cols.items() if i is not None}
    chaves_vistas: set = set()
    for num, linha in tab.linhas():
        g = lambda k: pegar(linha, cols[k])  # noqa: E731
        bruto_proj = g("projeto")
        # Conciliacao dos totais: soma tudo que tem projeto, antes de qualquer rejeicao.
        vf_bruto = g("valor_faturado")
        vf = para_decimal(vf_bruto)
        if normalizar_codigo(bruto_proj) is not None:
            if isinstance(vf_bruto, str) and vf_bruto.strip().startswith("#"):
                totais["celulas_erro"] += 1
            if vf is not None:
                if valor_e_texto(vf_bruto):
                    totais["lido_texto"] += vf
                    totais["celulas_texto"] += 1
                else:
                    totais["lido_numerico"] += vf
        wl = _codigo_da_linha(dados, est, num, bruto_proj)
        if wl is None:
            continue
        if wl not in dados.obras:
            dados.rejeitar(est, num, wl, "projeto sem obra", "nao existe em CGO/Carteiras/SIGEO; obra nao e' criada automaticamente")
            continue
        ciclo = texto_limpo(g("ciclo"))
        chave = (wl, ciclo)
        if ciclo is not None and chave in chaves_vistas:
            dados.rejeitar(est, num, wl, "duplicidade projeto+ciclo", f"ciclo {ciclo}")
            continue
        chaves_vistas.add(chave)

        area = texto_limpo(g("area"))
        familia = texto_limpo(g("familia"))
        # Itens 94-160 ("SIMPLIFICADA"): o codigo da familia (AC, RS, MA...) vem na coluna Area.
        if area and not familia and sem_acentos(area).upper() not in FAMILIAS_AREA and len(area) <= 3:
            familia, area = area.upper(), None
            dados.avisos["MEDICAO: familia lida da coluna Area (layout simplificado)"] += 1
        if familia:
            familia = familia[:20]

        necs = para_decimal(g("necs_faturada"))
        necs_orc = para_decimal(g("necs_orcado"))
        emitida = para_bool_sim_nao(g("emitida_nf"))
        data_nf = para_data(g("data_emissao"))
        if emitida and data_nf is None:
            totais["nf_sim_sem_data"] += 1
        pct = D0
        if necs is not None and necs_orc is not None and necs_orc > 0:
            pct = _q2(necs / necs_orc * 100)
            if pct > Decimal("999.99"):
                dados.avisos["MEDICAO: percentual calculado acima de 999,99 (gravado 0)"] += 1
                pct = D0
        if vf is not None:
            totais["aceito"] += vf
        glosado = para_decimal(g("glosado"))
        dados.medicoes.append({
            "wl": wl, "linha": num, "ciclo": ciclo[:30] if ciclo else None, "area": area[:40] if area else None,
            "familia": familia, "necs_medidos": _q3(necs) if necs is not None else D0,
            "valor_faturado": _q2(vf) if vf is not None else None, "emitida_nf": emitida, "data_emissao_nf": data_nf,
            "necs_orcados": _q3(necs_orc) if necs_orc is not None else None,
            "necs_inventariados": _dec(_q3, g("necs_inventariado")),
            "divergencia_necs": _dec(_q3, g("divergencia")),
            "valor_pago_por_nec": _dec(_q2, g("valor_pago_por_nec")),
            "percentual": pct, "glosado": _q2(glosado) if glosado is not None and glosado > 0 else None,
        })
        est.aceitas += 1
    est.colunas_nao_mapeadas = tab.nao_mapeadas()


# ---------------------------------------------------------------------------
# Tabelas "genericas" (Inventario, Execucao, SIGEO, Gerador)
# ---------------------------------------------------------------------------
def _ler_generica(dados: Dados, plan: Planilha | None, nomes, spec: dict, destino: str, lista: list, origem: str,
                  *, exigir_obra: bool, ignorar_norm: set = frozenset(), obrigatorios=None) -> None:
    tab, est = _abrir(plan, dados, nomes, obrigatorios or [PROJETO], destino)
    if not tab:
        return
    cols = tab.mapear(_spec_aliases(spec))
    est.colunas_usadas = {k: str(tab.cabecalhos_orig[i]) for k, i in cols.items() if i is not None}
    ignorar = {i for i, h in enumerate(tab.cabecalhos_norm) if h in ignorar_norm}
    for num, linha in tab.linhas():
        wl = _codigo_da_linha(dados, est, num, pegar(linha, cols["projeto"]))
        if wl is None:
            continue
        if exigir_obra and wl not in dados.obras:
            dados.rejeitar(est, num, wl, "projeto sem obra", "nao existe em CGO/Carteiras/SIGEO; obra nao e' criada automaticamente")
            continue
        row = {"projeto_codigo": wl, "tem_obra": wl in dados.obras, "linha_origem": num, "origem": origem}
        for campo, (tipo, _) in ((k, v) for k, v in spec.items() if isinstance(v, tuple)):
            v = _conv(tipo, pegar(linha, cols[campo]))
            if tipo == "dec" and v is not None:
                v = _q3(v) if campo.startswith(("nec", "qtde", "chi", "percentual")) else _q2(v)
            row[campo] = v
        extras = tab.extras(linha, ignorar)
        row["dados_extras"] = extras or None
        lista.append(row)
        est.aceitas += 1
    est.colunas_nao_mapeadas = tab.nao_mapeadas()


def ler_inventario(dados, fat):
    _ler_generica(dados, fat, ["INVENTARIO"], SPEC_INVENTARIO, "inventarios_obra", dados.inventarios,
                  "planilha:faturamento:inventario", exigir_obra=True)


def ler_execucao(dados, fat):
    _ler_generica(dados, fat, ["EXECUCAO"], SPEC_EXECUCAO, "execucoes_obra", dados.execucoes,
                  "planilha:faturamento:execucao", exigir_obra=False)


def ler_sigeo(dados, prog):
    _ler_generica(dados, prog, ["EXTRACAO SIGEO"], SPEC_SIGEO, "sigeo_extracoes", dados.sigeo,
                  "planilha:tees:sigeo", exigir_obra=False, ignorar_norm=IGNORAR_SIGEO)


def ler_gerador(dados, prog):
    _ler_generica(dados, prog, ["GERADOR"], SPEC_GERADOR, "geradores_programacao", dados.geradores,
                  "planilha:tees:gerador", exigir_obra=False)


# ---------------------------------------------------------------------------
# PROGRAMACAO (TEES)
# ---------------------------------------------------------------------------
def ler_programacao(dados: Dados, prog: Planilha | None) -> None:
    tab, est = _abrir(prog, dados, ["PROGRAMACAO"], [PROJETO, ["DATA"]], "programacoes (+equipes)")
    if not tab:
        return
    cols = tab.mapear(SPEC_PROGRAMACAO)
    est.colunas_usadas = {k: str(tab.cabecalhos_orig[i]) for k, i in cols.items() if i is not None}
    if cols["equipe"] is None:
        est.erro = "coluna de equipe/encarregado nao encontrada (aliases: EQUIPE, ENCARREGADO): todas as linhas seriam rejeitadas"
        return
    chaves: set = set()
    for num, linha in tab.linhas():
        g = lambda k: pegar(linha, cols[k])  # noqa: E731
        bruto = g("projeto")
        data_bruta = g("data")
        if normalizar_codigo(bruto) is None:
            # Regra do relatorio: linha SEM projeto mas com conteudo e' invalida ("4 sem PROJETO").
            if para_data(data_bruta) is not None or texto_limpo(g("equipe")):
                est.lidas += 1
                dados.rejeitar(est, num, None, "sem projeto")
            else:
                est.sem_projeto += 1
            continue
        wl = _codigo_da_linha(dados, est, num, bruto)
        if wl is None:
            continue
        if wl not in dados.obras:
            dados.rejeitar(est, num, wl, "projeto sem obra", "nao existe em CGO/Carteiras/SIGEO; obra nao e' criada automaticamente")
            continue
        if data_bruta is None or str(data_bruta).strip() == "":
            dados.rejeitar(est, num, wl, "sem data")
            continue
        data = para_data(data_bruta)
        if data is None:
            dados.rejeitar(est, num, wl, "data invalida", str(data_bruta)[:40])
            continue
        pct = para_decimal(g("pct_prog"))
        if pct is not None and not (D0 <= pct <= 1):
            dados.rejeitar(est, num, wl, "% PROG fora de 0-1", str(pct))
            continue
        equipe = texto_limpo(g("equipe"))
        if not equipe:
            dados.rejeitar(est, num, wl, "sem equipe (encarregado)", "Programacao.equipe_id e' obrigatorio")
            continue
        chave_eq = normalizar_chave(equipe)
        chave = (wl, data, chave_eq)
        if chave in chaves:
            dados.rejeitar(est, num, wl, "duplicidade (projeto+data+equipe)")
            continue
        chaves.add(chave)
        dados.equipes.setdefault(chave_eq, equipe[:80])

        bruto_status = texto_limpo(g("status"))
        status = STATUS_PROGRAMACAO.get(normalizar_chave(bruto_status)) if bruto_status else None
        if status is None:
            dados.status_prog_nao_reconhecidos[bruto_status or "(vazio)"] += 1
            status = "Programada"
        turno_bruto = normalizar_chave(texto_limpo(g("turno")) or "")
        turno = "Noturno" if "NOIT" in turno_bruto else "Diurno"
        dados.programacoes.append({
            "wl": wl, "linha": num, "data": data, "equipe_chave": chave_eq, "status": status, "turno": turno,
            "observacoes": texto_limpo(g("observacoes")), "dados_planilha": tab.extras(linha) or None,
        })
        est.aceitas += 1
    est.colunas_nao_mapeadas = tab.nao_mapeadas()


# ---------------------------------------------------------------------------
def ler_planilhas(faturamento: str | Path | None = None, programacao: str | Path | None = None) -> Dados:
    dados = Dados()
    fat = Planilha(faturamento) if faturamento else None
    prog = Planilha(programacao) if programacao else None
    dados.arquivos = [p.nome for p in (fat, prog) if p]
    try:
        ler_obras(dados, fat, prog)          # 1o: define o universo de obras ("mestre")
        ler_arquivo_morto(dados, fat)
        ler_medicao(dados, fat)
        ler_inventario(dados, fat)
        ler_execucao(dados, fat)
        ler_sigeo(dados, prog)
        ler_gerador(dados, prog)
        ler_programacao(dados, prog)
    finally:
        for p in (fat, prog):
            if p:
                p.fechar()
    # A aba EXTRACAO SIGEO e' lida duas vezes (fonte de obras + tabela): nao listar a mesma linha duas vezes.
    vistas, unicas = set(), []
    for r in dados.rejeicoes:
        chave = (r.arquivo, r.aba, r.linha, r.motivo)
        if chave not in vistas:
            vistas.add(chave)
            unicas.append(r)
    dados.rejeicoes = unicas
    return dados
