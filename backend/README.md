# EletroGestor — Backend

API REST em **FastAPI + SQLAlchemy + Alembic**, compatível com **SQLite**
(desenvolvimento local, sem instalar nada além do Python) e **PostgreSQL**
(produção). O frontend (`../src`, TanStack Start) já é construído esperando
estes endpoints — veja `../src/lib/api.ts`.

## Stack

- **FastAPI** (rotas, validação via Pydantic v2)
- **SQLAlchemy 2.0** (modelos/ORM) — SQLite em dev, PostgreSQL em produção
- **Alembic** (migrations, testadas nos dois dialetos)
- **JWT** (`python-jose`) + **bcrypt** (`passlib`) para autenticação
- **pyotp** para 2FA (TOTP, compatível com Google Authenticator/Authy)
- RBAC por perfil (tabela `perfis`, campo `permissoes`) + permissões
  granulares por transição de status (`obras:transicao:*`, `compras:transicao:*`)
- **pytest** para testes de regressão (`tests/`)

## Estrutura

```
backend/
├── app/
│   ├── main.py            # cria o FastAPI app e inclui os routers
│   ├── config.py          # variáveis de ambiente (.env)
│   ├── database.py        # engine/sessão SQLAlchemy
│   ├── security.py        # hash de senha, JWT, TOTP
│   ├── deps.py             # get_current_user, requer_permissao/tem_permissao (RBAC)
│   ├── auditoria_utils.py  # helper para gravar AuditLog
│   ├── models/             # um arquivo por domínio (SQLAlchemy)
│   ├── schemas/            # um arquivo por domínio (Pydantic)
│   ├── routers/             # um arquivo por domínio (endpoints)
│   ├── services/             # regras de negócio (pendências, notificações, relatórios, e-mail...)
│   ├── jobs/                 # rotinas agendadas (cron): notificações
│   ├── middleware.py         # request-id, IP/UA, HTTPS, cabeçalhos de segurança, access log
│   └── observabilidade.py    # logging estruturado + Sentry opcional
├── alembic/                  # migrations (0001 a 0009)
├── seeds/seed.py               # dados fictícios + usuários de teste
├── tests/                       # suíte pytest
├── Dockerfile / render.yaml      # publicação (Render) — ver docs/PUBLICACAO.md
├── scripts/backup_pg.sh          # backup + rotação do PostgreSQL
├── requirements.txt              # dependências de produção
├── requirements-dev.txt           # + pytest/httpx, para rodar os testes
└── .env.example
```

## Domínios implementados

| Domínio | Endpoints principais |
|---|---|
| Autenticação | `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me` |
| Senha (convite, troca, expiração) | `/auth/convite`, `/auth/definir-senha`, `/auth/trocar-senha`, `/auth/trocar-senha-obrigatoria` |
| 2FA (TOTP) | `/auth/mfa/iniciar`, `/auth/mfa/confirmar`, `/auth/mfa/validar`, `/auth/mfa/desabilitar` |
| Bloqueio de conta | `/auth/usuarios/{id}/desbloquear` |
| Usuários / Perfis / Permissões | `/usuarios`, `/perfis` |
| Clientes | `/clientes` |
| Equipes | `/equipes`, `/equipes/{id}/membros` |
| Obras (entidade central) | `/obras`, `/obras/{id}/resumo` |
| Programação de obras | `/programacao` |
| Estoque / Almoxarifado | `/materiais`, `/almoxarifados`, `/estoque`, `/estoque/movimentacoes` |
| Fornecedores / Compras | `/fornecedores`, `/requisicoes-compra`, `/pedidos-compra` |
| Medições / Faturas / Pagamentos / Cobrança | `/medicoes`, `/faturas`, `/pagamentos`, `/cobranca/resumo` |
| Frota | `/veiculos`, `/veiculos/{id}/manutencoes`, `/manutencoes/{id}` |
| **Painel unificado** (gerência) | `GET /painel/gerencia` |
| **Notificações** (sino + e-mail) | `/notificacoes`, `/notificacoes/contagem`, `/notificacoes/{id}/lida`, `/notificacoes/marcar-todas-lidas`, `/notificacoes/preferencias`, `POST /notificacoes/processar` |
| **Busca global** | `GET /busca?q=` |
| **Relatórios Excel/PDF** | `/relatorios/tipos`, `/relatorios/exportar/{tipo}`, `/relatorios/historico` |
| **Histórico do sistema** (auditoria) | `/auditoria`, `/auditoria/pagina`, `/auditoria/resumo` |
| Parâmetros globais | `/parametros` |
| Automações (genérico + rede elétrica) | `/automacoes`, `/automacoes/{id}/execucoes`, `/automacao/painel`, `/automacao/self-healing/indicadores`, `/subestacoes/{id}/status`, `/vegetacao/pontos-criticos` |
| Dashboard / Relatórios | `/dashboard`, `/relatorios/resumo-diario` |

