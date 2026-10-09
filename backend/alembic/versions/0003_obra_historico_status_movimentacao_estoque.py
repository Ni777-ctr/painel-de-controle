"""obra: historico de status e movimentacao de estoque

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'historico_status_obra',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=False),
        sa.Column('status_anterior', sa.String(length=20), nullable=True),
        sa.Column('status_novo', sa.String(length=20), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('observacao', sa.String(length=255), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_historico_status_obra_obra_id'), 'historico_status_obra', ['obra_id'], unique=False)

    op.create_table(
        'movimentacoes_estoque',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('almoxarifado_id', sa.Integer(), nullable=False),
        sa.Column('material_id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=True),
        sa.Column('usuario_id', sa.Integer(), nullable=True),
        sa.Column('tipo', sa.String(length=10), nullable=False),
        sa.Column('quantidade', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('observacao', sa.String(length=255), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['almoxarifado_id'], ['almoxarifados.id'], ),
        sa.ForeignKeyConstraint(['material_id'], ['materiais.id'], ),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_movimentacoes_estoque_obra_id'), 'movimentacoes_estoque', ['obra_id'], unique=False)
    op.create_index(op.f('ix_movimentacoes_estoque_material_id'), 'movimentacoes_estoque', ['material_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_movimentacoes_estoque_material_id'), table_name='movimentacoes_estoque')
    op.drop_index(op.f('ix_movimentacoes_estoque_obra_id'), table_name='movimentacoes_estoque')
    op.drop_table('movimentacoes_estoque')
    op.drop_index(op.f('ix_historico_status_obra_obra_id'), table_name='historico_status_obra')
    op.drop_table('historico_status_obra')
