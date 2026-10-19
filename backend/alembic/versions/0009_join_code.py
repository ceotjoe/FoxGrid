"""spoken join code for pending participants

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-19 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('join_code', sa.String(length=4), nullable=True))


def downgrade() -> None:
    op.drop_column('participants', 'join_code')
