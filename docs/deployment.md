# FoxGrid-Server betreiben (Deployment)

Diese Anleitung beschreibt, wie das Backend auf einem eigenen Server produktiv läuft: ein Linux-Host mit Docker Compose und
Caddy als TLS-Reverse-Proxy. Für die lokale Entwicklung genügt der Abschnitt „Starten“ im [README](../README.md).

Bestandteile (siehe `docker-compose.yml`):

| Dienst | Aufgabe | Pflicht |
|--------|---------|---------|
| `api` | FastAPI/uvicorn, führt beim Start die Alembic-Migrationen aus | ja |
| `db` | PostgreSQL + PostGIS (Volume `dbdata`) | ja |
| `redis` | Live-Events zwischen Workern, Locks, Rate-Limits | ja |
| `mosquitto`, `ingest` | MQTT-Broker und Ingest-Prozess für Sensoren (Profil `mqtt`) | optional |
| Caddy (außerhalb von Compose) | HTTPS, Zertifikate, Reverse-Proxy | ja, für Release-Builds |

## 1. Voraussetzungen

- Linux-Server mit Docker (Compose v2), 1 GB RAM reichen für kleine Einsätze; 2 GB sind komfortabel.
- Ein DNS-Name, der auf den Server zeigt (z. B. `foxgrid.example.org`), und offene Ports **80/443**. Alle anderen Ports bleiben zu.
- Die Apps in den Stores akzeptieren nur **HTTPS** (`serverUrlError` in `join_screen.dart`). Klartext gibt es nur in Debug-Builds.

## 2. Installation

```bash
git clone https://github.com/ceotjoe/FoxGrid.git && cd FoxGrid
cp .env.example .env
```

`.env` anpassen (nie einchecken). Mindestens:

| Variable | Bedeutung |
|----------|-----------|
| `POSTGRES_PASSWORD`, `REDIS_PASSWORD` | eigene, zufällige Werte; Compose bricht ohne sie ab |
| `FOXGRID_JWT_SECRET` | mindestens 32 Zeichen, kein „change-me“; die API startet sonst nicht. Erzeugen: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `FOXGRID_CORS_ORIGINS` | im Betrieb auf die Web-Origin beschränken, z. B. `["https://foxgrid.example.org"]`; Standard ist `*` |
| `FOXGRID_POSTGIS_IMAGE` | PostGIS-Image. **Bei einem bestehenden Datenvolume die Major-Version nie ändern** (siehe Abschnitt 7) |

Wichtige optionale Werte (Standard in Klammern):

- `FOXGRID_JWT_TTL_HOURS` (72) Gültigkeit der Sitzung.
- `FOXGRID_INVITE_TTL_HOURS` (24) und `FOXGRID_INVITE_MAX_USES` (20): Voreinstellungen für Einladungslinks.
- `FOXGRID_RATE_JOIN_PER_MIN` (20), `FOXGRID_RATE_MISSION_PER_MIN` (5), `…_BEARING_…` (120), `…_RSSI_…` (600), `…_MESSAGE_…` (30); `0` schaltet ein Limit ab.
- `FOXGRID_ENABLE_DOCS` (aus): macht `/docs` und `/openapi.json` sichtbar. Im Betrieb aus lassen.
- `FOXGRID_API_BIND` (`127.0.0.1`): API nur lokal binden, damit der Proxy der einzige Zugang ist. `0.0.0.0` nur für Tests im LAN.

Starten:

```bash
docker compose up -d --build
docker compose logs -f api          # Migrationen und Start beobachten
curl http://127.0.0.1:8000/healthz  # {"status":"ok"}
```

API, Datenbank und Redis lauschen nur auf `127.0.0.1`. Die Datenbank-Ports nie nach außen öffnen.

## 3. HTTPS mit Caddy

`deploy/Caddyfile` ist eine fertige Vorlage: automatische Let's-Encrypt-Zertifikate, Sicherheits-Header und ein Log, in dem der
WebSocket-`?token=` unkenntlich gemacht wird.

