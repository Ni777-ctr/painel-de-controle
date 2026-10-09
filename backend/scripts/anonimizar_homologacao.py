"""Anonimiza uma COPIA RESTAURADA do banco para uso em homologacao.

>>> NUNCA rode contra producao. <<<
Travas: (1) exige --confirmo-copia-descartavel; (2) o NOME do banco precisa conter
"homolog"; (3) tudo roda em UMA transacao (falhou = nada foi alterado); (4) se o esquema
tiver colunas de texto/JSON ainda nao classificadas abaixo, o script PARA antes de alterar
qualquer coisa (obriga a revisar novas colunas antes de usar dados reais).

O que faz:
  * usuarios: nome/login/e-mail ficticios, senha INUTILIZAVEL (ninguem entra com a senha real),
    2FA, convites e bloqueios zerados; refresh tokens apagados.
  * clientes, fornecedores, empreiteiras, veiculos(placa): nomes, documentos, contatos ficticios.
  * relatorios de supervisao: contato, responsavel, endereco, placa, equipe e fotos anonimizados.
  * textos livres (observacoes, motivos, mensagens...): substituidos por marcador.
  * auditoria: IP, user-agent e antes/depois removidos. JSON bruto de planilhas removido.
  * Nomes que se repetem (contratada, tecnico, responsavel...) viram pseudonimos ESTAVEIS na
    mesma execucao (mesmo valor -> mesmo pseudonimo; sal aleatorio, nao reversivel).
  * Codigos de negocio (WL, projeto, numero PowerOn, regional...) sao PRESERVADOS de proposito,
    para que os testes continuem fazendo sentido -- revise se eles forem sensiveis para voce.

Uso (a partir de backend/; DATABASE_URL = banco de HOMOLOGACAO):
    PYTHONPATH=. python scripts/anonimizar_homologacao.py --confirmo-copia-descartavel --dry-run
    PYTHONPATH=. python scripts/anonimizar_homologacao.py --confirmo-copia-descartavel --criar-usuarios-teste
"""
import argparse
import hashlib
import os
import secrets
import sys
from typing import Any, Callable

from sqlalchemy import JSON, MetaData, String, Text, bindparam, create_engine, delete, insert, select, update, inspect
from sqlalchemy.engine import Engine

from app.database import Base
import app.models  # noqa: F401 -- registra os modelos em Base.metadata
import app.central.models  # noqa: F401 -- esquema central opcional


# ---------------------------------------------------------------------------
# Estrategias
# ---------------------------------------------------------------------------
class Ctx:
    """Estado de uma execucao: sal para pseudonimos estaveis e hash de senha inutilizavel."""

    def __init__(self, senha_hash_inutilizavel: str, salt: bytes | None = None):
        self.salt = salt or os.urandom(16)
        self.senha_hash_inutilizavel = senha_hash_inutilizavel

    def pseudo(self, valor: str) -> str:
        return hashlib.sha256(self.salt + valor.strip().lower().encode()).hexdigest()[:6]


Estrategia = Callable[[Any, Any, Ctx], Any]
MARCADOR = "[removido na anonimizacao]"


def _digitos_cnpj(base12: str) -> str:
    def dv(b: str) -> str:
        pesos = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-len(b):]
        r = sum(int(d) * p for d, p in zip(b, pesos)) % 11
        return "0" if r < 2 else str(11 - r)

    d1 = dv(base12)
    return base12 + d1 + dv(base12 + d1)


def cnpj_sintetico(pk: Any) -> str:
    """CNPJ ficticio (valido nos digitos verificadores), unico por id, formatado."""
    d = _digitos_cnpj(f"{90000000 + int(pk):08d}0001")
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def por_id(prefixo: str) -> Estrategia:
    return lambda pk, v, c: None if v is None else f"{prefixo} {pk}"


def pseudonimo(prefixo: str) -> Estrategia:
    return lambda pk, v, c: None if v in (None, "") else f"{prefixo}-{c.pseudo(str(v))}"


def email_fake(prefixo: str) -> Estrategia:
    return lambda pk, v, c: None if v is None else f"{prefixo}{pk}@homolog.invalid"


def const(valor: Any) -> Estrategia:
    return lambda pk, v, c: valor


def texto_removido(pk, v, c):
    return None if v is None else MARCADOR


def nulo(pk, v, c):
    return None


def cnpj_fake(pk, v, c):
    return None if v in (None, "") else cnpj_sintetico(pk)


def placa_fake(pk, v, c):
    return None if v in (None, "") else f"TST{int(pk):04d}"


def equipe_anonima(pk, v, c):
    if not v:
        return v
    return [{"nome": f"Integrante {i + 1}", "funcao": (it or {}).get("funcao")} for i, it in enumerate(v)]


