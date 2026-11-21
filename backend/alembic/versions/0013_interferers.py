"""several interferers per mission

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-21 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

DEFAULT_NAME = 'Störer 1'


def upgrade() -> None:
    op.create_table(
        'interferers',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('mission_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('color_slot', sa.Integer(), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('frequency_mhz', sa.Numeric(8, 4), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='active', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['participants.id']),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mission_id', 'name', name='uq_interferer_name'),
        sa.CheckConstraint("status in ('active','resolved')", name='ck_interferer_status'),
        sa.CheckConstraint('color_slot >= 0 AND color_slot < 6', name='ck_interferer_color_slot'),
    )
    op.create_index(op.f('ix_interferers_mission_id'), 'interferers', ['mission_id'])
    op.execute(
        'CREATE TRIGGER trg_interferers_no_delete BEFORE DELETE ON interferers '
        'FOR EACH ROW EXECUTE FUNCTION forbid_bearing_delete()'
    )

    # Every existing mission gets one interferer that takes over all of its data.
    op.execute(
        "INSERT INTO interferers (id, mission_id, name, color_slot, status, is_active, "
        "created_by, created_at) "
        "SELECT gen_random_uuid(), m.id, '" + DEFAULT_NAME + "', 0, 'active', true, "
        "(SELECT p.id FROM participants p WHERE p.mission_id = m.id "
        " ORDER BY p.joined_at LIMIT 1), now() FROM missions m"
    )

    for table in ('bearings', 'rssi_samples', 'estimates'):
        op.add_column(table, sa.Column('interferer_id', sa.UUID(), nullable=True))
        op.execute(
            f'UPDATE {table} SET interferer_id = '
            f'(SELECT i.id FROM interferers i WHERE i.mission_id = {table}.mission_id)'
        )
        op.alter_column(table, 'interferer_id', nullable=False)
        op.create_foreign_key(
            f'fk_{table}_interferer_id_interferers', table, 'interferers', ['interferer_id'], ['id']
        )
    op.create_index(op.f('ix_bearings_interferer_id'), 'bearings', ['interferer_id'])
    op.create_index(op.f('ix_rssi_samples_interferer_id'), 'rssi_samples', ['interferer_id'])
    op.create_index(
        'ix_estimate_interferer_scope_time',
        'estimates',
        ['interferer_id', 'scope', 'computed_at'],
    )

    op.add_column('transmissions', sa.Column('interferer_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_transmissions_interferer_id_interferers',
        'transmissions',
        'interferers',
        ['interferer_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_transmissions_interferer_id_interferers', 'transmissions', type_='foreignkey'
    )
    op.drop_column('transmissions', 'interferer_id')
    op.drop_index('ix_estimate_interferer_scope_time', table_name='estimates')
    op.drop_index(op.f('ix_rssi_samples_interferer_id'), table_name='rssi_samples')
    op.drop_index(op.f('ix_bearings_interferer_id'), table_name='bearings')
    for table in ('estimates', 'rssi_samples', 'bearings'):
        op.drop_constraint(f'fk_{table}_interferer_id_interferers', table, type_='foreignkey')
        op.drop_column(table, 'interferer_id')
    op.execute('DROP TRIGGER IF EXISTS trg_interferers_no_delete ON interferers')
    op.drop_index(op.f('ix_interferers_mission_id'), table_name='interferers')
    op.drop_table('interferers')
