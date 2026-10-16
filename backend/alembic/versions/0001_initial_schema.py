"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-16 23:21:29.168452
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis')
    op.create_table('missions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('frequency_mhz', sa.Numeric(precision=8, scale=4), nullable=False),
    sa.Column('search_area', geoalchemy2.types.Geography(geometry_type='POLYGON', srid=4326, dimension=2, from_text='ST_GeogFromText', name='geography'), nullable=True),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('track_retention_days', sa.Integer(), nullable=False),
    sa.Column('engine_params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("status in ('active','ended')", name='ck_mission_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('invites',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('default_role', sa.String(length=10), nullable=False),
    sa.Column('max_uses', sa.Integer(), nullable=True),
    sa.Column('uses', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_invites_mission_id'), 'invites', ['mission_id'], unique=False)
    op.create_table('teams',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mission_id', 'name', name='uq_team_name')
    )
    op.create_table('participants',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('callsign', sa.String(length=20), nullable=False),
    sa.Column('role', sa.String(length=10), nullable=False),
    sa.Column('team_id', sa.UUID(), nullable=True),
    sa.Column('joined_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.CheckConstraint("role in ('lead','fixed','mobile')", name='ck_participant_role'),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mission_id', 'callsign', name='uq_participant_callsign')
    )
    op.create_index(op.f('ix_participants_mission_id'), 'participants', ['mission_id'], unique=False)
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('entity', sa.String(length=50), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['participants.id'], ),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_log_mission_id'), 'audit_log', ['mission_id'], unique=False)
    op.create_table('position_samples',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('heading_deg', sa.Float(), nullable=True),
    sa.Column('speed_mps', sa.Float(), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_position_mission_time', 'position_samples', ['mission_id', 'recorded_at'], unique=False)
    op.create_index('ix_position_participant_time', 'position_samples', ['participant_id', 'recorded_at'], unique=False)
    op.create_table('transmissions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.Column('started_by', sa.UUID(), nullable=True),
    sa.Column('ended_by', sa.UUID(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.CheckConstraint("source in ('manual','relay','mqtt')", name='ck_transmission_source'),
    sa.ForeignKeyConstraint(['ended_by'], ['participants.id'], ),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.ForeignKeyConstraint(['started_by'], ['participants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('mission_id', 'seq', name='uq_transmission_seq')
    )
    op.create_index('uq_one_open_transmission', 'transmissions', ['mission_id'], unique=True, postgresql_where=sa.text('ended_at IS NULL'))
    op.create_table('bearings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('participant_id', sa.UUID(), nullable=False),
    sa.Column('transmission_id', sa.UUID(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('station_accuracy_m', sa.Float(), nullable=True),
    sa.Column('azimuth_true_deg', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('azimuth_input_ref', sa.String(length=10), nullable=False),
    sa.Column('declination_deg_applied', sa.Float(), nullable=False),
    sa.Column('sigma_deg', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('rssi_dbm', sa.Float(), nullable=True),
    sa.Column('s_meter', sa.Float(), nullable=True),
    sa.Column('attenuation_db', sa.Float(), nullable=False),
    sa.Column('polarization', sa.String(length=10), nullable=False),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('is_outlier', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=10), nullable=False),
    sa.CheckConstraint("azimuth_input_ref in ('true','magnetic','compass')", name='ck_bearing_ref'),
    sa.CheckConstraint("polarization in ('h','v','unknown')", name='ck_bearing_pol'),
    sa.CheckConstraint("source in ('manual','sensor')", name='ck_bearing_source'),
    sa.CheckConstraint('azimuth_true_deg >= 0 AND azimuth_true_deg < 360', name='ck_bearing_az'),
    sa.CheckConstraint('sigma_deg > 0 AND sigma_deg <= 90', name='ck_bearing_sigma'),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.ForeignKeyConstraint(['participant_id'], ['participants.id'], ),
    sa.ForeignKeyConstraint(['transmission_id'], ['transmissions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bearing_mission_measured', 'bearings', ['mission_id', 'measured_at'], unique=False)
    op.create_index(op.f('ix_bearings_mission_id'), 'bearings', ['mission_id'], unique=False)
    op.create_table('estimates',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('mission_id', sa.UUID(), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scope', sa.String(length=10), nullable=False),
    sa.Column('transmission_id', sa.UUID(), nullable=True),
    sa.Column('input_hash', sa.String(length=64), nullable=False),
    sa.Column('n_bearings', sa.Integer(), nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('lat', sa.Float(), nullable=False),
    sa.Column('lon', sa.Float(), nullable=False),
    sa.Column('cov_ee', sa.Float(), nullable=False),
    sa.Column('cov_nn', sa.Float(), nullable=False),
    sa.Column('cov_en', sa.Float(), nullable=False),
    sa.Column('ellipse_1s', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ellipse_2s', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("scope in ('current','all')", name='ck_estimate_scope'),
    sa.ForeignKeyConstraint(['mission_id'], ['missions.id'], ),
    sa.ForeignKeyConstraint(['transmission_id'], ['transmissions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_estimate_mission_scope_time', 'estimates', ['mission_id', 'scope', 'computed_at'], unique=False)
    op.create_table('bearing_revisions',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('bearing_id', sa.UUID(), nullable=False),
    sa.Column('changed_by', sa.UUID(), nullable=False),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['bearing_id'], ['bearings.id'], ),
    sa.ForeignKeyConstraint(['changed_by'], ['participants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bearing_revisions_bearing_id'), 'bearing_revisions', ['bearing_id'], unique=False)
    # ### end Alembic commands ###

    # Generated PostGIS columns derived from lat/lon (kept out of the ORM on purpose).
    for table in ('position_samples', 'bearings', 'estimates'):
        op.execute(
            f'ALTER TABLE {table} ADD COLUMN geom geography(Point,4326) GENERATED ALWAYS AS '
            '(ST_SetSRID(ST_MakePoint(lon, lat), 4326)::geography) STORED'
        )
        op.execute(f'CREATE INDEX ix_{table}_geom ON {table} USING gist (geom)')

    # The bearing log must stay complete: bearings can be flagged, never deleted.
    op.execute(
        """
        CREATE FUNCTION forbid_bearing_delete() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'bearings are append-only and cannot be deleted';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        'CREATE TRIGGER trg_bearings_no_delete BEFORE DELETE ON bearings '
        'FOR EACH ROW EXECUTE FUNCTION forbid_bearing_delete()'
    )
    op.execute(
        'CREATE TRIGGER trg_bearing_revisions_no_delete BEFORE DELETE ON bearing_revisions '
        'FOR EACH ROW EXECUTE FUNCTION forbid_bearing_delete()'
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_bearing_revisions_no_delete ON bearing_revisions')
    op.execute('DROP TRIGGER IF EXISTS trg_bearings_no_delete ON bearings')
    op.execute('DROP FUNCTION IF EXISTS forbid_bearing_delete()')
    op.drop_index(op.f('ix_bearing_revisions_bearing_id'), table_name='bearing_revisions')
    op.drop_table('bearing_revisions')
    op.drop_index('ix_estimate_mission_scope_time', table_name='estimates')
    op.drop_table('estimates')
    op.drop_index(op.f('ix_bearings_mission_id'), table_name='bearings')
    op.drop_index('ix_bearing_mission_measured', table_name='bearings')
    op.drop_table('bearings')
    op.drop_index('uq_one_open_transmission', table_name='transmissions', postgresql_where=sa.text('ended_at IS NULL'))
    op.drop_table('transmissions')
    op.drop_index('ix_position_participant_time', table_name='position_samples')
    op.drop_index('ix_position_mission_time', table_name='position_samples')
    op.drop_table('position_samples')
    op.drop_index(op.f('ix_audit_log_mission_id'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_participants_mission_id'), table_name='participants')
    op.drop_table('participants')
    op.drop_table('teams')
    op.drop_index(op.f('ix_invites_mission_id'), table_name='invites')
    op.drop_table('invites')
    op.drop_table('missions')
    # ### end Alembic commands ###
