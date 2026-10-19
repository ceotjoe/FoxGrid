"""bind participants to the device that joined

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('device_hash', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('participants', 'device_hash')
