# Homologação controlada do v1.3 (com cópia de dados reais)

**Regra de ouro: este roteiro nunca se conecta à produção.** O ponto de partida é um **arquivo de backup que já existe** (dump ou branch/snapshot do provedor), restaurado em um **banco novo e separado**. Quem tem acesso à produção entrega o backup; nada aqui precisa da URL de produção.

Ordem obrigatória: **restaurar → migrar → anonimizar → permissões → usuários de teste → subir a API → aceite.**

## 0. Pré-requisitos

- [ ] Backup recente da produção (formato `pg_dump --format=custom` ou branch/snapshot) em mãos, **e o backup foi testado** (`pg_restore --list arquivo.dump` lê sem erro).
- [ ] Um banco PostgreSQL **novo**, só para homologação, com `homolog` no nome (ex.: `eletrogestor_homolog`), em instância/projeto diferente da produção ou, no mínimo, com credenciais próprias.
- [ ] Uma API de homologação com URL própria, e o frontend de homologação apontando para ela.
- [ ] Ninguém além da equipe de homologação com acesso a esse banco (ele conterá uma cópia dos dados até a etapa 3 terminar).

## 1. Restaurar o backup no banco de homologação

```bash
# Confira ANTES que a URL abaixo é a de HOMOLOGACAO (o nome do banco deve conter "homolog").
export DATABASE_URL_HOMOLOG='postgresql://USUARIO:SENHA@HOST/eletrogestor_homolog?sslmode=require'
pg_restore --list eletrogestor_AAAAMMDD.dump > /dev/null && echo "dump legivel"
pg_restore --clean --if-exists --no-owner --no-privileges -d "$DATABASE_URL_HOMOLOG" eletrogestor_AAAAMMDD.dump
```

Alternativa no Neon: criar uma *branch* a partir do ponto desejado e usar a URL da branch (dê a ela um nome com `homolog`). Registre quando o dump foi gerado — é a "data da cópia".

- [ ] Restauração concluída sem erros.
- [ ] `alembic current` no banco restaurado mostra **`0009`** (esperado: o v1.2 já em uso). Se mostrar outra coisa, **pare** e investigue — não use `stamp`.

## 2. Migrar para o v1.3 (cria só as 2 tabelas do módulo)

Na pasta `backend/` do v1.3, com `DATABASE_URL` apontando para a homologação:

```bash
export DATABASE_URL="$DATABASE_URL_HOMOLOG"
PYTHONPATH=. alembic current          # deve mostrar 0009
PYTHONPATH=. alembic heads            # deve mostrar UMA head: 0010
PYTHONPATH=. alembic upgrade head     # 0009 -> 0010
PYTHONPATH=. alembic current          # 0010 (head)
```

- [ ] `0010` aplicada. Só foram criadas `empreiteiras` e `relatorios_supervisao`; nenhuma tabela existente foi alterada.
- ⚠️ **Não rode `seeds/seed.py` em banco com dados reais** (cria `admin/admin123`, usuários `teste.*` com senha previsível e dados de demonstração). Use apenas os scripts abaixo.

## 3. Anonimizar (antes de qualquer pessoa usar o ambiente)

```bash
PYTHONPATH=. python scripts/anonimizar_homologacao.py --confirmo-copia-descartavel --dry-run   # confere as contagens
PYTHONPATH=. python scripts/anonimizar_homologacao.py --confirmo-copia-descartavel --criar-usuarios-teste
```

O script recusa rodar se o nome do banco não tiver `homolog`, roda em uma transação (falhou = nada mudou) e **para** se existir coluna de texto nova ainda não classificada. Ele:

- troca nomes, e-mails, logins, documentos, contatos, endereços e placas por valores fictícios; torna **todas as senhas inutilizáveis** (ninguém entra com a senha real); remove 2FA, convites e sessões;
- remove textos livres (observações, motivos, mensagens), IP/user-agent e antes/depois da auditoria e os JSON brutos de planilhas;
- **preserva** códigos de negócio (WL, projeto, PowerOn, regional, status) para os testes fazerem sentido.

- [ ] Revisou a lista "preservado de propósito" em `scripts/anonimizar_homologacao.py` (`PRESERVADAS`) e decidiu se algum código é sensível para você. **Se for, anonimize ou exclua antes de seguir.**
- [ ] Guardou as senhas dos usuários `homolog.<perfil>` impressas **uma única vez** (gerenciador de senhas). Todos precisam trocar a senha no 1º login.
- [ ] Conferência manual por amostragem (SQL abaixo) sem nenhum dado real.

```sql
select usuario, email, nome from usuarios limit 5;                 -- anon-user-N / @homolog.invalid
select nome, documento, email from clientes limit 5;               -- Cliente N / @homolog.invalid
select nome_razao_social, cnpj, codigo_contrato from empreiteiras limit 5;
select responsavel, contato, codigo_placa, endereco from relatorios_supervisao limit 5;
select count(*) from refresh_tokens;                               -- 0
select count(*) from audit_logs where ip is not null;              -- 0
```

