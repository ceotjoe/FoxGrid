# MQTT-Schnittstelle für Peilstationen und Relais-Hook

Automatische Peilstationen und der Relais-Hook melden ihre Daten über MQTT. Ein einzelner Dienst
(`python -m app.mqtt_ingest`, Compose-Service `ingest`) liest die Topics, prüft den Absender und legt
Peilungen, Pegelwerte und Aussendungen in der Datenbank ab. Die App sieht sie wie alle anderen Daten
(Strahlen, Schätzung, Banner, Push); jede Station erscheint als eigener Teilnehmer.

## Einrichten

```bash
docker compose --profile mqtt up -d      # Mosquitto (127.0.0.1:1883) und Ingest-Dienst starten
```

1. Als Lead in der App unter *Sensoren* (oder per API) eine Station anlegen: Name, Art
   (`station` oder `relay`) und bei festen Stationen die Position. **Der API-Schlüssel (`fgs_…`) wird nur
   einmal angezeigt.**
2. Das Gerät verbindet sich mit dem Broker (Benutzer und Passwort aus `.env`, `FOXGRID_MQTT_*`) und
   veröffentlicht auf dem angezeigten Topic-Präfix `foxgrid/<einsatz-id>/<sensor-id>`.

```bash
# Beispielclient: eine Station peilt einen versteckten Sender an
uv run tools/sensor_client/station.py --user foxgrid --password … \
  --mission <einsatz-id> --sensor <sensor-id> --key fgs_… \
  --lat 48.10 --lon 11.50 --truth 48.137 11.575 --count 5
```

## Sicherheit

* Der Broker-Login entscheidet nur, wer mit dem Broker sprechen darf. Jede Nachricht trägt zusätzlich den
  API-Schlüssel der Station im Feld `key`; er wird gegen den gespeicherten Hash geprüft, und Einsatz und
  Sensor müssen zum Topic passen. Eine falsche oder deaktivierte Station wird stillschweigend verworfen
  (nur ein Logeintrag), ohne zu verraten, was falsch war.
* Der Schlüssel steckt in der Nachricht. Wer den Broker über ein unsicheres Netz erreicht, braucht TLS
  (Listener mit Zertifikat in `deploy/mosquitto/mosquitto.conf`). Kompromittierte Stationen lassen sich in
  der App deaktivieren; ihre bisherigen Daten bleiben im Protokoll.
* Pro Station werden höchstens 30 Nachrichten pro Sekunde angenommen (`FOXGRID_MQTT_MAX_MSGS_PER_S`),
  Nachrichten über 64 KB werden verworfen.
* Der Ingest-Dienst darf nur **einmal** laufen, sonst würden Nachrichten doppelt verarbeitet.

## Topics und Nachrichten

Alle Nachrichten sind JSON, QoS 1, Zeiten mit Zeitzone (UTC empfohlen). `key` ist immer Pflicht.
IDs (`id`) erzeugt das Gerät selbst und behält sie bei Wiederholungen bei: Eine erneut zugestellte
Nachricht wird erkannt und ignoriert.

### `foxgrid/<einsatz>/<sensor>/bearing`

```json
{
  "key": "fgs_…",
  "id": "5d9c0f3e-…",
  "azimuth_true_deg": 123.4,
  "sigma_deg": 8.0,
  "measured_at": "2026-10-16T21:15:00Z",
  "lat": 48.10, "lon": 11.50,
  "rssi_dbm": -82.0, "attenuation_db": 0, "polarization": "v", "note": "…"
}
```

`azimuth_true_deg` ist rechtweisend (0 ≤ az < 360), `sigma_deg` ist Pflicht (0 < σ ≤ 90). `lat`/`lon`
fehlen bei festen Stationen: dann gilt die registrierte Position. Ohne beides wird die Nachricht
abgelehnt. `rssi_dbm`, `attenuation_db`, `polarization` (`h`, `v`, `unknown`) und `note` sind optional.

### `foxgrid/<einsatz>/<sensor>/rssi`

Ein einzelner Messwert oder bis zu 100 gesammelt:

```json
{"key": "fgs_…", "id": "…", "rssi_dbm": -90.5, "attenuation_db": 10, "measured_at": "…"}
{"key": "fgs_…", "samples": [{"id": "…", "rssi_dbm": -70, "measured_at": "…", "lat": 48.1, "lon": 11.5}]}
```

### `foxgrid/<einsatz>/<sensor>/status`

Herzschlag, z. B. alle 30 s: `{"key": "fgs_…"}`. Eine Station gilt als *online*, wenn sie in den letzten
zwei Minuten etwas gesendet hat (jede gültige Nachricht zählt).

### `foxgrid/<einsatz>/<sensor>/transmission` (nur Sensoren der Art `relay`)

```json
{"key": "fgs_…", "event": "start", "at": "2026-10-16T21:15:00Z", "note": "Squelch offen ohne CTCSS"}
{"key": "fgs_…", "event": "stop",  "at": "2026-10-16T21:15:42Z"}
```

`start` legt eine Aussendung der Quelle `relay` an (Banner, Push, Zuordnung der Peilungen),
`stop` beendet sie. Ein wiederholtes `start` bei laufender Aussendung und ein `stop` ohne laufende
Aussendung sind harmlos und werden ignoriert. `at` ist optional (Standard: Empfangszeit).

### Antworten des Ingest-Dienstes

Es gibt keine Antwort an das Gerät. Der Dienst protokolliert pro Nachricht `ok`, `duplicate` oder
`rejected:<grund>` (`auth`, `topic`, `payload`, `invalid`, `too_large`, `rate_limited`, `no_position`,
`id_conflict`, `not_relay`, `mission`, `kind`).

## Relais-Hook

`tools/relay_hook/hook.py` meldet „Squelch offen ohne CTCSS“ als Aussendung. Ein Relais öffnet nur für
Nutzer mit dem richtigen CTCSS-Ton; öffnet der Squelch ohne Ton, sendet jemand anderes auf der
Eingabefrequenz.

* **Eingang:** Der Relais-Controller veröffentlicht seinen Zustand auf `relay/<name>/state` als
  `{"squelch": true, "ctcss": false}` (Annahme: der Controller kann MQTT).
* **Entprellung:** Start erst nach `--min-on` Sekunden (Standard 1 s, kurze Störimpulse zählen nicht),
  Stop erst nach `--hang` Sekunden Ruhe (Standard 4 s, kurze Aussetzer eines schwachen Signals teilen eine
  Aussendung nicht). Der Startzeitpunkt ist der Beginn der Störung, der Stopp der letzte Moment.
* **Demo ohne Hardware:** `--simulate` spielt einen legitimen Nutzer, einen Störimpuls und den Störer ab.

```bash
uv run tools/relay_hook/hook.py --broker localhost --user foxgrid --password … \
  --mission <einsatz-id> --sensor <relais-sensor-id> --key fgs_… --relay DB0XYZ [--simulate]
```
