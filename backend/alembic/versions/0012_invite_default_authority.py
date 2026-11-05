"""invite default authority

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'invites',
        sa.Column('default_authority', sa.String(length=12), server_default='member', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('invites', 'default_authority')
