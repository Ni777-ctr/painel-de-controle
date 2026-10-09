# Publicação segura — EletroGestor API

Stack alvo: **Render** (API + cron) · **Neon** (PostgreSQL) · **Cloudflare** (DNS/HTTPS/WAF) · **Resend** (e-mail) · **Sentry** (erros).

## O que o código já faz sozinho

| Requisito | Como está implementado |
|---|---|
| Recusa configuração insegura | `ENVIRONMENT=production` → a API **não sobe** com `JWT_SECRET_KEY` fraca/padrão, banco local/SQLite ou `CORS_ORIGINS` vazio/com `localhost` (`Settings.validar_para_producao`). |
| HTTPS | `FORCE_HTTPS=true` + `TRUST_PROXY=true`: redireciona http→https (308) lendo `X-Forwarded-Proto`; envia HSTS. `/saude*` nunca redireciona (health check da plataforma). |
| Cabeçalhos de segurança | `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, CSP restritiva (exceto `/docs`), `Cache-Control: no-store` em `/auth/*`. |
| Host header | `ALLOWED_HOSTS` (TrustedHost). |
| MFA | `MFA_OBRIGATORIO_ENFORCE=true`: perfis administrador, desenvolvedor, tester, gerência-geral e administrativo **não recebem sessão** até configurarem o 2FA (recebem só um token restrito para `/auth/mfa/iniciar` e `/auth/mfa/confirmar`). |
| Força bruta | Bloqueio de conta (5 tentativas/30 min) **+** rate limit por IP no login (429 + `Retry-After`). |
| Logs | JSON estruturado (`LOG_JSON=true`) com `request_id` (também devolvido em `X-Request-ID`), método, rota, status, duração, IP. Query string **não** é logada. |
| Monitoramento | `/saude` (liveness), `/saude/pronto` (readiness — testa o banco, devolve 503 se cair), Sentry opcional (`SENTRY_DSN`, sem PII). |
| Auditoria | Login, falhas, bloqueios, acesso negado (403), alterações, exclusões e exportações, com IP e user-agent — tela do admin em `/auditoria/pagina` e `/auditoria/resumo`. |
| Backups | `scripts/backup_pg.sh` (pg_dump + validação + rotação). Restore testado. |

## Passo a passo

### 1. Neon
1. Crie o projeto e copie a connection string (`postgresql://…neon.tech/…?sslmode=require`). Pode colar **como vem**: a API ajusta o driver.
2. Use um *branch* separado para testes. Em Settings, deixe o **histórico de restauração (PITR)** no maior prazo que seu plano permitir.

### 2. Render
1. *New → Blueprint* apontando para este repositório (`render.yaml` na pasta `backend/`; ajuste `rootDir` se necessário).
2. Preencha as variáveis marcadas `sync: false`: `DATABASE_URL`, `CORS_ORIGINS`, `FRONTEND_URL`, `ALLOWED_HOSTS`, `SMTP_SENHA`, `EMAIL_REMETENTE`, `SENTRY_DSN`.
3. `JWT_SECRET_KEY` é gerada pelo Render. **Troque-a só de propósito**: invalida todas as sessões.
4. As migrations rodam no `preDeployCommand` (`alembic upgrade head`) — antes de o novo código receber tráfego.
5. O cron `eletrogestor-notificacoes` roda de hora em hora (`python -m app.jobs.processar_notificacoes`): gera avisos novos e envia e-mails. É idempotente.

### 3. Primeiro acesso em produção
```bash
# no Shell do Render (ou local apontando para o Neon):
PYTHONPATH=. python seeds/seed.py
```
O seed cria os perfis e o usuário `admin` com **senha temporária** (`admin123`, troca obrigatória no 1º login). Troque-a imediatamente e **configure o 2FA**. Depois, **desative ou apague os usuários `teste.<perfil>`** — eles existem só para homologação:
```
PUT /usuarios/{id} {"ativo": false}   # ou DELETE /usuarios/{id}
```

### 4. Cloudflare (domínio + HTTPS)
- CNAME `api` → serviço do Render, proxy ligado (nuvem laranja), SSL/TLS em **Full (strict)**.
- Opcional: regra de WAF/rate limit em `/auth/login`.
- `TRUST_PROXY=true` faz a API usar `CF-Connecting-IP` como IP do cliente (auditoria e rate limit).

### 5. E-mail (Resend)
Verifique o domínio de envio no Resend, crie uma API key e use-a como `SMTP_SENHA` (host `smtp.resend.com`, porta `587`, usuário `resend`). Sem SMTP configurado, as notificações **continuam aparecendo no sistema**; os e-mails ficam marcados como `ignorado`.

### 6. Backups
- **Primário:** PITR do Neon.
- **Cópia fora do provedor** (recomendado): agende `scripts/backup_pg.sh` (ex.: cron diário num runner/VM) e envie o `.dump` para um bucket (R2, S3, Backblaze). Teste o restore periodicamente:
```bash
pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL_DE_TESTE" eletrogestor_AAAAMMDD.dump
```

### 7. Monitoramento
- Health check do Render: `/saude/pronto`.
- UptimeRobot/Better Stack em `https://api…/saude/pronto`.
- Sentry com `SENTRY_DSN`.
- Revisar semanalmente `GET /auditoria/resumo?dias=7` (falhas de acesso por IP).

## Limitações conhecidas (leia antes de publicar)
- O **rate limit de login é em memória do processo**: com N workers o limite efetivo é N× maior. O bloqueio por conta (no banco) continua valendo para todos. Para limite global, use a regra de rate limit da Cloudflare.
- `MFA_OBRIGATORIO_ENFORCE` vem **desligado** por padrão (para não travar o desenvolvimento); o `render.yaml` o liga. Sessões já abertas antes de ligar continuam válidas até expirarem.
- E-mail e notificações no sistema estão prontos; **WhatsApp não está implementado** (a fila `Notificacao` foi desenhada para receber um segundo canal depois).
