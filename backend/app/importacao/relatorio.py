"""Relatorio da importacao: Markdown legivel + JSON + CSV de rejeicoes."""
import csv
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.importacao.modelos import Dados


def brl(valor) -> str:
    d = Decimal(valor or 0)
    return "R$ " + f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo_dict(dados: Dados, aplicado: dict | None) -> dict:
    t = dados.totais_medicao or {}
    lido_total = (t.get("lido_numerico", 0) or 0) + (t.get("lido_texto", 0) or 0)
    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "modo": "GRAVADO NO BANCO" if aplicado is not None else "SIMULACAO (nada foi gravado)",
        "arquivos": dados.arquivos,
        "universo_obras": len(dados.obras),
        "obras_por_fonte": dict(Counter(f for o in dados.obras.values() for f in set(o["fontes"]))),
        "clientes": len(dados.clientes), "equipes": len(dados.equipes),
        "medicoes": len(dados.medicoes), "glosas": sum(1 for m in dados.medicoes if m["glosado"]),
        "programacoes": len(dados.programacoes), "inventarios": len(dados.inventarios),
        "execucoes": len(dados.execucoes), "sigeo": len(dados.sigeo), "geradores": len(dados.geradores),
        "obras_a_arquivar": len(dados.arquivados & set(dados.obras)),
        "arquivo_morto_sem_obra": len(dados.arquivados - set(dados.obras)),
        "rejeicoes_total": len(dados.rejeicoes),
        "rejeicoes_por_motivo": {f"{a} | {m}": n for (a, m), n in Counter((r.aba, r.motivo) for r in dados.rejeicoes).items()},
        "conflitos_entre_fontes": dados.total_conflitos,
        "medicao_totais": {
            "valor_lido_somente_numerico": str(t.get("lido_numerico", 0)),
            "valor_lido_em_texto": str(t.get("lido_texto", 0)),
            "celulas_em_texto": t.get("celulas_texto", 0),
            "valor_lido_total": str(lido_total),
            "valor_das_medicoes_aceitas": str(t.get("aceito", 0)),
            "nf_sim_sem_data": t.get("nf_sim_sem_data", 0),
            "celulas_de_erro_na_coluna_valor": t.get("celulas_erro", 0),
        },
        "status_programacao_nao_reconhecidos": dict(dados.status_prog_nao_reconhecidos.most_common(30)),
        "avisos": dict(dados.avisos),
        "abas": [e.__dict__ for e in dados.estat],
        "gravado": aplicado,
    }


