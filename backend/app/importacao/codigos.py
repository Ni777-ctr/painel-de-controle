"""Codigo de projeto (= Obra.wl): normalizacao, validacao (D9) e regional (D8).

Padrao real medido nas planilhas: `DMP/A.SUL.25.00419`
    <SIGLA>/<REGIONAL>.<ANO 2 dig>.<SEQUENCIAL 5 dig>

Codigos fora do padrao (ex.: `DMP/A.SUL25.06647`, `DAC/A,SUL.26.00403`,
`DMP/A.SUL.26.2128`, `DMP/A.SUL.25.007392`, `PROG++`) sao REJEITADOS e listados
(decisao D9: nao corrigir por adivinhacao)."""
import re

PADRAO_CODIGO = re.compile(r"^[A-Z]{2,5}/A\.[A-Z]{2,6}\.\d{2}\.\d{5}$")
# Heuristica so para a aba ARQUIVO MORTO: celula que "parece" um codigo mas esta malformada.
PARECE_CODIGO = re.compile(r"^[A-Z]{2,5}/[A-Z.,]+[.,]?\d")


def normalizar_codigo(valor) -> str | None:
    """Maiusculas e sem NENHUM espaco (inclusive nbsp). None se vazio."""
    if valor is None:
        return None
    texto = "".join(str(valor).split()).upper()
    return texto or None


def codigo_valido(codigo: str | None) -> bool:
    return bool(codigo and PADRAO_CODIGO.match(codigo))


def parece_codigo(texto: str | None) -> bool:
    return bool(texto and PARECE_CODIGO.match(texto))


def regional_do_codigo(codigo: str) -> str | None:
    """`DMP/A.SUL.25.00419` -> `A.SUL`. None se o codigo nao segue o padrao."""
    if not codigo_valido(codigo):
        return None
    return codigo.split("/", 1)[1].rsplit(".", 2)[0]
