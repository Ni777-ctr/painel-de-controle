# API de Supervisão (v1.3)

Módulo de **empreiteiras** e **relatórios diários de campo**. Sem prefixo global (como os demais módulos): `/supervisao/...`.
Documentação interativa: `/docs` (quando `DOCS_HABILITADO=true`). Este arquivo é o contrato para o frontend.

## Autenticação e permissões

- `Authorization: Bearer <access_token>` (JWT do `POST /auth/login`, o mesmo dos outros módulos).
- Usuário com `deve_trocar_senha`/senha expirada recebe `senha_pendente: true` no login e precisa passar por `POST /auth/trocar-senha-obrigatoria` antes de obter o token.
- **`supervisao:read`**: todos os `GET`. **`supervisao:write`**: `POST`, `PUT`, `PATCH`, `DELETE`. Perfil com `*` tem tudo. Escrever **não** implica ler (perfil só com `write` não lista).

| Perfil | read | write |
|---|---|---|
| administrador, desenvolvedor, tester (`*`) | ✔ | ✔ |
| supervisor | ✔ | ✔ |
| gerencia-geral | ✔ | — |
| qualidade | ✔ | — |
| demais perfis | — | — |

Erros comuns: `401` sem token/token inválido · `403` sem permissão (`"Seu perfil nao tem permissao para esta acao."`, registrado na auditoria como `acesso_negado`) · `404` não encontrado · `409` conflito · `422` validação.

## Empreiteiras — `/supervisao/empreiteiras`

Objeto `Empreiteira`:

| Campo | Tipo | Regras |
|---|---|---|
| `id` | int | somente resposta |
| `nome_razao_social` | string 1–160 | obrigatório; espaços das pontas removidos |
| `cnpj` | string \| null | opcional. Aceita com ou sem máscara; **precisa ter 14 dígitos e dígitos verificadores válidos** (senão `422`). Gravado e devolvido **formatado** `00.000.000/0000-00`. **Único** (duplicado → `409`). `""`/`null` = sem CNPJ |
| `codigo_contrato` | string \| null | até 60 |
| `ativo` | bool | padrão `true` |
| `criado_em` | datetime ISO | somente resposta |

| Método e caminho | Perm. | Descrição |
|---|---|---|
| `GET /supervisao/empreiteiras` | read | Lista ordenada por nome (sem paginação). Filtros: `ativo` (bool) · `q` (texto no nome, CNPJ ou código do contrato; busca literal, `%` e `_` não são curingas; o CNPJ é buscado **como gravado, com máscara**, ex.: `11.444`) |
| `POST /supervisao/empreiteiras` | write | Cria → `201` com o objeto. `409` se CNPJ já existe |
| `GET /supervisao/empreiteiras/{id}` | read | `404` se não existe |
| `PATCH /supervisao/empreiteiras/{id}` | write | Atualização **parcial** (só os campos enviados). `nome_razao_social: null` e `ativo: null` → `422`. `409` se o CNPJ pertence a outra |
| `DELETE /supervisao/empreiteiras/{id}` | write | `204`. **`409` se houver relatórios vinculados** — use `PATCH {"ativo": false}` para desativar |

## Relatórios — `/supervisao/relatorios`

Objeto `RelatorioSupervisao` (entrada e saída; campos extras só na resposta):

| Campo | Tipo | Regras |
|---|---|---|
| `data_relatorio` | date `YYYY-MM-DD` | **obrigatório** |
| `projeto_atividade` | string ≤200 \| null | |
| `ordem` | string ≤60 \| null | |
| `status` | enum | `"Concluído"` (**com acento**), `"Parcial"`, `"Cancelado"`, `"Sem status"` (padrão) |
| `porcentagem_execucao` | int 0–100 \| null | |
| `empreiteira_id` | int \| null | se informado, precisa existir (senão `422`) |
| `empreiteira_nome_customizado` | string ≤160 \| null | texto livre para empreiteira ainda não cadastrada |
| `contato`, `responsavel`, `supervisor_beq` | string ≤120 \| null | |
| `lv_lm` | string ≤20 \| null | |
| `codigo_placa` | string ≤40 \| null | |
| `endereco` | string ≤255 \| null · `bairro`, `municipio` ≤120 | |
| `estado` | string 2 letras \| null | convertido para maiúsculas (`sp` → `SP`) |
| `composicao_equipe` | `[{"nome": string 1–120, "funcao": string ≤80 \| null}]` \| null | |
| `servicos_executados`, `pendencias` | texto \| null | |
| `horario_saida_base`, `horario_chegada_obra`, `horario_saida_obra`, `horario_chegada_base` | time `HH:MM[:SS]` \| null | |
| `fotos` | `[{"url": string, "legenda": string ≤300 \| null}]` \| null | `url` deve começar com `http://`, `https://` ou `/` (caminho do sistema). Rejeitados: `javascript:`, `data:`, `//host`, barra invertida, quebras de linha |
| *resposta:* `id`, `empreiteira_nome`, `criado_por_id`, `criado_em`, `atualizado_em` | | `empreiteira_nome` = nome da empreiteira cadastrada, ou o customizado se não houver cadastro |

