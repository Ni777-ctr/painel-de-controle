"""Governança central aditiva. Sem seeds, renomes ou alteração de usuários."""
from alembic import op
from app.central.models import ContaCentral, Setor, Vinculo, Limite, Regra, Excecao, Sessao, VersaoAutenticacao

revision = '0011_central_local'
down_revision = '0010'
branch_labels = None
depends_on = None
TABLES = [ContaCentral.__table__, Setor.__table__, Vinculo.__table__, Limite.__table__, Regra.__table__, Excecao.__table__, Sessao.__table__, VersaoAutenticacao.__table__]

def upgrade():
    for table in TABLES:
        table.create(op.get_bind(), checkfirst=False)

def downgrade():
    for table in reversed(TABLES):
        table.drop(op.get_bind(), checkfirst=False)
