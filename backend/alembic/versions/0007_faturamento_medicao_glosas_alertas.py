"""faturamento: NEC por medicao/fatura, glosas, alertas financeiros,
obra.necs_faturados/observacoes

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- Obra: necs_faturados, observacoes ----
    op.add_column('obras', sa.Column('necs_faturados', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('obras', sa.Column('observacoes', sa.Text(), nullable=True))

    # ---- Medicao: necs_medidos ----
    op.add_column('medicoes', sa.Column('necs_medidos', sa.Integer(), nullable=False, server_default='0'))

    # ---- Fatura: necs_faturados ----
    op.add_column('faturas', sa.Column('necs_faturados', sa.Integer(), nullable=True))

    # ---- Glosa ----
    op.create_table(
        'glosas',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('medicao_id', sa.Integer(), nullable=False),
        sa.Column('valor', sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column('motivo', sa.Text(), nullable=False),
        sa.Column('resolvida', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['medicao_id'], ['medicoes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_glosas_medicao_id'), 'glosas', ['medicao_id'], unique=False)

    # ---- AlertaFinanceiro ----
    op.create_table(
        'alertas_financeiros',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('nivel', sa.String(length=20), nullable=False, server_default='atencao'),
        sa.Column('obra_id', sa.Integer(), nullable=True),
        sa.Column('fatura_id', sa.Integer(), nullable=True),
        sa.Column('medicao_id', sa.Integer(), nullable=True),
        sa.Column('mensagem', sa.Text(), nullable=False),
        sa.Column('resolvido', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('resolvido_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolvido_por_usuario_id', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
        sa.ForeignKeyConstraint(['fatura_id'], ['faturas.id'], ),
        sa.ForeignKeyConstraint(['medicao_id'], ['medicoes.id'], ),
        sa.ForeignKeyConstraint(['resolvido_por_usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_alertas_financeiros_obra_id'), 'alertas_financeiros', ['obra_id'], unique=False)
    op.create_index(op.f('ix_alertas_financeiros_fatura_id'), 'alertas_financeiros', ['fatura_id'], unique=False)
    op.create_index(op.f('ix_alertas_financeiros_medicao_id'), 'alertas_financeiros', ['medicao_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_alertas_financeiros_medicao_id'), table_name='alertas_financeiros')
    op.drop_index(op.f('ix_alertas_financeiros_fatura_id'), table_name='alertas_financeiros')
    op.drop_index(op.f('ix_alertas_financeiros_obra_id'), table_name='alertas_financeiros')
    op.drop_table('alertas_financeiros')

    op.drop_index(op.f('ix_glosas_medicao_id'), table_name='glosas')
    op.drop_table('glosas')

    op.drop_column('faturas', 'necs_faturados')
    op.drop_column('medicoes', 'necs_medidos')
    op.drop_column('obras', 'observacoes')
    op.drop_column('obras', 'necs_faturados')
