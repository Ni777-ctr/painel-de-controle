# Nithicom · Painel central separado

Site administrativo próprio em **http://127.0.0.1:8765**, sem publicação. O frontend original não é alterado. A cópia do backend incluída reutiliza FastAPI, SQLAlchemy, Alembic, PostgreSQL, bcrypt, convites e TOTP do EletroGestor 1.3 enviado. Não existe um segundo cadastro de senhas: a autenticação continua em `usuarios`.

## Estado da entrega e limite de integração

O painel implementa as oito abas: visão geral, usuários, cargos e liberações, setores, permissões, hierarquia e equipes, histórico e segurança. Os indicadores vêm do banco. Nenhum cargo, setor ou limite é preenchido automaticamente. As contas antigas aparecem como não gerenciadas até a revisão explícita pelo administrador.

**A integração dos registros operacionais por setor ainda exige desenvolvimento específico de cada módulo.** O modelo original não tem uma relação uniforme entre seus registros e os novos setores. Por segurança, a integração incluída nega as rotas operacionais antigas aos usuários já vinculados ao controle central, enquanto os usuários ainda não vinculados mantêm o RBAC anterior. Não adote usuários de produção antes de planejar esse mapeamento. As regras e exceções são persistidas e avaliadas no servidor, mas não se deve afirmar que já liberam todos os módulos operacionais. O backend original agrupa criar/editar/excluir em `write`; separá-las exige alterar essas rotas. Nenhum módulo foi inventado.

A conexão com um backend SQLite local existente foi validada com preservação dos registros. O repositório contém apenas código e exemplos; a configuração e os dados reais permanecem locais. A concorrência entre processos no PostgreSQL permanece sujeita a homologação. Consulte `VALIDACAO.md` para os testes da versão base.

## 1. Abrir e preparar no VS Code