> As fotos são **referências (URL)**. O backend não recebe upload de arquivo neste módulo.

| Método e caminho | Perm. | Descrição |
|---|---|---|
| `GET /supervisao/relatorios` | read | Lista com filtros e paginação (abaixo). Ordem fixa: `data_relatorio` desc, `id` desc |
| `POST /supervisao/relatorios` | write | Cria → `201`. `criado_por_id` = usuário do token |
| `GET /supervisao/relatorios/{id}` | read | `404` se não existe |
| `PUT /supervisao/relatorios/{id}` | write | **Substitui o relatório inteiro**: campo omitido volta ao padrão/nulo. Envie o objeto completo (faça `GET`, altere, `PUT`). Não existe `PATCH` nem `DELETE` de relatório |

Filtros de `GET /supervisao/relatorios` (todos opcionais, combináveis com **E**):

| Parâmetro | Tipo | Efeito |
|---|---|---|
| `data` | date | dia exato |
| `data_inicio`, `data_fim` | date | intervalo inclusivo; `inicio > fim` → `422` |
| `municipio`, `responsavel` | texto | contém, sem diferenciar maiúsculas |
| `status` | enum | um dos 4 valores (outro → `422`) |
| `empreiteira_id` | int | empreiteira exata |
| `empreiteira` | texto | contém no nome da empreiteira cadastrada **ou** no nome customizado |
| `limite` | int 1–500 (padrão 100) · `offset` ≥ 0 | paginação. **Não há contagem total**: se vierem `limite` itens, peça a próxima página |

Todos os textos de busca são tratados como **literais** (`%`, `_`, `'`, `;` não têm efeito especial); filtros usam parâmetros ligados, sem SQL montado por texto.

## Auditoria

Toda escrita gera um registro (visível em `/auditoria`, categorias existentes: `alteracao`, `exclusao`...). Leituras não geram.

| Ação | Quando | Dados |
|---|---|---|
| `empreiteira_criada` | POST | `depois`: nome, cnpj |
| `empreiteira_atualizada` | PATCH | `antes`/`depois` só dos campos alterados |
| `empreiteira_excluida` | DELETE | `antes`: nome, cnpj |
| `relatorio_supervisao_criado` | POST | `depois`: data, projeto, status |
| `relatorio_supervisao_atualizado` | PUT | `antes`/`depois` só dos campos que mudaram |

## Exemplos

```http
POST /supervisao/empreiteiras
{"nome_razao_social": "Alfa Construções Ltda", "cnpj": "11444777000161", "codigo_contrato": "CT-100"}
→ 201 {"id": 1, "nome_razao_social": "Alfa Construções Ltda", "cnpj": "11.444.777/0001-61",
       "codigo_contrato": "CT-100", "ativo": true, "criado_em": "2026-10-08T03:10:00Z"}

POST /supervisao/relatorios
{"data_relatorio": "2026-10-05", "projeto_atividade": "DMP/A.SUL.25.00419", "status": "Parcial",
 "porcentagem_execucao": 40, "empreiteira_id": 1, "municipio": "Santo André", "estado": "sp",
 "composicao_equipe": [{"nome": "Maria", "funcao": "Eletricista"}], "horario_saida_base": "07:30:00",
 "fotos": [{"url": "https://exemplo.com/f1.jpg", "legenda": "Antes"}]}
→ 201 {"id": 1, ..., "estado": "SP", "empreiteira_nome": "Alfa Construções Ltda", "criado_por_id": 7, ...}

GET /supervisao/relatorios?data_inicio=2026-10-01&data_fim=2026-10-31&status=Parcial&municipio=santo&limite=20
DELETE /supervisao/empreiteiras/1   → 409 {"detail": "Empreiteira possui relatorios vinculados e nao pode ser excluida; desative-a (ativo=false)."}
```

## Notas para o frontend

- `status` usa o texto exato com acento (`"Concluído"`); URL-encode no query string (`status=Conclu%C3%ADdo`).
- Mensagens de erro de validação (`422`) seguem o formato padrão FastAPI (`detail` = lista de `{loc, msg, type}`); erros de regra de negócio (`404`, `409`, `403`) trazem `detail` em texto.
- CORS: a origem do frontend precisa estar em `CORS_ORIGINS` do backend (com `allow_credentials`).
- Horários são "hora de parede" sem fuso (`HH:MM:SS`); `criado_em`/`atualizado_em` são datetimes ISO.
