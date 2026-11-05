"""participant authority (roles and permissions)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-05 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

AUTHORITIES = "('lead','deputy','analyst','coordinator','member','station','observer')"


def upgrade() -> None:
    op.add_column(
        'participants',
        sa.Column('authority', sa.String(length=12), server_default='member', nullable=False),
    )
    # The old `lead` role carried all standing; sensors own a virtual participant that only
    # delivers readings. Everybody else (including human `fixed` stations) stays a member.
    op.execute("UPDATE participants SET authority = 'lead' WHERE role = 'lead'")
    op.execute(
        "UPDATE participants SET authority = 'station' "
        "WHERE id IN (SELECT participant_id FROM sensors)"
    )
    op.create_check_constraint(
        'ck_participant_authority', 'participants', f'authority in {AUTHORITIES}'
    )


def downgrade() -> None:
    op.drop_constraint('ck_participant_authority', 'participants', type_='check')
    op.drop_column('participants', 'authority')