def markdown(dados: Dados, aplicado: dict | None) -> str:
    r = resumo_dict(dados, aplicado)
    L = [f"# Importacao de planilhas - {r['modo']}", "", f"Gerado em {r['gerado_em']} - arquivos: {', '.join(r['arquivos']) or '-'}", ""]
    L += ["## Resumo", "", "| Item | Qtde |", "|---|---:|"]
    for k, v in (("Obras (universo)", r["universo_obras"]), ("Clientes (nomes reais)", r["clientes"]),
                 ("Equipes (encarregados)", r["equipes"]), ("Medicoes", r["medicoes"]), ("Glosas", r["glosas"]),
                 ("Programacoes", r["programacoes"]), ("Inventarios", r["inventarios"]), ("Execucoes", r["execucoes"]),
                 ("Extracoes SIGEO", r["sigeo"]), ("Geradores", r["geradores"]), ("Obras a arquivar", r["obras_a_arquivar"]),
                 ("Arquivo morto sem obra", r["arquivo_morto_sem_obra"]), ("**Linhas rejeitadas**", r["rejeicoes_total"]),
                 ("Conflitos de valor entre fontes", r["conflitos_entre_fontes"])):
        L.append(f"| {k} | {v} |")

    L += ["", "## Abas lidas", "", "| Arquivo | Aba | Destino | Com projeto | Aceitas | Rejeitadas | Sem projeto | Erro |", "|---|---|---|---:|---:|---:|---:|---|"]
    for e in dados.estat:
        L.append(f"| {e.arquivo} | {e.aba} | {e.destino} | {e.lidas} | {e.aceitas} | {e.rejeitadas} | {e.sem_projeto} | {e.erro or ''} |")

    erros = [e for e in dados.estat if e.erro]
    if erros:
        L += ["", "## ATENCAO: abas com erro (nao importadas)", ""] + [f"- **{e.aba}**: {e.erro}" for e in erros]

    t = r["medicao_totais"]
    L += ["", "## Conciliacao da aba MEDICAO (Valor faturado)", "",
          f"- Soma so das celulas numericas: **{brl(t['valor_lido_somente_numerico'])}**",
          f"- Soma dos valores que estavam como texto ({t['celulas_em_texto']} celulas): **{brl(t['valor_lido_em_texto'])}**",
          f"- Total lido (numerico + texto): **{brl(t['valor_lido_total'])}**",
          f"- Total das medicoes aceitas: {brl(t['valor_das_medicoes_aceitas'])}",
          f"- Linhas com NF = Sim e sem data de emissao: {t['nf_sim_sem_data']}",
          f"- Celulas de erro (#N/A etc.) na coluna de valor: {t['celulas_de_erro_na_coluna_valor']}",
          "", "_Compare com o relatorio de analise: R$ 1.555.657,49 (so numericos) e R$ 1.915.635,38 (com texto)._"]

    if dados.rejeicoes:
        L += ["", "## Rejeicoes por motivo", "", "| Aba | Motivo | Qtde |", "|---|---|---:|"]
        for (aba, motivo), n in sorted(Counter((x.aba, x.motivo) for x in dados.rejeicoes).items()):
            L.append(f"| {aba} | {motivo} | {n} |")
        L += ["", "Lista completa em `rejeicoes.csv`."]
        invalidos = sorted({x.projeto for x in dados.rejeicoes if x.motivo == "codigo fora do padrao" and x.projeto})
        if invalidos:
            L += ["", "### Codigos fora do padrao (amostra)", ""] + [f"- `{c}`" for c in invalidos[:40]]

    if dados.status_prog_nao_reconhecidos:
        L += ["", "## Status de programacao nao reconhecidos (importados como 'Programada')", "", "| Valor na planilha | Qtde |", "|---|---:|"]
        L += [f"| {v} | {n} |" for v, n in dados.status_prog_nao_reconhecidos.most_common(20)]
        L += ["", "_Ajuste `STATUS_PROGRAMACAO` em `app/importacao/parsers.py` se algum desses tem significado conhecido._"]

    if dados.conflitos:
        L += ["", f"## Conflitos entre fontes (amostra de {len(dados.conflitos)} de {dados.total_conflitos}; vale a primeira fonte: CGO > SOT > Obras)", "",
              "| Projeto | Campo | Mantido | Ignorado | Fonte ignorada |", "|---|---|---|---|---|"]
        L += [f"| {c['projeto']} | {c['campo']} | {c['mantido']} | {c['ignorado']} | {c['fonte']} |" for c in dados.conflitos[:30]]

    if dados.avisos:
        L += ["", "## Avisos", ""] + [f"- {k}: {v}" for k, v in dados.avisos.items()]

    L += ["", "## Colunas encontradas e mapeadas / nao mapeadas", ""]
    for e in dados.estat:
        if e.colunas_usadas or e.colunas_nao_mapeadas:
            L.append(f"**{e.aba}** ({e.destino})")
            L.append("- mapeadas: " + (", ".join(f"{k}<-{v}" for k, v in e.colunas_usadas.items()) or "-"))
            nm = e.colunas_nao_mapeadas
            L.append(f"- guardadas em dados extras ({len(nm)}): " + (", ".join(nm[:60]) + (" ..." if len(nm) > 60 else "") if nm else "-"))
            L.append("")

    if aplicado is not None:
        L += ["## Gravado no banco", ""] + [f"- {k}: {v}" for k, v in aplicado.items()]
    return "\n".join(L) + "\n"


def gravar(dados: Dados, aplicado: dict | None, pasta: str | Path) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "relatorio.md").write_text(markdown(dados, aplicado), encoding="utf-8")
    (pasta / "relatorio.json").write_text(json.dumps(resumo_dict(dados, aplicado), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with open(pasta / "rejeicoes.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["arquivo", "aba", "linha", "projeto", "motivo", "detalhe"])
        for x in dados.rejeicoes:
            w.writerow([x.arquivo, x.aba, x.linha, x.projeto or "", x.motivo, x.detalhe])
    return pasta
