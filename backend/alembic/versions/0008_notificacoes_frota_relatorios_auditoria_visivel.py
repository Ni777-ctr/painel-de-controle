"""notificacoes, frota, execucoes de automacao, relatorios gerados,
auditoria visivel (categoria/ip/user-agent), preferencia de e-mail

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- audit_logs: categoria, ip, user_agent + indices ----
    op.add_column('audit_logs', sa.Column('categoria', sa.String(length=20), nullable=False, server_default='alteracao'))
    op.add_column('audit_logs', sa.Column('ip', sa.String(length=45), nullable=True))
    op.add_column('audit_logs', sa.Column('user_agent', sa.String(length=255), nullable=True))
    op.create_index('ix_audit_logs_criado_em', 'audit_logs', ['criado_em'], unique=False)
    op.create_index('ix_audit_logs_categoria_criado_em', 'audit_logs', ['categoria', 'criado_em'], unique=False)

    # Backfill das linhas antigas com a mesma regra usada em runtime.
    from app.auditoria_utils import classificar_acao

    bind = op.get_bind()
    acoes = [row[0] for row in bind.execute(sa.text("SELECT DISTINCT acao FROM audit_logs"))]
    for acao in acoes:
        bind.execute(
            sa.text("UPDATE audit_logs SET categoria = :cat WHERE acao = :acao"),
            {"cat": classificar_acao(acao), "acao": acao},
        )

    # ---- usuarios: preferencia de e-mail ----
    op.add_column('usuarios', sa.Column('notificacoes_email', sa.Boolean(), nullable=False, server_default=sa.true()))

    # ---- veiculos / manutencoes ----
    op.create_table(
        'veiculos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('placa', sa.String(length=10), nullable=False),
        sa.Column('modelo', sa.String(length=80), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=True),
        sa.Column('ano', sa.Integer(), nullable=True),
        sa.Column('regional', sa.String(length=60), nullable=True),
        sa.Column('equipe_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Ativo'),
        sa.Column('km_atual', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('licenciamento_vence_em', sa.Date(), nullable=True),
        sa.Column('seguro_vence_em', sa.Date(), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['equipe_id'], ['equipes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_veiculos_placa'), 'veiculos', ['placa'], unique=True)

    op.create_table(
        'manutencoes_veiculo',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('veiculo_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False, server_default='Preventiva'),
        sa.Column('descricao', sa.String(length=255), nullable=False),
        sa.Column('data_prevista', sa.Date(), nullable=True),
        sa.Column('data_realizada', sa.Date(), nullable=True),
        sa.Column('km', sa.Integer(), nullable=True),
        sa.Column('custo', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='Agendada'),
        sa.Column('observacoes', sa.Text(), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['veiculo_id'], ['veiculos.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_manutencoes_veiculo_veiculo_id'), 'manutencoes_veiculo', ['veiculo_id'], unique=False)

    # ---- execucoes_automacao ----
    op.create_table(
        'execucoes_automacao',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('automacao_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('mensagem', sa.String(length=500), nullable=True),
        sa.Column('duracao_ms', sa.Integer(), nullable=True),
        sa.Column('iniciado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['automacao_id'], ['automacoes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_execucoes_automacao_automacao_id'), 'execucoes_automacao', ['automacao_id'], unique=False)

    # ---- notificacoes ----
    op.create_table(
        'notificacoes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=50), nullable=False),
        sa.Column('modulo', sa.String(length=30), nullable=False),
        sa.Column('nivel', sa.String(length=20), nullable=False, server_default='atencao'),
        sa.Column('titulo', sa.String(length=160), nullable=False),
        sa.Column('mensagem', sa.Text(), nullable=False),
        sa.Column('entidade', sa.String(length=40), nullable=True),
        sa.Column('entidade_id', sa.String(length=40), nullable=True),
        sa.Column('chave_dedup', sa.String(length=120), nullable=False),
        sa.Column('lida', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('lida_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('email_status', sa.String(length=15), nullable=True),
        sa.Column('email_tentativas', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('email_enviado_em', sa.DateTime(timezone=True), nullable=True),
        sa.Column('email_erro', sa.String(length=255), nullable=True),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usuario_id', 'chave_dedup', name='uq_notificacao_usuario_chave'),
    )
    op.create_index('ix_notificacoes_usuario_lida', 'notificacoes', ['usuario_id', 'lida'], unique=False)

    # ---- relatorios_gerados ----
    op.create_table(
        'relatorios_gerados',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('usuario_id', sa.Integer(), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('formato', sa.String(length=10), nullable=False),
        sa.Column('periodo_inicio', sa.Date(), nullable=True),
        sa.Column('periodo_fim', sa.Date(), nullable=True),
        sa.Column('obra_id', sa.Integer(), nullable=True),
        sa.Column('responsavel_usuario_id', sa.Integer(), nullable=True),
        sa.Column('filtros', sa.JSON(), nullable=True),
        sa.Column('nome_arquivo', sa.String(length=160), nullable=False),
        sa.Column('linhas', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('tamanho_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('criado_em', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['usuarios.id'], ),
        sa.ForeignKeyConstraint(['obra_id'], ['obras.id'], ),
        sa.ForeignKeyConstraint(['responsavel_usuario_id'], ['usuarios.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_relatorios_gerados_usuario_id'), 'relatorios_gerados', ['usuario_id'], unique=False)
    op.create_index('ix_relatorios_tipo_criado_em', 'relatorios_gerados', ['tipo', 'criado_em'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_relatorios_tipo_criado_em', table_name='relatorios_gerados')
    op.drop_index(op.f('ix_relatorios_gerados_usuario_id'), table_name='relatorios_gerados')
    op.drop_table('relatorios_gerados')

    op.drop_index('ix_notificacoes_usuario_lida', table_name='notificacoes')
    op.drop_table('notificacoes')

    op.drop_index(op.f('ix_execucoes_automacao_automacao_id'), table_name='execucoes_automacao')
    op.drop_table('execucoes_automacao')

    op.drop_index(op.f('ix_manutencoes_veiculo_veiculo_id'), table_name='manutencoes_veiculo')
    op.drop_table('manutencoes_veiculo')
    op.drop_index(op.f('ix_veiculos_placa'), table_name='veiculos')
    op.drop_table('veiculos')

    op.drop_column('usuarios', 'notificacoes_email')

    op.drop_index('ix_audit_logs_categoria_criado_em', table_name='audit_logs')
    op.drop_index('ix_audit_logs_criado_em', table_name='audit_logs')
    op.drop_column('audit_logs', 'user_agent')
    op.drop_column('audit_logs', 'ip')
    op.drop_column('audit_logs', 'categoria')
