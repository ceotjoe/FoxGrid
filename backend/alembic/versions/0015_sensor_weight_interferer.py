"""mobile stations: sensor weight and default interferer

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-26 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'sensors', sa.Column('weight', sa.Float(), server_default='1', nullable=False)
    )
    op.create_check_constraint('ck_sensor_weight', 'sensors', 'weight >= 0 and weight <= 2')
    op.add_column(
        'sensors', sa.Column('interferer_id', sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        'fk_sensors_interferer_id', 'sensors', 'interferers', ['interferer_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_sensors_interferer_id', 'sensors', type_='foreignkey')
    op.drop_column('sensors', 'interferer_id')
    op.drop_constraint('ck_sensor_weight', 'sensors', type_='check')
    op.drop_column('sensors', 'weight')