Abra esta pasta no VS Code. Use Python 3.12 e PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Copy-Item backend\.env.central.example backend\.env
```

Edite **somente localmente** `backend/.env`:

- `DATABASE_URL`: o banco EXISTENTE. Não rode seeds. Não crie um banco duplicado de usuários.
- `JWT_SECRET_KEY`: a mesma chave do backend principal, com pelo menos 32 caracteres. A chave fica no servidor.
- `CENTRAL_ADMIN_IDS`: IDs reais dos usuários autorizados, separados por vírgula. Cada conta também precisa do perfil existente `administrador` e estar ativa. A interface não cria administradores centrais.
- `MFA_OBRIGATORIO_ENFORCE`: preserve a política existente. O exemplo exige MFA; configure o TOTP no site principal primeiro, se necessário.
- Banco remoto: use `sslmode=verify-full`, CA confiável e privilégios mínimos. Um usuário separado de migração pode criar as tabelas; o usuário de execução deve possuir apenas os acessos necessários. Nunca coloque credenciais no frontend.

Para localizar IDs, consulte administrativamente a tabela `usuarios` ou a API autorizada existente. Não faça um mapeamento automático entre perfil operacional e cargo hierárquico.

## 2. Backup, revisão e migração

Antes de aplicar qualquer mudança ao banco, revise `backend/alembic/versions/0011_central_local.py` e faça backup consistente com as ferramentas PostgreSQL. O banco já deve estar na revisão **0010** do projeto enviado.

```powershell
# PGSERVICE e o arquivo de credenciais devem estar configurados localmente.
# Evite inserir a senha diretamente no histórico de comandos.
pg_dump --dbname=service=nithicom --format=custom --file=nithicom-antes-central.dump
Set-Location backend
..\.venv\Scripts\python.exe -m alembic current
..\.venv\Scripts\python.exe -m alembic upgrade 0011_central_local
Set-Location ..
```

A migração cria oito tabelas aditivas: `central_contas`, `central_setores`, `central_vinculos`, `central_limites`, `central_regras`, `central_excecoes`, `central_sessoes` e `central_versoes_auth`. Não altera os dados das tabelas existentes e não cria limites iniciais.

**Reversão de esquema:** primeiro desligue o painel e retire a integração do backend original, depois, com backup dos dados centrais, execute `python -m alembic downgrade 0010`. Isso remove SOMENTE as oito tabelas centrais, incluindo configurações, vínculos e sessões; as alterações já realizadas em `usuarios` não são desfeitas. Para restaurar essas alterações, use um backup validado em ambiente isolado e siga o procedimento de recuperação da empresa.

**Restauração:** teste primeiro `pg_restore --dbname=service=nithicom_restore --no-owner nithicom-antes-central.dump` em um banco vazio e isolado. Confira usuários, perfis, contagens e revisão Alembic antes de planejar uma restauração no banco real. Não use `--clean` contra o banco real sem autorização explícita. O painel não executa restaurações.

## 3. Integrar o backend original

O painel usa o mesmo banco, mas as regras só são invioláveis quando o backend principal também valida os controles. A integração é necessária para bloquear cadastros pela API antiga, validar convites delegados, ativar convites e invalidar access tokens após revogação.

O arquivo `integrar_backend.py` faz **inspeção sem alteração por padrão**. Com `--aplicar`, primeiro valida hashes dos arquivos originais enviados no ZIP, cria uma cópia de segurança e copia apenas os arquivos necessários. Se seu projeto mudou, ele recusa a substituição; use o patch em `integracao-central.patch` para revisar a integração manualmente.

```powershell
.\.venv\Scripts\python.exe integrar_backend.py --destino "C:\caminho\eletrogestor\backend"
# Só após revisão e backup:
.\.venv\Scripts\python.exe integrar_backend.py --destino "C:\caminho\eletrogestor\backend" --aplicar
```

Defina `CENTRAL_ADMIN_IDS` também no ambiente do backend original. Não altere portas, CORS, hosts, URLs ou configurações de produção para servir o painel. Reinicie o backend original conforme sua rotina. Não aplique a migração duas vezes: ambos usam o mesmo banco.

As fontes existentes alteradas são `app/config.py`, `app/deps.py`, `app/main.py`, `app/routers/auth.py` e `scripts/anonimizar_homologacao.py` (para também anonimizar os setores e remover as sessões centrais na cópia de homologação). A fixture dos testes foi adaptada para verificar o esquema anterior separadamente. A interface principal fica intacta. A rota antiga de alteração/cadastro de usuários passa a orientar o uso do painel; delegações usam `POST /governanca/convites`. A cópia incluída preserva as demais fontes do backend para execução e regressão.

## 4. Iniciar o painel separado

```powershell
.\.venv\Scripts\python.exe iniciar.py
```

Abra **http://127.0.0.1:8765**. O iniciador valida a configuração, a migração e a existência de administrador autorizado. Escuta apenas loopback e um processo. Não abre túneis nem publica o site. Use o login existente. TOTP e troca obrigatória de senha são respeitados. Tokens JWT permanecem no servidor; o navegador recebe apenas uma sessão opaca em cookie HttpOnly e o código CSRF.

Na primeira configuração, aprove limites globais, crie os setores reais e configure as regras por cargo/setor. Revise as contas antigas individualmente; não atribua cargos sem conhecer a hierarquia. Usuários ativos e convites pendentes ocupam vagas. Reativações e mudanças de cargo respeitam os limites. Reduzir um limite não desativa ninguém. O último administrador central ativo não pode ser desativado ou perder seu perfil por esta interface.

## 5. Convites e redefinição de senha

O painel exibe o código de convite uma única vez, com validade de 72 horas. Entregue-o privadamente ao destinatário. Ele pode usar o fluxo de convite existente ou `POST /auth/definir-senha` da API principal. O frontend original enviado não fornece uma página dedicada completa de aceite; a chamada abaixo é uma alternativa local com senha oculta na entrada do terminal:

```powershell
$conviteCentral = Read-Host "Código de convite"
$senhaCentral = Read-Host "Nova senha" -AsSecureString
$senhaCentralTexto = [System.Net.NetworkCredential]::new('', $senhaCentral).Password
$dadosCentral = @{ convite_token=$conviteCentral; senha=$senhaCentralTexto } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/auth/definir-senha" -ContentType "application/json" -Body $dadosCentral
Remove-Variable senhaCentralTexto, dadosCentral, conviteCentral, senhaCentral
```

Adapte a URL da API principal existente. Para API remota, use HTTPS. O código não é gravado na auditoria. Redefinir a senha revoga sessões e deixa a conta pendente; ela só volta a acessar depois de aceitar o convite. A redefinição do último administrador é recusada: estabeleça primeiro outro administrador autorizado de acordo com o procedimento da empresa.

## 6. Segurança e autorização

- O servidor identifica o ator pela sessão validada; IDs enviados pelo navegador são somente alvos.
- Todos os controles de edição exigem justificativa, confirmação, origem autorizada e CSRF.
- Cookie HttpOnly, SameSite Strict, expiração de uma hora, logout e revogação persistida.
- A lista de administradores vem do servidor; perfil `administrador` sozinho não dá acesso central.
- Sem CORS aberto; Host restrito e CSP bloqueiam fontes externas.
- Validação de perfil, cargo, responsável superior, setor ativo, cargos autorizados e ciclos.
- Exceções não concedem acesso a setores fora dos vínculos nem a módulos não liberados no setor.
- O administrador não altera seu próprio perfil/cargo nem suas próprias exceções de permissão.
- Auditoria existente reutilizada, com autor, alvo, antes/depois, horário e justificativa; nenhuma rota de edição ou exclusão de logs.
- Não existe exclusão definitiva de usuário na interface; estados preservam o histórico.
- Todas as mutações de governança usam um advisory lock transacional no PostgreSQL; o mesmo lock é usado nos dois serviços. No SQLite local, as mutações adquirem `BEGIN IMMEDIATE` antes de validar a governança; não use esse ambiente como substituto de uma implantação PostgreSQL de produção.
- Contas fora da governança preservam o modelo anterior. A migração não inventa autoria nem vínculos históricos que não existiam.

## 7. Testes

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Set-Location backend
..\.venv\Scripts\python.exe -m pytest central_tests -q
# Regressões do sistema antes da migração central:
..\.venv\Scripts\python.exe -m pytest tests -q
```

