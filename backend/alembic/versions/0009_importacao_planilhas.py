"""importacao das planilhas: NECs decimais, campos da medicao, obra arquivada,
dados_planilha, origem em programacoes e 4 tabelas novas (D5)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-05 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

NEC = sa.Numeric(precision=14, scale=3)


def _linha_importada():
    return [
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('obra_id', sa.Integer(), nullable=True),
        sa.Column('projeto_codigo', sa.String(length=60), nullable=False),
        sa.Column('linha_origem', sa.Integer(), nullable=True),
        sa.Column('origem', sa.String(length=40), nullable=False, server_default='planilha'),
        sa.Column('dados_extras', sa.JSON(), nullable=True),
        sa.Column('importado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    ]


def _indices(tabela):
    op.create_index(f'ix_{tabela}_obra_id', tabela, ['obra_id'], unique=False)
    op.create_index(f'ix_{tabela}_projeto_codigo', tabela, ['projeto_codigo'], unique=False)
    op.create_index(f'ix_{tabela}_origem', tabela, ['origem'], unique=False)


def upgrade() -> None:
    # ---- NECs inteiros -> Numeric(14,3) (nao ha perda: inteiro cabe em decimal) ----
    with op.batch_alter_table('obras') as b:
        b.alter_column('necs_planejados', existing_type=sa.Integer(), type_=NEC, existing_nullable=False)
        b.alter_column('necs_executados', existing_type=sa.Integer(), type_=NEC, existing_nullable=False)
        b.alter_column('necs_faturados', existing_type=sa.Integer(), type_=NEC, existing_nullable=False)
        b.add_column(sa.Column('arquivada', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('dados_planilha', sa.JSON(), nullable=True))
    with op.batch_alter_table('medicoes') as b:
        b.alter_column('necs_medidos', existing_type=sa.Integer(), type_=NEC, existing_nullable=False)
        b.add_column(sa.Column('ciclo_medicao', sa.String(length=30), nullable=True))
        b.add_column(sa.Column('area', sa.String(length=40), nullable=True))
        b.add_column(sa.Column('familia', sa.String(length=20), nullable=True))
        b.add_column(sa.Column('valor_faturado', sa.Numeric(14, 2), nullable=True))
        b.add_column(sa.Column('emitida_nf', sa.Boolean(), nullable=True))
        b.add_column(sa.Column('data_emissao_nf', sa.Date(), nullable=True))
        b.add_column(sa.Column('necs_orcados', NEC, nullable=True))
        b.add_column(sa.Column('necs_inventariados', NEC, nullable=True))
        b.add_column(sa.Column('divergencia_necs', NEC, nullable=True))
        b.add_column(sa.Column('valor_pago_por_nec', sa.Numeric(14, 2), nullable=True))
        b.add_column(sa.Column('origem', sa.String(length=40), nullable=True))
        b.create_unique_constraint('uq_medicao_obra_ciclo', ['obra_id', 'ciclo_medicao'])
    op.create_index('ix_medicoes_origem', 'medicoes', ['origem'], unique=False)
    with op.batch_alter_table('faturas') as b:
        b.alter_column('necs_faturados', existing_type=sa.Integer(), type_=NEC, existing_nullable=True)
    with op.batch_alter_table('programacoes') as b:
        b.add_column(sa.Column('origem', sa.String(length=40), nullable=True))
        b.add_column(sa.Column('dados_planilha', sa.JSON(), nullable=True))
    op.create_index('ix_programacoes_origem', 'programacoes', ['origem'], unique=False)

    # ---- Tabelas novas ----
    op.create_table(
        'inventarios_obra', *_linha_importada(),
        sa.Column('familia', sa.String(length=40)),
        sa.Column('valor_orcado', sa.Numeric(14, 2)),
        sa.Column('valor_inventario', sa.Numeric(14, 2)),
        sa.Column('diferenca_saldo', sa.Numeric(14, 2)),
        sa.Column('valor_parcial_solicitado', sa.Numeric(14, 2)),
        sa.Column('valor_pago_parcial', sa.Numeric(14, 2)),
        sa.Column('data_solicitacao_parcial', sa.Date()),
        sa.Column('conclusao', sa.String(length=80)),
        sa.Column('data_inventario', sa.Date()),
        sa.Column('enviado_faturamento_enel', sa.String(length=80)),
        sa.Column('tecnico_responsavel', sa.String(length=120)),
        sa.Column('status', sa.String(length=60)),
        sa.Column('observacao', sa.Text()),
        sa.Column('ciclo_medicao', sa.String(length=30)),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    _indices('inventarios_obra')

    op.create_table(
        'execucoes_obra', *_linha_importada(),
        sa.Column('data', sa.Date()),
        sa.Column('circuito', sa.String(length=80)),
        sa.Column('familia', sa.String(length=40)),
        sa.Column('percentual_executado', sa.Numeric(8, 4)),
        sa.Column('nec_orcado', NEC),
        sa.Column('nec_programada', NEC),
        sa.Column('nec_executada', NEC),
        sa.Column('empresa', sa.String(length=80)),
        sa.Column('status', sa.String(length=60)),
        sa.Column('atraso', sa.String(length=60)),
        sa.Column('observacoes', sa.Text()),
        sa.Column('intervencao', sa.String(length=80)),
        sa.Column('obra_eletricamente_concluida', sa.String(length=40)),
        sa.Column('data_envio_conclusao', sa.Date()),
        sa.Column('qtde_lv', NEC),
        sa.Column('qtde_lm', NEC),
        sa.Column('inventario_aprovado', sa.String(length=40)),
        sa.Column('motivo_reprova', sa.Text()),
        sa.Column('medicao', sa.String(length=60)),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    _indices('execucoes_obra')
    op.create_index('ix_execucoes_obra_data', 'execucoes_obra', ['data'], unique=False)

    op.create_table(
        'sigeo_extracoes', *_linha_importada(),
        sa.Column('data_programacao', sa.Date()),
        sa.Column('status_programacao', sa.String(length=60)),
        sa.Column('tipo_intervencao', sa.String(length=80)),
        sa.Column('numero_poweron', sa.String(length=60)),
        sa.Column('equipamentos', sa.Text()),
        sa.Column('chi', NEC),
        sa.Column('horario_inicio', sa.String(length=8)),
        sa.Column('horario_fim', sa.String(length=8)),
        sa.Column('contratada', sa.String(length=80)),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    _indices('sigeo_extracoes')
    op.create_index('ix_sigeo_extracoes_data_programacao', 'sigeo_extracoes', ['data_programacao'], unique=False)

    op.create_table(
        'geradores_programacao', *_linha_importada(),
        sa.Column('id_origem', sa.String(length=40)),
        sa.Column('status', sa.String(length=60)),
        sa.Column('regional', sa.String(length=60)),
        sa.Column('area', sa.String(length=60)),
        sa.Column('contratada_propria', sa.String(length=60)),
        sa.Column('tecnico_pre_operacao', sa.String(length=120)),
        sa.Column('circuito', sa.String(length=80)),
        sa.Column('equipamento_seccionador', sa.String(length=80)),
        sa.Column('numero', sa.String(length=60)),
        sa.Column('endereco', sa.String(length=255)),
        sa.Column('link', sa.Text()),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    _indices('geradores_programacao')


def downgrade() -> None:
    for t in ('geradores_programacao', 'sigeo_extracoes', 'execucoes_obra', 'inventarios_obra'):
        op.drop_table(t)
    op.drop_index('ix_programacoes_origem', table_name='programacoes')
    with op.batch_alter_table('programacoes') as b:
        b.drop_column('dados_planilha')
        b.drop_column('origem')
    with op.batch_alter_table('faturas') as b:
        b.alter_column('necs_faturados', existing_type=NEC, type_=sa.Integer(), existing_nullable=True)
    op.drop_index('ix_medicoes_origem', table_name='medicoes')
    with op.batch_alter_table('medicoes') as b:
        b.drop_constraint('uq_medicao_obra_ciclo', type_='unique')
        for c in ('origem', 'valor_pago_por_nec', 'divergencia_necs', 'necs_inventariados', 'necs_orcados',
                  'data_emissao_nf', 'emitida_nf', 'valor_faturado', 'familia', 'area', 'ciclo_medicao'):
            b.drop_column(c)
        b.alter_column('necs_medidos', existing_type=NEC, type_=sa.Integer(), existing_nullable=False)
    with op.batch_alter_table('obras') as b:
        b.drop_column('dados_planilha')
        b.drop_column('arquivada')
        b.alter_column('necs_faturados', existing_type=NEC, type_=sa.Integer(), existing_nullable=False)
        b.alter_column('necs_executados', existing_type=NEC, type_=sa.Integer(), existing_nullable=False)
        b.alter_column('necs_planejados', existing_type=NEC, type_=sa.Integer(), existing_nullable=False)