Todas as rotas (exceto `/auth/login`, `/auth/refresh`, `/auth/mfa/validar`,
`/auth/trocar-senha-obrigatoria`, `/auth/definir-senha`, `/`, `/saude`,
`/docs`) exigem um token JWT (`Authorization: Bearer <token>`) e checam a
permissão do perfil do usuário logado — **o RBAC é sempre aplicado no
backend**, nunca apenas no frontend.

## Rodando localmente

### Opção A — SQLite (mais rápido, nada para instalar além do Python)

Use isso para desenvolvimento do dia a dia.

**Linux/macOS:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # inclui pytest, além das deps de producao
cp .env.example .env
```
Edite o `.env` e troque a linha `DATABASE_URL` por:
```
DATABASE_URL=sqlite:///./dev.db
```
```bash
alembic upgrade head
PYTHONPATH=. python seeds/seed.py
uvicorn app.main:app --reload --port 8000
```

**Windows (PowerShell ou CMD), Python 3.12:**
```bat
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```
Edite o `.env` (Bloco de Notas) e troque `DATABASE_URL` por
`sqlite:///./dev.db`. Depois:
```bat
alembic upgrade head
set PYTHONPATH=.
python seeds\seed.py
uvicorn app.main:app --reload --port 8000
```

### Opção B — PostgreSQL (recomendado antes de ir para produção)

Via Docker (mais simples — sobe um Postgres já configurado):
```bash
docker compose up -d db
```
(usa o `docker-compose.yml` na raiz do `backend/`, credenciais de
desenvolvimento apenas — nunca use essas credenciais em produção).

Ou via `psql` local:
```bash
createdb eletrogestor
createuser eletrogestor --pwprompt
```

Depois, com o `.env` apontando para
`DATABASE_URL=postgresql+psycopg2://eletrogestor:eletrogestor@localhost:5432/eletrogestor`
(valor padrão do `.env.example`), rode os mesmos passos de migrations/seed/uvicorn
acima (Linux/macOS ou Windows).

### Rodando os testes

```bash
pytest -q
```
(precisa de `requirements-dev.txt` instalado; os testes usam SQLite em
memória, não tocam no seu `.env`/banco real).

### Conectar o frontend

No diretório raiz do projeto (frontend), crie/edite o `.env` com:
```
VITE_API_URL=http://localhost:8000
```
O backend já libera CORS para `http://localhost:8081` (onde o Codex roda o
frontend hoje), além de `5173`/`3000`, via `CORS_ORIGINS` no `.env` — ajuste
essa variável para a URL real em produção, **nunca hardcode no código**.

## Fluxo de autenticação (para o frontend implementar)

