# Importação das planilhas (FATURAMENTO.xlsx + PROGRAMAÇÃO_TEES)

Implementa o que o *Relatório de análise das planilhas (etapa 1)* mediu. **Por padrão é uma simulação**: lê, valida
e gera relatório, sem abrir conexão com banco algum.

```bash
# 1) Simulação (não grava nada) -> pasta com relatorio.md, relatorio.json e rejeicoes.csv
python -m app.importacao --faturamento FATURAMENTO.xlsx --programacao "PROGRAMAÇÃO_TEES_-_2026.xlsx"

# 2) Banco migrado e simulação conferida? Então grave (uma transação; falhou = nada é gravado)
alembic upgrade head
python -m app.importacao --faturamento FATURAMENTO.xlsx --programacao "PROGRAMAÇÃO_TEES_-_2026.xlsx" --confirmar
```
Opções: `--saida PASTA`, `--sobrescrever` (obras existentes recebem os valores da planilha mesmo se já preenchidos),
`--glosas-pendentes` (glosas entram como não resolvidas). Código de saída `1` se alguma aba deu erro de leitura.

> **Rode a simulação primeiro e confira `relatorio.md`**: ele mostra por aba quantas linhas entraram/foram rejeitadas,
> a conciliação do total da MEDIÇÃO (compare com R$ 1.555.657,49 e R$ 1.915.635,38 do relatório de análise), os códigos
> fora do padrão, os status de programação não reconhecidos e quais colunas foram mapeadas.

## Decisões adotadas (D1–D10) — padrão assumido e onde mudar

| Decisão | O que o código faz | Para mudar |
|---|---|---|
| **D1a** Fatura | **Não cria Fatura** (a planilha não tem vencimento nem nº de NF). Valor faturado, NF emitida e data ficam na própria **Medição** (`valor_faturado`, `emitida_nf`, `data_emissao_nf`). | Criar faturas exige decidir o vencimento; não inventei. |
| **D1b** Glosa | Uma `Glosa` por medição com subtotal > 0, motivo fixo **"Importado da planilha, sem motivo informado"**, **resolvida** (o valor já foi descontado; evita ~93 alertas falsos). | `--glosas-pendentes` |
| **D1c** NECs | `necs_*` viraram `Numeric(14,3)` (obras, medições, faturas). **Nada é arredondado.** | — (migration 0009) |
| **D1d** Status | Medições entram como **Rascunho** (a planilha não diz se foi aprovada). Só medições *Aprovadas* contam na meta mensal, então o histórico não polui o mês atual. `criado_em` = data de emissão da NF quando existe. | `parsers.py` / `aplicar.py` |
| **D2** Clientes | Só nomes reais da coluna Cliente (dedup sem acento/caixa). `-` e vazio → obra sem cliente. **ENEL não é criado.** | — |
| **D3** Equipes | Uma por nome de encarregado (coluna EQUIPE da Programação), sem membros. | — |
| **D4** MONITORAMENTO | **Não importado**: o relatório não lista as colunas dessa aba. Envie o layout para incluir. | — |
| **D5** Tabelas novas | Criadas: `inventarios_obra`, `execucoes_obra`, `sigeo_extracoes`, `geradores_programacao` (migration 0009). Guardam o código mesmo **sem obra** (obra_id nulo) — exceto Inventário, que exige obra. | — |
| **D6** ARQUIVO MORTO | `Obra.arquivada = true` (novo campo; o enum `status` não foi mexido). Obras arquivadas saem dos alertas. Códigos arquivados sem obra são só contados. | — |
| **D7** Abas ocultas | **Fora** (MANUTENÇÃO 2024 e PROG. NOITE NOVO têm layout antigo/ não documentado). | — |
| **D8** Regional | Lida do código (`DMP/A.SUL.25.00419` → `A.SUL`). | `codigos.py` |
| **D9** Códigos fora do padrão | **Rejeitados e listados** em `rejeicoes.csv` (nenhuma correção por adivinhação). Padrão: `SIGLA/A.REGIONAL.AA.NNNNN`. | `PADRAO_CODIGO` em `codigos.py` |
| **D10** Pré-APR | Fora do escopo desta etapa (continua pendente). | — |

## Regras de importação (do relatório)

- **Universo de obras** = CGO ∪ CARTEIRA SOT ∪ CARTEIRA DE OBRAS ∪ EXTRAÇÃO SIGEO (a CGO do arquivo de programação não é relida: é a mesma). Prioridade de valores: **CGO > SOT > Obras**; divergências entre fontes são contadas e amostradas no relatório.
- **Medição, Programação e Inventário só entram se a obra existir** → senão vão para `rejeicoes.csv` ("projeto sem obra"); **obra nunca é criada automaticamente a partir delas**.
- **MEDIÇÃO**: valores em texto (`R$ 1.484,10`) são lidos; `#N/A`/`;` viram vazio; nos itens "simplificados" a família que veio na coluna *Área* é movida para *Família*; `percentual` = NEC faturada ÷ NEC orçado (0 se não houver orçado); duplicidade projeto+ciclo é rejeitada; `Obra.necs_faturados` = soma das NECs faturadas importadas.
- **PROGRAMAÇÃO**: rejeita sem projeto, sem data, data inválida, `% PROG` fora de 0–1, sem equipe, duplicidade (projeto+data+equipe), código fora do padrão. As ~15 colunas sem campo no banco ficam em `dados_planilha`. Status desconhecido → `Programada` (e listado no relatório). **Programação com mais de 30 dias não gera alerta** (histórico importado não vira notificação).
- **Colunas sem campo próprio** (contrato, circuito, status SAP, etc.) ficam em `obras.dados_planilha` (por aba de origem) e `dados_extras` — nada é descartado.
- **Reimportar é seguro**: clientes/equipes/obras são *upsert* (obra existente só recebe campos **vazios**; edição manual é preservada); medições, glosas, programações e as 4 tabelas novas importadas são **substituídas** (só as de `origem = planilha:*`). Se já existir fatura ligada a uma medição importada, a reimportação é **abortada** antes de apagar qualquer coisa.

## O que NÃO foi feito (e por quê)
- **Estoque/almoxarifado, Faturas, Pagamentos, vencimentos, nº de NF, motivo de glosa**: as planilhas não têm esses dados; nada foi inventado.
- **PROGRAM, WIP, CONSOLIDADO, KPI, dashboards/pivôs, LOCALIZAÇÃO, BACKLOG**: duplicados/derivados (conforme o relatório).
- **Validação com os arquivos reais**: este código foi testado com planilhas **sintéticas** que reproduzem os problemas medidos. Os cabeçalhos exatos de algumas abas (principalmente PROGRAMAÇÃO, EXECUCAO, INVENTARIO e GERADOR) não estavam no relatório; o importador usa nomes prováveis e **informa no relatório quais colunas mapeou e quais guardou como extras** — se algo estiver no lugar errado, é um ajuste de uma linha em `parsers.py` (dicionários `SPEC_*`). Uma aba/coluna obrigatória ausente **não é adivinhada**: vira erro explícito no relatório.
