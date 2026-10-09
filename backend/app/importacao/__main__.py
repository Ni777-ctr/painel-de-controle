"""CLI:  python -m app.importacao --faturamento FATURAMENTO.xlsx --programacao PROGRAMACAO_TEES.xlsx

Sem --confirmar e' SIMULACAO: nao abre conexao com banco nenhum; gera relatorio.md,
relatorio.json e rejeicoes.csv na pasta de saida. Com --confirmar grava (uma transacao)."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from app.importacao import relatorio
from app.importacao.parsers import ler_planilhas


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.importacao", description=__doc__.split("\n\n")[0])
    ap.add_argument("--faturamento", help="caminho do FATURAMENTO.xlsx")
    ap.add_argument("--programacao", help="caminho do PROGRAMACAO_TEES_-_2026.xlsx")
    ap.add_argument("--saida", help="pasta do relatorio (padrao: ./importacao_AAAAMMDD_HHMMSS)")
    ap.add_argument("--confirmar", action="store_true", help="GRAVA no banco (DATABASE_URL). Sem isso, so simula.")
    ap.add_argument("--sobrescrever", action="store_true", help="obras existentes recebem os valores da planilha mesmo se ja preenchidos")
    ap.add_argument("--glosas-pendentes", action="store_true", help="glosas importadas entram como NAO resolvidas (padrao: resolvidas)")
    a = ap.parse_args(argv)

    if not a.faturamento and not a.programacao:
        ap.error("informe --faturamento e/ou --programacao")
    for caminho in (a.faturamento, a.programacao):
        if caminho and not Path(caminho).is_file():
            ap.error(f"arquivo nao encontrado: {caminho}")

    dados = ler_planilhas(a.faturamento, a.programacao)
    aplicado = None
    if a.confirmar:
        from app.database import SessionLocal
        from app.importacao.aplicar import ImportacaoErro, aplicar

        db = SessionLocal()
        try:
            aplicado = aplicar(db, dados, sobrescrever=a.sobrescrever, glosas_resolvidas=not a.glosas_pendentes)
            db.commit()
        except ImportacaoErro as exc:
            db.rollback()
            print(f"IMPORTACAO ABORTADA (nada foi gravado): {exc}", file=sys.stderr)
            return 2
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    pasta = a.saida or f"importacao_{datetime.now():%Y%m%d_%H%M%S}"
    relatorio.gravar(dados, aplicado, pasta)
    r = relatorio.resumo_dict(dados, aplicado)
    print(f"{r['modo']}: {r['universo_obras']} obras, {r['medicoes']} medicoes, {r['programacoes']} programacoes, "
          f"{r['inventarios']} inventarios, {r['execucoes']} execucoes, {r['sigeo']} sigeo, {r['geradores']} geradores; "
          f"{r['rejeicoes_total']} linhas rejeitadas. Relatorio em: {pasta}/")
    erros = [e for e in dados.estat if e.erro]
    for e in erros:
        print(f"  ! {e.aba}: {e.erro}", file=sys.stderr)
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
