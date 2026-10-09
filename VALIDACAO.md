# Validação executada — 09/10/2026

## Resultados reais

- **24 testes centrais passaram** na execução final da suíte `central_tests` (72,59 s).
- A execução ampla `central_tests tests` executou 209 casos: 207 passaram e dois testes de migração falharam por um subprocesso substituir o caminho das dependências Python.
- Depois de corrigir o caminho, os **dois testes de migração passaram** em uma execução específica (55,17 s).
- O total de casos distintos validados é **211: 24 centrais e 187 do backend existente**, em execuções complementares. Não se trata de uma execução única de 211 casos após todas as alterações.
- `node --check` passou para o JavaScript do painel; `compileall` passou para as fontes centrais.
- Alembic reconheceu uma única revisão final `0011_central_local`, descendente de `0010`.
- O instalador foi executado em uma cópia descartável dentro de `work/`: criou o backup e os 15 arquivos de integração copiados foram comparados byte a byte com o pacote.
- O modo de inspeção do instalador também foi executado e não modificou o destino.
- A interface foi conferida no navegador em viewport estreito e em 1366 × 900: login, visão geral, usuários e formulário de convite, limites, setores, permissões, hierarquia, histórico e segurança.

Os testes utilizaram bancos SQLite isolados e pessoas expressamente sintéticas. A prévia de interface utiliza um banco separado de QA e exibe “TESTE ISOLADO · DADOS SINTÉTICOS”. Não houve acesso a banco real, publicação ou alteração do ZIP original.

## Regras verificadas

| Regra | Evidência |
|---|---|
| Administrador autorizado entra; usuário comum não entra | Testes de sessão, login, MFA e acesso negado auditado |
| Operações exigem sessão, origem, CSRF e confirmação | Tentativas sem sessão, CSRF incorreto, origem externa, Host inválido e confirmação ausente foram recusadas |
| Limites persistem e não são ignorados | Cadastro sem configuração negado, vaga de convite reservada e segundo cadastro negado ao atingir o máximo |
| Redução de limite preserva usuários | Contas continuaram existentes; novos cadastros bloqueados; edição do nome permaneceu possível |
| Concorrência controlada | Dois cadastros simultâneos disputaram uma vaga; somente um foi criado em SQLite no mesmo processo |
| Limite por setor e setor inativo | Novo cadastro no setor com limite atingido ou setor inativo foi recusado |
| Hierarquia segura | Autorresponsabilidade, cargo superior inválido, setor fora do vínculo e ciclo foram recusados |
| Cargo global não esconde autoridade de setor | Cargo global inferior ao maior cargo dos vínculos foi recusado |
| Convites delegados respeitam a hierarquia | Dono criou gerente; criação de dono e concessão de perfil privilegiado por delegado foram recusadas |
| Permissões herdadas e exceções | Padrão permitido, ausência negada, exceção negada/permitida e remoção para herdar foram avaliados no servidor |
| Setor fora do escopo | Consulta ao contexto sem vínculo recusada; exceção não concedeu setor adicional |
| Rotas legadas ambíguas não vazam escopo | Operação global recusada; busca global não retornou registros para usuário gerenciado sem isolamento de setor |
| Bloqueio e revogação | Login bloqueado, refresh token revogado, access token anterior recusado, MFA pendente revogado e sessão local encerrada |
| Último administrador | Desativação recusada |
| Auditoria | Alterações e negativas registradas; data de login existente serializada; nenhuma rota para alterar/apagar logs |
| Migrações | Upgrade/downgrade central preservou usuários; migrações do projeto e comparação entre esquema e modelos passaram |
| Regressão antes da migração | Login, RBAC, obras, estoque/compras, faturamento, frota, busca, relatórios, notificações, importações, supervisão e anonimização cobertos pela suíte existente |

## Pendências para aceitação integral

1. Configurar localmente o banco real, a chave existente e os IDs autorizados; aplicar a migração somente após revisão e backup.
2. Homologar a integração no backend principal com o frontend original. Os testes existentes de regressão cobrem o esquema anterior; a suíte central cobre o esquema migrado em dados isolados.
3. Relacionar os registros operacionais de cada módulo aos setores e aplicar filtros e autorização de objeto em suas rotas. O comportamento atual é negar acesso às rotas ambíguas para contas já gerenciadas. **As permissões configuradas no painel ainda não liberam essas operações legadas.**
4. Caso sejam necessárias ações separadas de criar/editar/excluir/aprovar, desmembrar as permissões `write` nas rotas existentes; o painel mantém as chaves efetivamente identificadas no projeto.
5. Testar o advisory lock em PostgreSQL isolado com os dois processos e cadastros simultâneos. O teste executado em SQLite não prova concorrência multiprocesso no PostgreSQL.
6. Validar TLS, permissões do usuário de banco e recuperação de backup com a infraestrutura real.

Houve avisos de descontinuação das bibliotecas existentes e avisos SQLAlchemy na importação de planilhas. Esses avisos não foram apresentados como resultados novos nem tratados como garantia de funcionamento em produção.