Os testes centrais usam somente SQLite em memória e dados expressamente sintéticos. Nunca defina `TEST_DATABASE_URL` com um banco real: a fixture original apaga/recria tabelas quando essa variável está configurada. A concorrência multiprocesso e o TLS do banco remoto devem ser homologados em PostgreSQL isolado antes do uso real.

## Diagnóstico e riscos de compatibilidade

O frontend enviado é React 19, TanStack Start, Vite e Tailwind. O backend é FastAPI, SQLAlchemy 2 e Alembic com PostgreSQL. `perfis.permissoes` é um array JSON e tem coringa `*`; não havia vínculo entre cargos hierárquicos e esses perfis. `usuarios` tem um perfil por conta, mas o novo modelo admite vários setores e cargos distintos em cada vínculo. Já existiam refresh tokens com hash, convites, TOTP, auditoria e módulos de obras, programação, estoque, compras, equipes, financeiro, frota, relatórios, supervisão e automações.

A interface central é HTML/CSS/JavaScript sem um segundo processo de build, servida pelo novo app FastAPI. Isso mantém o frontend principal intacto e evita mudar o framework dele. O backend e o banco mantêm as tecnologias existentes. A autenticação reutiliza os serviços originais; a tabela de sessão central não é uma segunda tabela de senhas.

Este pacote ainda não satisfaz a aceitação integral de acesso operacional por setor: será necessário relacionar registros e filtros de listagem de cada módulo aos setores, verificar essas relações em cada operação e testar o frontend principal com usuários gerenciados. O comportamento atual é negar esses acessos ambíguos, de maneira explícita, em vez de afirmar uma integração que o esquema original não suporta.

## Backend local já configurado

Após integrar as fontes e a migração compatível com a sequência do backend existente, execute `python conectar_existente.py CAMINHO_DO_BACKEND`. O comando lê o `.env` do próprio backend e abre apenas `127.0.0.1:8765`. SQLite é aceito somente em desenvolvimento e com um arquivo de banco existente. Configure `CENTRAL_ADMIN_IDS` com os administradores reais autorizados; use os logins existentes. Não publique `.env`, bancos, backups ou chaves JWT. Em versões diferentes da base enviada, adapte a sequência da migração central e preserve as fontes locais antes da aplicação.
