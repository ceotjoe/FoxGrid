"""omnidirectional stations: repeater reference and receiver kind

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('missions', sa.Column('repeater_lat', sa.Float(), nullable=True))
    op.add_column('missions', sa.Column('repeater_lon', sa.Float(), nullable=True))
    op.add_column('missions', sa.Column('repeater_input_mhz', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('missions', sa.Column('repeater_output_mhz', sa.Numeric(precision=8, scale=4), nullable=True))
    op.add_column('rssi_samples', sa.Column('receiver', sa.String(length=6), server_default='mobile', nullable=False))
    op.add_column('rssi_samples', sa.Column('is_calibration', sa.Boolean(), server_default='false', nullable=False))
    op.create_check_constraint('ck_rssi_receiver', 'rssi_samples', "receiver in ('mobile','omni')")
    op.create_check_constraint('ck_rssi_calibration', 'rssi_samples', "not is_calibration or receiver = 'omni'")


def downgrade() -> None:
    op.drop_constraint('ck_rssi_calibration', 'rssi_samples', type_='check')
    op.drop_constraint('ck_rssi_receiver', 'rssi_samples', type_='check')
    op.drop_column('rssi_samples', 'is_calibration')
    op.drop_column('rssi_samples', 'receiver')
    op.drop_column('missions', 'repeater_output_mhz')
    op.drop_column('missions', 'repeater_input_mhz')
    op.drop_column('missions', 'repeater_lon')
    op.drop_column('missions', 'repeater_lat')
