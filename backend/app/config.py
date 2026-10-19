from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from FOXGRID_* environment variables or `.env`."""

    model_config = SettingsConfigDict(env_prefix="FOXGRID_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://foxgrid:foxgrid@localhost:5432/foxgrid"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str  # required, no default on purpose
    jwt_ttl_hours: int = 72
    # Defaults for invite links; a leaked link should stop working on its own.
    invite_ttl_hours: int = 24
    invite_max_uses: int = 20
    # Requests per minute (0 = off). Joins are counted per client address (set
    # FORWARDED_ALLOW_IPS for uvicorn behind a proxy), the rest per participant;
    # bearings and readings count per item.
    rate_join_per_min: int = 20
    rate_bearing_per_min: int = 120
    rate_rssi_per_min: int = 600
    rate_message_per_min: int = 30
    position_min_interval_s: int = 5
    recompute_debounce_ms: int = 500
    recompute_max_wait_ms: int = 2000
    track_purge_interval_s: int = 3600
    # Browser clients (Flutter web) need CORS. Auth is a bearer token (no cookies), so '*' is safe;
    # restrict to your web origin in production.
    # Push via Firebase Cloud Messaging (HTTP v1). Without credentials pushes are only logged.
    fcm_project_id: str | None = None
    fcm_credentials_file: str | None = None
    # MQTT ingest (separate process: python -m app.mqtt_ingest)
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_max_msgs_per_s: int = 30  # per sensor; floods are dropped
    cors_origins: list[str] = ["*"]