1. **Login** — `POST /auth/login` com `{ usuario, senha }`. A resposta pode
   vir em 3 formatos, nesta ordem de prioridade:
   - `senha_pendente: true` — senha temporária (primeiro acesso) ou expirada
     pela regra de validade (parâmetro `senha_validade_dias`, 180 dias por
     padrão). Chame `POST /auth/trocar-senha-obrigatoria` com
     `{ senha_pendente_token, nova_senha }` — a resposta já traz os tokens
     finais (não precisa logar de novo).
   - `mfa_pendente: true` — 2FA habilitado. Chame `POST /auth/mfa/validar`
     com `{ mfa_token, codigo }`.
   - `mfa_configuracao_pendente: true` — (só com `MFA_OBRIGATORIO_ENFORCE=true`)
     perfil sensível sem 2FA: **nenhuma sessão é emitida**. Use
     `mfa_setup_token` como Bearer **apenas** em `POST /auth/mfa/iniciar` e
     `POST /auth/mfa/confirmar` (QR code + 1º código) e depois faça login de
     novo (cairá em `mfa_pendente`). Em qualquer outra rota esse token dá 401.
   - Nenhum dos três: `access_token` + `refresh_token` já vêm prontos.
   - Erros: `429` (muitas tentativas do mesmo IP; respeite `Retry-After`),
     `401` (usuário/senha inválidos), `423` (conta bloqueada — a
     mensagem `detail` informa até quando), `403` (convite de senha ainda
     não aceito).
2. **Guardar sessão** — guarde `access_token`/`refresh_token` em memória
   (contexto React) ou em cookie `httpOnly`; evite `localStorage` puro sem
   expiração. Envie `Authorization: Bearer <access_token>` em toda chamada.
3. **Renovar token** — `POST /auth/refresh` com `{ refresh_token }` antes do
   access token expirar (~8h por padrão). A resposta rotaciona o refresh
   token (o antigo é revogado) — sempre substitua os dois.
4. **Logout** — `POST /auth/logout` com `{ refresh_token }`.
5. **Usuário/perfil/permissões** — `GET /auth/me` retorna o usuário logado.
   O objeto `usuario` já vem embutido na resposta de login/refresh, incluindo
   `mfa_habilitado` e `mfa_obrigatorio` (perfil exige 2FA mas ainda não
   configurou). Permissões detalhadas do perfil: `GET /perfis`.
6. **Conta bloqueada** — `423` com `detail` explicando até quando; só um
   Administrador desbloqueia antes do prazo (`POST /auth/usuarios/{id}/desbloquear`).

## Painel, notificações, busca, relatórios e histórico (v1.1)

### Painel unificado — `GET /painel/gerencia`
Alertas de **todas as áreas** numa chamada: faturamento (faturas vencidas/vencendo, medição sem fatura, glosa pendente, meta mensal de NECs em risco a partir do `dia_alerta`), obras (atrasadas / prazo próximo), frota (manutenção, licenciamento e seguro), programação (programações sem fechamento, obra em execução sem programação futura), automações (última execução com falha nas últimas 24 h) e estoque abaixo do mínimo. Ordenado por gravidade; cada seção só aparece se o perfil tem a permissão de leitura do módulo. `?modulo=frota` filtra.

A detecção fica em `app/services/pendencias_service.py` e é **a mesma** usada pelas notificações — painel e avisos nunca divergem. Os limiares (7 dias de prazo, 15 de manutenção, 30 de documentos…) são constantes no topo desse arquivo.

### Notificações
- **No sistema:** `GET /notificacoes` (somente do usuário logado), `GET /notificacoes/contagem` (badge do sino), marcar como lida / todas.
- Cada evento notifica cada usuário **uma única vez** (`chave_dedup` + unique no banco) e só quem tem a permissão de leitura do módulo.
- **E-mail:** níveis `atencao`/`critico`, só para quem tem e-mail e `notificacoes_email=true` (`PUT /notificacoes/preferencias`). Até `EMAIL_MAX_TENTATIVAS`; falha não derruba nada e fica em `email_erro`. Sem SMTP, marca `ignorado`.
- **Quando roda:** `python -m app.jobs.processar_notificacoes` (cron de hora em hora no `render.yaml`) ou manualmente `POST /notificacoes/processar` (permissão `notificacoes:processar`).
- Evento imediato: conta bloqueada por tentativas → notifica quem tem `usuarios:write`.
- Lembrete de **exportação mensal da frota** nos 5 primeiros dias do mês, até alguém exportar o relatório `frota`.
- **WhatsApp:** não implementado (previsto como 2º canal).

