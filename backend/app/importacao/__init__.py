"""Importacao das planilhas FATURAMENTO.xlsx e PROGRAMACAO_TEES_-_2026.xlsx.

Uso (CLI):  python -m app.importacao --faturamento F.xlsx --programacao P.xlsx
Por padrao e' SIMULACAO: le as planilhas, valida e gera o relatorio -- nao toca
em banco nenhum. Para gravar: acrescente --confirmar. Veja docs/IMPORTACAO_PLANILHAS.md.
"""
