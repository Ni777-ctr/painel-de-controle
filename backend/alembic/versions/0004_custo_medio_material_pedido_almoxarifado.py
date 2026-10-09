"""compras->estoque->custo: custo medio do material, valor_unitario na
movimentacao, almoxarifado de recebimento no pedido de compra

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('materiais', sa.Column('custo_medio', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'))
    op.add_column('movimentacoes_estoque', sa.Column('valor_unitario', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('pedidos_compra', sa.Column('almoxarifado_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('pedidos_compra') as batch_op:
        batch_op.create_foreign_key(
            'fk_pedidos_compra_almoxarifado_id', 'almoxarifados', ['almoxarifado_id'], ['id']
        )


def downgrade() -> None:
    with op.batch_alter_table('pedidos_compra') as batch_op:
        batch_op.drop_constraint('fk_pedidos_compra_almoxarifado_id', type_='foreignkey')
    op.drop_column('pedidos_compra', 'almoxarifado_id')
    op.drop_column('movimentacoes_estoque', 'valor_unitario')
    op.drop_column('materiais', 'custo_medio')