### Busca global — `GET /busca?q=…`
Obra, contrato (= código WL), cliente, veículo (placa/modelo), fatura, medição, material, fornecedor e equipe. Filtros `tipos=obra,veiculo`, `regional=`. Respeita o RBAC (só busca onde o perfil pode ler), trata `%` e `_` literalmente e devolve `rota` sugerida para o frontend navegar.

### Relatórios — `/relatorios/exportar/{tipo}?formato=xlsx|pdf`
Tipos: `obras`, `faturas`, `medicoes`, `programacao`, `estoque_movimentacoes`, `frota`. Filtros: `data_inicio`, `data_fim`, `obra_id`, `responsavel_id` (líder da equipe; na medição, o responsável dela; no estoque, quem lançou). Exige `relatorios:export` **e** a permissão de leitura do domínio. O arquivo traz "gerado por / em / filtros" no cabeçalho; cada exportação grava um `RelatorioGerado` (`/relatorios/historico`: quem vê todos tem `auditoria:read`, os demais só os próprios) e uma linha de auditoria `exportacao_<tipo>`. Células que começam com `= + - @` são neutralizadas (injeção de fórmula).

### Histórico do sistema — `/auditoria`
Cada registro tem `categoria` (`login`, `falha_acesso`, `exportacao`, `exclusao`, `alteracao`, `sistema`), IP e user-agent. Filtros: `categoria`, `acao`, `usuario_id`, `ip`, `data_inicio`, `data_fim`, `entidade`. `/auditoria/pagina` devolve `total` para paginação; `/auditoria/resumo` mostra volume por categoria, ações mais frequentes e IPs com mais falhas. Passam a ser registrados: login com usuário inexistente, rate limit, 403 (`acesso_negado`) e exportações. Continua **sem** endpoint de edição/exclusão de log.

### Novas permissões
`frota:read`, `frota:write`, `relatorios:export`, `notificacoes:processar` (o `*` do administrador cobre todas). O `seed.py` já as distribui (gerência-geral, faturamento, programação, almoxarifado, logística/frota, qualidade, visualizador) e **acrescenta as 4 chaves novas a perfis já existentes no banco** sem mexer nas demais — revise em `perfis.permissoes` conforme a regra real.

### Migração para quem já tem banco
```bash
alembic upgrade head                      # aplica a 0008 (nada é apagado; audit_logs antigos são reclassificados)
PYTHONPATH=. python seeds/seed.py         # idempotente: só completa perfis/dados que faltam
```

### Testes contra PostgreSQL
```bash
TEST_DATABASE_URL=postgresql+psycopg2://user:pass@localhost/eletrogestor_test pytest -q
```
(o banco informado é apagado e recriado a cada teste — use um banco só de testes). A suíte inteira passa em SQLite e em PostgreSQL 16.

## Importação das planilhas (FATURAMENTO / PROGRAMAÇÃO TEES)
`python -m app.importacao --faturamento F.xlsx --programacao P.xlsx` (simulação por padrão; `--confirmar` grava). Regras, decisões D1–D10 e limites em **`docs/IMPORTACAO_PLANILHAS.md`**. Migration `0009`: NECs decimais, campos da medição, `obras.arquivada`, 4 tabelas novas.

## Publicação
Veja **`docs/PUBLICACAO.md`** (Neon + Render + Cloudflare + Resend, backups, MFA obrigatório, monitoramento e limitações conhecidas).

## Segurança

- Hash de senha com **bcrypt** (via `passlib`) — nunca senha em texto puro,
  em lugar nenhum (banco, log, resposta de API).
- Bloqueio automático após 5 tentativas inválidas por 30 minutos
  (`MAX_TENTATIVAS_LOGIN`/`BLOQUEIO_MINUTOS` no `.env`), com desbloqueio
  automático por tempo e manual por Administrador.
