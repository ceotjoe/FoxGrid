"""external bearing points

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-05 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bearing_points',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('mission_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('lon', sa.Float(), nullable=False),
        sa.Column('accuracy_m', sa.Float(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('use_in_estimate', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['participants.id']),
        sa.ForeignKeyConstraint(['mission_id'], ['missions.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mission_id', 'name', name='uq_bearing_point_name'),
    )
    op.create_index(op.f('ix_bearing_points_mission_id'), 'bearing_points', ['mission_id'])
    op.execute(
        'CREATE TRIGGER trg_bearing_points_no_delete BEFORE DELETE ON bearing_points '
        'FOR EACH ROW EXECUTE FUNCTION forbid_bearing_delete()'
    )
    op.add_column('bearings', sa.Column('point_id', sa.UUID(), nullable=True))
    op.create_foreign_key(
        'fk_bearings_point_id_bearing_points', 'bearings', 'bearing_points', ['point_id'], ['id']
    )
    op.drop_constraint('ck_bearing_source', 'bearings', type_='check')
    op.create_check_constraint(
        'ck_bearing_source', 'bearings', "source in ('manual','sensor','external')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_bearing_source', 'bearings', type_='check')
    op.create_check_constraint('ck_bearing_source', 'bearings', "source in ('manual','sensor')")
    op.drop_constraint('fk_bearings_point_id_bearing_points', 'bearings', type_='foreignkey')
    op.drop_column('bearings', 'point_id')
    op.execute('DROP TRIGGER IF EXISTS trg_bearing_points_no_delete ON bearing_points')
    op.drop_index(op.f('ix_bearing_points_mission_id'), table_name='bearing_points')
    op.drop_table('bearing_points')
