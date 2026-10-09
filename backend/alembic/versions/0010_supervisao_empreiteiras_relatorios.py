"""supervisao: empreiteiras e relatorios diarios de campo

Integra o modulo Supervisao ao backend principal. Apenas CRIA duas tabelas novas
(empreiteiras, relatorios_supervisao); nao altera nenhuma tabela existente.
O downgrade remove somente essas duas tabelas.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'empreiteiras',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('nome_razao_social', sa.String(length=160), nullable=False),
        sa.Column('cnpj', sa.String(length=18), nullable=True),
        sa.Column('codigo_contrato', sa.String(length=60), nullable=True),
        sa.Column('ativo', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_empreiteiras_nome_razao_social'), 'empreiteiras', ['nome_razao_social'], unique=False)
    # CNPJ unico quando informado (NULL pode repetir em PostgreSQL e SQLite).
    op.create_index('uq_empreiteiras_cnpj', 'empreiteiras', ['cnpj'], unique=True)

    op.create_table(
        'relatorios_supervisao',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('data_relatorio', sa.Date(), nullable=False),
        sa.Column('projeto_atividade', sa.String(length=200), nullable=True),
        sa.Column('ordem', sa.String(length=60), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Sem status'),
        sa.Column('porcentagem_execucao', sa.Integer(), nullable=True),
        sa.Column('empreiteira_id', sa.Integer(), nullable=True),
        sa.Column('empreiteira_nome_customizado', sa.String(length=160), nullable=True),
        sa.Column('contato', sa.String(length=120), nullable=True),
        sa.Column('lv_lm', sa.String(length=20), nullable=True),
        sa.Column('responsavel', sa.String(length=120), nullable=True),
        sa.Column('codigo_placa', sa.String(length=40), nullable=True),
        sa.Column('supervisor_beq', sa.String(length=120), nullable=True),
        sa.Column('endereco', sa.String(length=255), nullable=True),
        sa.Column('bairro', sa.String(length=120), nullable=True),
        sa.Column('municipio', sa.String(length=120), nullable=True),
        sa.Column('estado', sa.String(length=2), nullable=True),
        sa.Column('composicao_equipe', sa.JSON(none_as_null=True), nullable=True),
        sa.Column('servicos_executados', sa.Text(), nullable=True),
        sa.Column('pendencias', sa.Text(), nullable=True),
        sa.Column('horario_saida_base', sa.Time(), nullable=True),
        sa.Column('horario_chegada_obra', sa.Time(), nullable=True),
        sa.Column('horario_saida_obra', sa.Time(), nullable=True),
        sa.Column('horario_chegada_base', sa.Time(), nullable=True),
        sa.Column('fotos', sa.JSON(none_as_null=True), nullable=True),
        sa.Column('criado_por_id', sa.Integer(), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('atualizado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['empreiteira_id'], ['empreiteiras.id'], ),
        sa.ForeignKeyConstraint(['criado_por_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_relatorios_supervisao_data_relatorio'), 'relatorios_supervisao', ['data_relatorio'], unique=False)
    op.create_index(op.f('ix_relatorios_supervisao_status'), 'relatorios_supervisao', ['status'], unique=False)
    op.create_index(op.f('ix_relatorios_supervisao_empreiteira_id'), 'relatorios_supervisao', ['empreiteira_id'], unique=False)
    op.create_index(op.f('ix_relatorios_supervisao_responsavel'), 'relatorios_supervisao', ['responsavel'], unique=False)
    op.create_index('ix_relatorios_supervisao_data_municipio', 'relatorios_supervisao', ['data_relatorio', 'municipio'], unique=False)


def downgrade() -> None:
    # Remove SOMENTE as tabelas criadas por esta revisao.
    op.drop_index('ix_relatorios_supervisao_data_municipio', table_name='relatorios_supervisao')
    op.drop_index(op.f('ix_relatorios_supervisao_responsavel'), table_name='relatorios_supervisao')
    op.drop_index(op.f('ix_relatorios_supervisao_empreiteira_id'), table_name='relatorios_supervisao')
    op.drop_index(op.f('ix_relatorios_supervisao_status'), table_name='relatorios_supervisao')
    op.drop_index(op.f('ix_relatorios_supervisao_data_relatorio'), table_name='relatorios_supervisao')
    op.drop_table('relatorios_supervisao')
    op.drop_index('uq_empreiteiras_cnpj', table_name='empreiteiras')
    op.drop_index(op.f('ix_empreiteiras_nome_razao_social'), table_name='empreiteiras')
    op.drop_table('empreiteiras')