- Desligar um colaborador (`DELETE /usuarios/{id}`) desativa o usuário **e**
  revoga explicitamente todos os refresh tokens ativos dele — o acesso é
  cortado na próxima requisição, mesmo com um access token ainda não expirado
  (`get_current_user` também rejeita usuários inativos em toda chamada).
- 2FA (TOTP) pronto para uso; perfis que devem exigi-lo futuramente:
  Administrador, Desenvolvedor, Tester, Gerência Geral, Administrativo
  (`PERFIS_COM_2FA_OBRIGATORIO` em `app/security.py`).
- Auditoria é **somente para inclusão** — não existe endpoint de edição ou
  exclusão de `AuditLog` nesta API.
- Nenhuma chave, senha ou dado real está no código — tudo vem do `.env`
  (não é commitado, veja `.gitignore`). Gere uma `JWT_SECRET_KEY` forte antes
  de produção: `python -c "import secrets; print(secrets.token_hex(32))"`.
- Os usuários do seed (`admin` e `teste.<perfil>`) têm senha **temporária**
  (`deve_trocar_senha=True`) — o próprio login já força a troca.

### Pendência de negócio: "regra dos 30 segundos"

Procurei em todo o histórico do projeto (código, README, specs anteriores)
e **não encontrei nenhuma definição objetiva** para essa regra. Criei um
parâmetro placeholder (`regra_30_segundos`, via `GET/PUT /parametros`) que
não está ligado a nenhum comportamento ainda, para não travar o resto da
etapa nem inventar um comportamento por conta própria.

**Pergunta que preciso de resposta para implementar:** o que exatamente são
esses "30 segundos"? Candidatos mais prováveis:
- Timeout de sessão por inatividade no frontend?
- Intervalo mínimo obrigatório entre tentativas de login (rate limiting,
  diferente do bloqueio por 5 tentativas)?
- Tempo de tolerância de alguma automação de campo/rede elétrica?
- Debounce de auto-save em algum formulário?

## Permissões (RBAC)

Cada perfil (`perfis.id`) tem uma lista `permissoes` (JSON) com chaves no
formato `dominio:acao` (ex.: `obras:write`) ou, para transições de status,
`dominio:transicao:<de>:<para>` (ex.: `obras:transicao:contratada:em_execucao`).
O perfil `"*"` equivale a acesso total. Os 21 perfis do frontend
(`src/data/perfis.ts`) já vêm populados pelo seed com um conjunto inicial de
permissões — **isso é um ponto de partida, não uma regra de negócio
validada**; ajuste o campo `permissoes` de cada perfil conforme a regra real
da empresa.

## Criando uma nova migration

```bash
alembic revision --autogenerate -m "descricao da mudanca"
alembic upgrade head
```
Revise sempre o arquivo gerado antes de aplicar. Se a migration usar
`create_foreign_key`/`create_unique_constraint`/`drop_constraint` em uma
tabela existente, envolva a operação em `with op.batch_alter_table(...)`
— é o que garante que a migration funcione tanto em SQLite (dev) quanto em
PostgreSQL (produção); sem isso, SQLite rejeita `ALTER TABLE ADD CONSTRAINT`.

## Módulo Supervisão (v1.3)

Empreiteiras (`/supervisao/empreiteiras`) e relatórios diários de campo (`/supervisao/relatorios`), com RBAC `supervisao:read`/`supervisao:write`, auditoria, CNPJ validado e exclusão de empreiteira bloqueada quando há relatórios vinculados.

- Contrato da API: [`docs/SUPERVISAO_API.md`](docs/SUPERVISAO_API.md)
- Migration: `0010_supervisao_empreiteiras_relatorios` (sobre a `0009`; cria só 2 tabelas novas).
- Permissões em bancos existentes (sem dados de demonstração): `PYTHONPATH=. python seeds/seed_supervisao.py [--dry-run | --reverter]`
- Homologação com cópia de dados reais: [`docs/HOMOLOGACAO.md`](docs/HOMOLOGACAO.md) (inclui `scripts/anonimizar_homologacao.py` e `.env.homologacao.example`).
