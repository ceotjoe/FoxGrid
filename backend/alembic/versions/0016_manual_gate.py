"""manual gate: bearing windows, gate state and override, gated sensors

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-26 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bearings', sa.Column('window_start', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bearings', sa.Column('window_end', sa.DateTime(timezone=True), nullable=True))
    op.add_column('bearings', sa.Column('gate_state', sa.String(length=8), nullable=True))
    op.add_column('bearings', sa.Column('gate_override', sa.Boolean(), nullable=True))
    op.create_check_constraint(
        'ck_bearing_gate_state', 'bearings', "gate_state in ('inside','outside')"
    )
    op.add_column(
        'sensors', sa.Column('gated', sa.Boolean(), server_default='false', nullable=False)
    )


def downgrade() -> None:
    op.drop_column('sensors', 'gated')
    op.drop_constraint('ck_bearing_gate_state', 'bearings', type_='check')
    op.drop_column('bearings', 'gate_override')
    op.drop_column('bearings', 'gate_state')
    op.drop_column('bearings', 'window_end')
    op.drop_column('bearings', 'window_start')
