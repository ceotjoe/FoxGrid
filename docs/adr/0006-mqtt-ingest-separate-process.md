# 0006 – MQTT ingest as its own process

**Status:** accepted

**Context.** Automatic bearing stations and a repeater hook report over MQTT. With multiple API workers, an in-process subscriber
would handle every message N times.

**Decision.** The ingest runs once as `python -m app.mqtt_ingest` (Compose profile `mqtt`) and calls the same service functions as
the REST API. Each sensor owns a virtual participant and an API key (`fgs_…`, only the hash stored) that is part of every message.

**Consequences.** Exactly-once processing, but one more service to run. The key travels in each message, so external stations need
TLS at the broker. See [MQTT interface](../reference/mqtt.md).
