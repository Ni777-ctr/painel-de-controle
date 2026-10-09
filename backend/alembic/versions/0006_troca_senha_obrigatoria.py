"""usuarios: troca de senha obrigatoria (primeiro acesso / expiracao)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-22 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'usuarios',
        sa.Column('deve_trocar_senha', sa.Boolean(), nullable=False, server_default=sa.text('false')),
    )
    op.add_column('usuarios', sa.Column('senha_alterada_em', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('usuarios', 'senha_alterada_em')
    op.drop_column('usuarios', 'deve_trocar_senha')
