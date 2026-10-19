"""lead approval for new participants

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-19 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participants', sa.Column('status', sa.String(length=10), server_default='active', nullable=False))
    op.create_check_constraint('ck_participant_status', 'participants', "status in ('pending','active','rejected')")
    op.add_column('invites', sa.Column('auto_approve', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('invites', 'auto_approve')
    op.drop_constraint('ck_participant_status', 'participants', type_='check')
    op.drop_column('participants', 'status')
