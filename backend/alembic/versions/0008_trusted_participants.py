"""trusted flag: only trusted participants feed the estimate

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-19 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('trusted', sa.Boolean(), server_default='true', nullable=False))


def downgrade() -> None:
    op.drop_column('participants', 'trusted')