def parametro_sem_email(pk, v, c):
    """Parametros globais sao JSON: remove qualquer texto com '@' (e-mails de destino), em qualquer nivel."""

    def varrer(x):
        if isinstance(x, str):
            return MARCADOR if "@" in x else x
        if isinstance(x, list):
            return [varrer(i) for i in x]
        if isinstance(x, dict):
            return {k: varrer(i) for k, i in x.items()}
        return x

    return varrer(v)


# tabela -> {coluna: estrategia}. PK padrao = "id" (excecoes em PK_ESPECIAL).
ESTRATEGIAS: dict[str, dict[str, Estrategia]] = {
    'central_setores': {'nome': por_id('Setor'), 'descricao': texto_removido},
    "usuarios": {
        "nome": por_id("Usuario"), "usuario": lambda pk, v, c: f"anon-user-{pk}", "email": email_fake("user"),
        "senha_hash": lambda pk, v, c: c.senha_hash_inutilizavel, "convite_token_hash": nulo,
        "convite_expira_em": nulo, "mfa_secret": nulo, "mfa_habilitado": const(False),
        "notificacoes_email": const(False), "deve_trocar_senha": const(True), "bloqueado_ate": nulo,
        "tentativas_login_falhas": const(0), "ultimo_login_em": nulo,
    },
    "clientes": {
        "nome": por_id("Cliente"), "documento": cnpj_fake, "contato": por_id("Contato cliente"),
        "telefone": lambda pk, v, c: None if v is None else "(00) 00000-0000", "email": email_fake("cliente"),
        "endereco": por_id("Endereco ficticio"),
    },
    "fornecedores": {
        "nome": por_id("Fornecedor"), "documento": cnpj_fake, "contato": por_id("Contato fornecedor"),
        "telefone": lambda pk, v, c: None if v is None else "(00) 00000-0000", "email": email_fake("fornecedor"),
    },
    "empreiteiras": {"nome_razao_social": por_id("Empreiteira"), "cnpj": cnpj_fake, "codigo_contrato": por_id("CT")},
    "relatorios_supervisao": {
        "empreiteira_nome_customizado": pseudonimo("Empreiteira informal"), "contato": por_id("Contato"),
        "responsavel": pseudonimo("Responsavel"), "codigo_placa": placa_fake, "supervisor_beq": pseudonimo("Supervisor"),
        "endereco": por_id("Endereco ficticio"), "composicao_equipe": equipe_anonima, "fotos": nulo,
        "servicos_executados": texto_removido, "pendencias": texto_removido,
    },
    "veiculos": {"placa": placa_fake},
    "audit_logs": {"antes": nulo, "depois": nulo, "ip": nulo, "user_agent": nulo},
    "alertas_financeiros": {"mensagem": texto_removido},
    "notificacoes": {"titulo": texto_removido, "mensagem": texto_removido, "email_erro": nulo},
    "glosas": {"motivo": texto_removido},
    "obras": {"observacoes": texto_removido, "dados_planilha": nulo},
    "programacoes": {"observacoes": texto_removido, "dados_planilha": nulo},
    "historico_status_obra": {"observacao": texto_removido},
    "movimentacoes_estoque": {"observacao": texto_removido},
    "requisicoes_compra": {"observacoes": texto_removido},
    "manutencoes_veiculo": {"descricao": texto_removido, "observacoes": texto_removido},
    "relatorios_gerados": {"filtros": nulo},
    "execucoes_obra": {"empresa": pseudonimo("Empresa"), "observacoes": texto_removido,
                       "motivo_reprova": texto_removido, "dados_extras": nulo},
    "geradores_programacao": {"tecnico_pre_operacao": pseudonimo("Tecnico"), "endereco": por_id("Endereco ficticio"),
                              "link": nulo, "dados_extras": nulo},
    "inventarios_obra": {"tecnico_responsavel": pseudonimo("Tecnico"), "observacao": texto_removido, "dados_extras": nulo},
    "sigeo_extracoes": {"contratada": pseudonimo("Contratada"), "dados_extras": nulo},
    "parametros_globais": {"valor": parametro_sem_email},
}
PK_ESPECIAL = {"parametros_globais": "chave"}
# Tabelas cujas linhas sao apagadas por inteiro (credenciais de sessao).
APAGAR_TABELAS = ("refresh_tokens", 'central_sessoes')

