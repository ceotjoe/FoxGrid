"""retroactive bearings: entry_mode

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-24 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'bearings',
        sa.Column('entry_mode', sa.String(length=12), server_default='live', nullable=False),
    )
    op.create_check_constraint(
        'ck_bearing_entry_mode', 'bearings', "entry_mode in ('live','retroactive')"
    )


def downgrade() -> None:
    op.drop_constraint('ck_bearing_entry_mode', 'bearings', type_='check')
    op.drop_column('bearings', 'entry_mode')
