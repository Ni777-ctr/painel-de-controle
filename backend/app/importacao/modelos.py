from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class Rejeicao:
    arquivo: str
    aba: str
    linha: int
    projeto: str | None
    motivo: str
    detalhe: str = ""


@dataclass
class EstatAba:
    arquivo: str
    aba: str
    destino: str
    lidas: int = 0          # linhas com projeto preenchido
    aceitas: int = 0
    rejeitadas: int = 0
    sem_projeto: int = 0    # linhas sem codigo de projeto (totais, separadores) -- nao contam como rejeicao
    colunas_usadas: dict = field(default_factory=dict)
    colunas_nao_mapeadas: list = field(default_factory=list)
    erro: str | None = None


@dataclass
class Dados:
    obras: dict = field(default_factory=dict)          # wl -> campos
    clientes: dict = field(default_factory=dict)       # chave normalizada -> nome
    equipes: dict = field(default_factory=dict)        # chave normalizada -> nome
    medicoes: list = field(default_factory=list)
    inventarios: list = field(default_factory=list)
    execucoes: list = field(default_factory=list)
    sigeo: list = field(default_factory=list)
    geradores: list = field(default_factory=list)
    programacoes: list = field(default_factory=list)
    arquivados: set = field(default_factory=set)
    rejeicoes: list = field(default_factory=list)
    estat: list = field(default_factory=list)
    avisos: Counter = field(default_factory=Counter)
    conflitos: list = field(default_factory=list)      # amostra (ate 200)
    total_conflitos: int = 0
    status_prog_nao_reconhecidos: Counter = field(default_factory=Counter)
    totais_medicao: dict = field(default_factory=dict)
    arquivos: list = field(default_factory=list)

    def rejeitar(self, estat: EstatAba, linha: int, projeto, motivo: str, detalhe: str = "") -> None:
        estat.rejeitadas += 1
        self.rejeicoes.append(Rejeicao(estat.arquivo, estat.aba, linha, None if projeto is None else str(projeto), motivo, detalhe))


D0 = Decimal(0)