# Colunas de texto/JSON mantidas de proposito (codigos de negocio, status, enums, dados tecnicos).
PRESERVADAS: dict[str, set[str]] = {
    'central_contas': {'cargo', 'estado'},
    'central_vinculos': {'cargo'},
    'central_setores': {'modulos', 'cargos'},
    'central_limites': {'cargo'},
    'central_regras': {'cargo', 'permissao'},
    'central_excecoes': {'permissao'},
    # Estas linhas são apagadas integralmente na cópia de homologação.
    'central_sessoes': {'token_hash', 'csrf'},
    "alertas_financeiros": {"tipo", "nivel"},
    "almoxarifados": {"nome", "regional"},
    "audit_logs": {"bot", "acao", "categoria", "entidade", "entidade_id"},
    "automacoes": {"nome", "gatilho", "acao"},
    "equipe_membros": {"funcao"},
    "equipes": {"nome"},
    "execucoes_automacao": {"status", "mensagem"},
    "execucoes_obra": {"circuito", "familia", "status", "atraso", "intervencao", "obra_eletricamente_concluida",
                       "inventario_aprovado", "medicao", "projeto_codigo", "origem"},
    "faturas": {"status"},
    "geradores_programacao": {"id_origem", "status", "regional", "area", "contratada_propria", "circuito",
                              "equipamento_seccionador", "numero", "projeto_codigo", "origem"},
    "historico_status_obra": {"status_anterior", "status_novo"},
    "inventarios_obra": {"familia", "conclusao", "enviado_faturamento_enel", "status", "ciclo_medicao",
                         "projeto_codigo", "origem"},
    "manutencoes_veiculo": {"tipo", "status"},
    "materiais": {"codigo", "nome", "unidade"},
    "medicoes": {"status", "ciclo_medicao", "area", "familia", "origem"},
    "movimentacoes_estoque": {"tipo"},
    "notificacoes": {"tipo", "modulo", "nivel", "entidade", "entidade_id", "chave_dedup", "email_status"},
    "obras": {"wl", "descricao", "regional", "status"},
    "pagamentos": {"metodo"},
    "parametros_globais": {"chave", "descricao"},
    "pedidos_compra": {"status"},
    "perfis": {"id", "nome", "descricao", "categoria", "permissoes"},
    "pontos_vegetacao": {"descricao", "risco"},
    "programacoes": {"turno", "status", "origem"},
    "refresh_tokens": {"token_hash"},
    "relatorios_gerados": {"tipo", "formato", "nome_arquivo"},
    "relatorios_supervisao": {"projeto_atividade", "ordem", "status", "lv_lm", "bairro", "municipio", "estado"},
    "requisicoes_compra": {"status"},
    "sigeo_extracoes": {"status_programacao", "tipo_intervencao", "numero_poweron", "equipamentos", "horario_inicio",
                        "horario_fim", "projeto_codigo", "origem"},
    "subestacoes": {"nome"},
    "usuarios": {"perfil_id"},
    "veiculos": {"modelo", "tipo", "regional", "status"},
}


# ---------------------------------------------------------------------------
# Travas e cobertura
# ---------------------------------------------------------------------------
def nome_banco(engine_ou_url: Any) -> str:
    url = engine_ou_url.url if hasattr(engine_ou_url, "url") else engine_ou_url
    return (getattr(url, "database", None) or str(url)) or ""


def validar_nome_banco(nome: str) -> None:
    """Trava principal: so roda em banco cujo nome contenha 'homolog'."""
    base = os.path.basename(nome or "").lower()
    if "homolog" not in base:
        raise SystemExit(
            f"RECUSADO: o nome do banco ('{nome}') nao contem 'homolog'. Use um banco separado de homologacao "
            "(ex.: eletrogestor_homolog). Este script nunca deve rodar em producao."
        )


def colunas_nao_classificadas(metadata: MetaData = Base.metadata) -> list[str]:
    """Colunas String/Text/JSON que nao estao nem em ESTRATEGIAS nem em PRESERVADAS."""
    faltando = []
    for tabela in metadata.sorted_tables:
        for col in tabela.columns:
            if not isinstance(col.type, (String, Text, JSON)):
                continue
            if col.name in ESTRATEGIAS.get(tabela.name, {}) or col.name in PRESERVADAS.get(tabela.name, set()):
                continue
            faltando.append(f"{tabela.name}.{col.name}")
    return faltando