1. Caddy auf dem Host installieren (Paket der Distribution oder [caddyserver.com](https://caddyserver.com/docs/install)).
2. `deploy/Caddyfile` nach `/etc/caddy/Caddyfile` kopieren und `foxgrid.example.org` durch den eigenen Namen ersetzen.
3. Das Log-Verzeichnis anlegen (`/var/log/caddy`, Besitzer `caddy`) und `systemctl reload caddy` ausführen.
4. Prüfen: `curl https://foxgrid.example.org/healthz`.

WebSockets laufen ohne weitere Einstellung durch `reverse_proxy`.

### Echte Client-Adresse für die Rate-Limits

Beitritte werden pro Client-Adresse gezählt. Hinter dem Proxy sieht uvicorn sonst nur die Adresse des Proxys, und alle Nutzer teilen sich
ein Limit. Deshalb muss `FORWARDED_ALLOW_IPS` auf die Adresse gesetzt werden, von der der Proxy die Verbindung aufbaut. Niemals `*`, sonst
kann jeder Client `X-Forwarded-For` fälschen und die Limits umgehen.

Compose reicht diese Variable nicht von selbst durch. Sie wird im Dienst `api` ergänzt, am besten in einer `docker-compose.override.yml`
neben der Hauptdatei:

```yaml
services:
  api:
    environment:
      FORWARDED_ALLOW_IPS: "172.17.0.1"   # Gateway-Adresse des Docker-Netzes, siehe unten
```

Die Adresse, die die API für Caddy sieht, steht im Log, oder man liest sie mit `docker network inspect` (Feld `Gateway`) aus.
Danach `docker compose up -d api`. Ob es greift, zeigt ein Beitritt von zwei Geräten mit unterschiedlichen Adressen im Sicherheits-Log
(`GET /missions/{id}/audit`).

## 4. Mehrere Worker

Standardmäßig startet der Container einen uvicorn-Prozess. Für mehr Last kann `--workers N` ergänzt werden; Redis verteilt die Live-Events
zwischen den Workern. Dazu im `api`-Dienst `command` überschreiben:

```yaml
    command: ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 4"]
```

Für einen Amateurfunk-Einsatz mit Dutzenden Teilnehmern reicht meist ein Worker.

## 5. Optional: MQTT-Sensoren

Für Messstationen und den Relais-Hook (siehe [mqtt.md](mqtt.md)):

```bash
# in .env: FOXGRID_MQTT_PASSWORD setzen
docker compose --profile mqtt up -d --build
```

- Der Ingest-Prozess (`ingest`) muss **genau einmal** laufen, nicht pro API-Worker.
- Das Passwort ist in `.env` optional, damit `docker compose up` auch ohne MQTT geht. Der Broker startet aber nicht ohne Passwort.
- Der Broker lauscht nur auf `127.0.0.1:1883`. Für externe Sensoren einen TLS-Listener nach `deploy/mosquitto/mosquitto.conf` einrichten,
  nicht den Klartext-Port freigeben.

## 6. Optional: Push-Benachrichtigungen

Serverseitig reichen zwei Werte in `.env`: `FOXGRID_FCM_PROJECT_ID` und `FOXGRID_FCM_CREDENTIALS_FILE`. Die Datei mit dem Service-Account-
Schlüssel muss im `api`-Container unter diesem Pfad liegen (z. B. als schreibgeschütztes Volume nach `/run/secrets/…` einhängen und nie ins
Repository legen). Ohne Konfiguration werden Pushes nur geloggt. Die App registriert ihr Token selbst, wenn sie mit den Firebase-Dateien gebaut wurde, siehe README, Abschnitt
„Push-Benachrichtigungen einrichten“.

## 7. Betrieb

### Datensicherung

Alle Daten liegen in PostgreSQL. Peilungen werden nie gelöscht (ein DB-Trigger verbietet `DELETE`), sie sind also der Prüfpfad eines Einsatzes
und sollten gesichert werden. Redis enthält nur flüchtige Zustände und braucht kein Backup.

```bash
# Sicherung (täglich per Cron, Ausgabe auf ein anderes Medium kopieren)
docker compose exec -T db pg_dump -U foxgrid -d foxgrid --format=custom > foxgrid-$(date +%F).dump

# Wiederherstellen in eine leere Datenbank
docker compose stop api
docker compose exec -T db dropdb -U foxgrid foxgrid && docker compose exec -T db createdb -U foxgrid foxgrid
docker compose exec -T db psql -U foxgrid -d foxgrid -c "CREATE EXTENSION IF NOT EXISTS postgis;"
docker compose exec -T db pg_restore -U foxgrid -d foxgrid --no-owner < foxgrid-2026-01-01.dump
docker compose start api
```

Benutzer und Datenbankname entsprechen den Werten `POSTGRES_USER` und `POSTGRES_DB` aus `.env`. Die Wiederherstellung einmal auf einem
Testsystem durchspielen, bevor man sie braucht.

### Update

```bash
git pull
docker compose up -d --build     # baut neu, die API führt "alembic upgrade head" beim Start aus
docker compose logs --tail=50 api
```

- Vorher eine Sicherung ziehen. Migrationen lassen sich nicht automatisch zurückdrehen.
- Mit mehreren Workern laufen die Migrationen im selben Startbefehl; bei einem Update die API zuerst mit einem Worker starten.
- Die PostGIS-**Major-Version** (z. B. 16 → 17) nicht einfach im Image ändern: ein vorhandenes Datenverzeichnis startet damit nicht. Dafür
  `pg_dump` mit dem alten und `pg_restore` mit dem neuen Image verwenden.
- Beachten: `.env.example` setzt `postgis/postgis:16-3.4`, der Standard in `docker-compose.yml` ohne diese Variable ist `17-3.5`. Auf einem
  laufenden System darf sich der Wert nie ändern.

### Aufbewahrung

Ein Einsatz hat `track_retention_days` (Standard 30). Positionsspuren werden danach automatisch gelöscht; die API prüft das stündlich
(`FOXGRID_TRACK_PURGE_INTERVAL_S`, 3600) und loggt `purged … expired position samples`. Peilungen und RSSI-Messwerte bleiben erhalten.
Die Datenschutzhinweise ([privacy.md](privacy.md)) müssen zu den gewählten Fristen passen.

### Überwachung und Logs

- Gesundheitsprüfung: `GET /healthz` (auch für einen externen Monitor wie Uptime Kuma geeignet).
- Logs: `docker compose logs -f api`; Zugriffe in `/var/log/caddy/foxgrid.log` (Token sind geschwärzt). Docker-Logs mit
  `logging: { driver: local }` oder einer `daemon.json`-Rotation begrenzen, sonst wachsen sie unbegrenzt.
- Neustart nach Absturz: der `api`-Dienst hat `restart: on-failure`. Mit `restart: unless-stopped` im Override übersteht er auch einen Reboot
  des Hosts, vorausgesetzt Docker startet beim Booten (`systemctl enable docker`).

## 8. Checkliste vor dem ersten Einsatz

- [ ] Alle `change-me`-Werte in `.env` ersetzt, `.env` nicht im Repository
- [ ] `FOXGRID_CORS_ORIGINS` auf die Web-Origin gesetzt
- [ ] HTTPS erreichbar, `curl https://…/healthz` liefert `ok`
- [ ] Ports 5432, 6379, 8000 und 1883 sind von außen nicht erreichbar (von einem fremden Rechner prüfen)
- [ ] `FORWARDED_ALLOW_IPS` auf die Proxy-Adresse gesetzt (nicht `*`)
- [ ] Tägliche Sicherung eingerichtet und eine Wiederherstellung getestet
- [ ] Einladungslinks laufen ab und sind begrenzt (Standardwerte prüfen), siehe [sicherheit.md](sicherheit.md)
- [ ] Mit zwei Geräten einen Test-Einsatz durchgespielt (Beitritt, Peilung, Schätzung erscheint live)