> Limite honesto: o script cobre **todas** as colunas de texto/JSON conhecidas, mas não enxerga PII escondida dentro de campos que ele preserva (ex.: alguém digitou um telefone em `descricao` de uma obra). Por isso a amostragem manual acima é obrigatória antes de liberar o acesso a mais gente.

## 4. Permissões do módulo

```bash
PYTHONPATH=. python seeds/seed_supervisao.py --dry-run    # mostra o que mudaria
PYTHONPATH=. python seeds/seed_supervisao.py              # soma supervisao:read/write
PYTHONPATH=. python seeds/seed_supervisao.py              # 2a vez: "nenhuma alteracao necessaria"
```

Só soma as chaves e nunca remove permissões customizadas. Mapa: supervisor `read+write`; gerencia-geral e qualidade `read`; demais sem acesso; `*` já cobre tudo. Para desfazer: `--reverter`.

- [ ] Perfis conferidos: `select id, permissoes from perfis where id in ('supervisor','gerencia-geral','qualidade');`

## 5. Subir a API de homologação

Use `.env.homologacao.example` como modelo. Pontos críticos:

- [ ] `EMAIL_HABILITADO=false` (**obrigatório**: a cópia não pode notificar pessoas reais; confira também que nenhum `SMTP_*` real foi configurado).
- [ ] `JWT_SECRET_KEY` **própria** (diferente da produção; assim tokens de um ambiente não valem no outro).
- [ ] `CORS_ORIGINS` = somente a URL do frontend de homologação (nada de `localhost` com `ENVIRONMENT=production`).
- [ ] `ENVIRONMENT=production` (liga as validações de segurança; a API recusa subir com configuração insegura).
- [ ] `GET /saude` e `GET /saude/pronto` respondem `ok`.
- [ ] Preflight CORS do frontend funciona: `OPTIONS /supervisao/relatorios` com `Origin` do frontend devolve `access-control-allow-origin` igual à origem.

## 6. Aceite funcional (use os usuários `homolog.*`)

Regressão dos módulos existentes (com `homolog.administrador`):

- [ ] Login com troca obrigatória de senha; `GET /auth/me`.
- [ ] Obras, clientes, equipes, programação, estoque/compras, faturamento/medição, frota, painel, busca, notificações, relatórios (exportação), auditoria, parâmetros: listagens abrem e os totais batem com o esperado da cópia.
- [ ] Importação de planilhas, se faz parte do uso (em dados anonimizados).

Supervisão (com `homolog.supervisor` e depois `homolog.gerencia-geral`, `homolog.qualidade`, `homolog.encarregado`):

- [ ] Supervisor: cria empreiteira (CNPJ válido formata `00.000.000/0000-00`); CNPJ inválido → `422`; CNPJ repetido → `409`.
- [ ] Supervisor: cria relatório com empreiteira cadastrada e outro com empreiteira "customizada"; edita (`PUT` completo); lista com filtros (data, período, município, status, empreiteira, responsável) e paginação.
- [ ] Excluir empreiteira com relatórios → `409`; sem relatórios → `204`; desativar via `PATCH ativo=false`.
- [ ] gerencia-geral e qualidade: leem; qualquer escrita → `403`. encarregado: `403` até na leitura.
- [ ] Auditoria: cada escrita aparece com usuário, ação e antes/depois; tentativas negadas aparecem como `acesso_negado`.
- [ ] Frontend: telas de Supervisão consomem o contrato de `docs/SUPERVISAO_API.md` (atenção ao `status` com acento e ao `PUT` que substitui o objeto inteiro).
- [ ] Desempenho: lista de relatórios com volume realista responde em tempo aceitável (hoje há índices em data, status, empreiteira, responsável e data+município).

## 7. Critérios para sair da homologação

- [ ] Todos os itens acima marcados; nenhum `5xx` nos logs da API durante o aceite.
- [ ] Pendências de permissão por perfil decididas (ex.: liberar `supervisao:read` a mais perfis).
- [ ] Plano de produção revisado: backup novo **antes**, `alembic upgrade head` (só a 0010), `seed_supervisao.py`, e rollback conhecido.

## 8. Rollback e descarte

- **Código:** volte ao pacote v1.2 (`eletrogestor-backend-v1.2.zip`); as tabelas novas não são usadas por ele e podem permanecer sem efeito.
- **Banco (somente homologação/descartável):** `PYTHONPATH=. alembic downgrade 0009` remove apenas `relatorios_supervisao` e `empreiteiras` (apaga os dados de Supervisão criados). Em dúvida, restaure o dump.
- **Permissões:** `PYTHONPATH=. python seeds/seed_supervisao.py --reverter`.
- **Fim da homologação:** apague o banco/branch de homologação e revogue as credenciais dele. Nunca o reutilize como se fosse produção.
- Nunca use `alembic stamp`, reset de banco ou `drop` manual de tabelas existentes.