# ---------------------------------------------------------------------------
# Execucao
# ---------------------------------------------------------------------------
def anonimizar(engine: Engine, *, dry_run: bool = False, ctx: Ctx | None = None, metadata: MetaData = Base.metadata) -> dict[str, int]:
    """Anonimiza o banco em UMA transacao. Retorna {tabela: linhas_alteradas}."""
    from app.security import hash_senha

    ctx = ctx or Ctx(hash_senha(secrets.token_urlsafe(32)))
    resumo: dict[str, int] = {}
    with engine.connect() as con:
        trans = con.begin()
        try:
            for nome_tabela in APAGAR_TABELAS:
                if nome_tabela in metadata.tables and inspect(con).has_table(nome_tabela):
                    r = con.execute(delete(metadata.tables[nome_tabela]))
                    resumo[nome_tabela] = r.rowcount or 0
            for nome_tabela, cols in ESTRATEGIAS.items():
                if nome_tabela not in metadata.tables or not inspect(con).has_table(nome_tabela):
                    continue
                tabela = metadata.tables[nome_tabela]
                pk = tabela.c[PK_ESPECIAL.get(nome_tabela, "id")]
                nomes = list(cols)
                linhas = con.execute(select(pk, *[tabela.c[n] for n in nomes])).all()
                lote = []
                for linha in linhas:
                    pk_val, valores = linha[0], linha[1:]
                    item = {"b_pk": pk_val}
                    for n, atual in zip(nomes, valores):
                        novo = cols[n](pk_val, atual, ctx)
                        if novo is None and not tabela.c[n].nullable:
                            novo = {} if isinstance(tabela.c[n].type, JSON) else MARCADOR
                        item[f"v_{n}"] = novo
                    lote.append(item)
                if lote:
                    params = {
                        n: bindparam(
                            f"v_{n}", type_=JSON(none_as_null=True) if isinstance(tabela.c[n].type, JSON) else tabela.c[n].type
                        )
                        for n in nomes
                    }
                    con.execute(
                        update(tabela).where(pk == bindparam("b_pk")).values(params), lote
                    )
                resumo[nome_tabela] = len(lote)
            if dry_run:
                trans.rollback()
            else:
                trans.commit()
        except Exception:
            trans.rollback()
            raise
    return resumo


def criar_usuarios_teste(engine: Engine, metadata: MetaData = Base.metadata) -> list[tuple[str, str, str]]:
    """Cria 1 usuario por perfil existente: login 'homolog.<perfil>' com senha ALEATORIA (impressa uma vez).
    Retorna [(login, senha, perfil_id)]. Idempotente: nao recria logins que ja existem."""
    from app.security import hash_senha

    perfis, usuarios = metadata.tables["perfis"], metadata.tables["usuarios"]
    criados: list[tuple[str, str, str]] = []
    with engine.begin() as con:
        existentes = {r[0] for r in con.execute(select(usuarios.c.usuario))}
        for perfil_id, nome in con.execute(select(perfis.c.id, perfis.c.nome)).all():
            login = f"homolog.{perfil_id}"
            if login in existentes:
                continue
            senha = secrets.token_urlsafe(12)
            con.execute(insert(usuarios).values(
                nome=f"Teste {nome}", usuario=login, email=f"{login}@homolog.invalid", senha_hash=hash_senha(senha),
                perfil_id=perfil_id, ativo=True, deve_trocar_senha=True, notificacoes_email=False,
            ))
            criados.append((login, senha, perfil_id))
    return criados


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--confirmo-copia-descartavel", action="store_true", help="obrigatorio: confirma que o banco e' uma copia de homologacao")
    ap.add_argument("--dry-run", action="store_true", help="executa tudo e desfaz (rollback) para ver as contagens")
    ap.add_argument("--criar-usuarios-teste", action="store_true", help="cria homolog.<perfil> com senha aleatoria")
    ap.add_argument("--aceitar-nao-classificadas", action="store_true", help="segue mesmo com colunas de texto nao classificadas (NAO recomendado)")
    args = ap.parse_args()
    if not args.confirmo_copia_descartavel:
        raise SystemExit("RECUSADO: passe --confirmo-copia-descartavel (leia o cabecalho do script).")

    from app.config import get_settings

    url = get_settings().database_url_normalizada
    engine = create_engine(url, future=True)
    validar_nome_banco(nome_banco(engine))
    faltando = colunas_nao_classificadas()
    if faltando and not args.aceitar_nao_classificadas:
        print("PARADO: colunas de texto/JSON ainda nao classificadas (anonimizar ou preservar de proposito):", file=sys.stderr)
        for f in faltando:
            print("  -", f, file=sys.stderr)
        raise SystemExit(2)

    resumo = anonimizar(engine, dry_run=args.dry_run)
    print(("[dry-run - nada foi gravado] " if args.dry_run else "") + f"Banco '{nome_banco(engine)}' anonimizado:")
    for t, n in sorted(resumo.items()):
        print(f"  {t}: {n} linha(s)")
    if args.criar_usuarios_teste and not args.dry_run:
        print("\nUsuarios de teste (guarde as senhas agora; nao serao exibidas de novo; troca obrigatoria no 1o login):")
        for login, senha, perfil in criar_usuarios_teste(engine):
            print(f"  {login}  /  {senha}   (perfil {perfil})")
    print("\nLembrete: confira EMAIL_HABILITADO=false, CORS_ORIGINS e JWT_SECRET_KEY proprios no ambiente de homologacao.")


if __name__ == "__main__":
    main()
