# FoxGrid – Phase 0: Plan

Stand: Entwurf zur Freigabe. Kein Code, nur Schema, API und offene Fragen.

## 1. Architektur in Kürze

```
Flutter (iOS/Android/Web) ──REST/WS──► FastAPI (n Worker) ──► PostgreSQL+PostGIS
   Drift (offline queue)                    │  ▲
                                            ▼  │ Pub/Sub
                                          Redis ──► WS-Fan-out an alle Worker
                                            │
                       Recompute-Job (Debounce 500 ms, pro Einsatz) ──► foxgrid_engine
```

- **Recompute**: Bearing-Write → Redis-Key `recompute:{mission}` mit 500 ms Debounce → genau ein Worker (Redis-Lock) ruft die Engine in einem Threadpool auf → speichert `estimates` → Event `estimate_updated`.
- **Engine** bekommt reine Datenstrukturen (Liste von Bearings, Params) und liefert Ergebnis-Dataclasses. Keine DB-Kenntnis.
- **Idempotenz**: `bearings.id` = Client-UUID (PK). `POST` mit vorhandener ID und identischem Inhalt → 200 mit bestehendem Objekt; abweichender Inhalt → 409.
- **Unveränderlichkeit**: kein `DELETE`-Endpunkt; DB-Trigger verhindert `DELETE` auf `bearings`. Änderungen (Ausreißer, Deaktivierung, Notiz) erzeugen Zeilen in `bearing_revisions`.

## 2. Datenbankschema (PostgreSQL 16 + PostGIS)

Alle Geometrien `geography(Point,4326)`, Zeiten `timestamptz` (UTC), IDs `uuid` sofern nicht anders genannt.

### Kern

| Tabelle | Spalten (Auswahl) | Hinweise |
|---|---|---|
| `missions` | id, name, frequency_mhz numeric(8,4), search_area geography(Polygon), status enum(`active`,`ended`), created_at, ended_at, track_retention_days int default 30, engine_params jsonb | `engine_params`: Zellgröße, ε, Halbwertszeit, Scope-Default |
| `invites` | id, mission_id, token_hash, default_role, max_uses, uses, expires_at, revoked_at | Token nur als Hash; Klartext nur einmal bei Erzeugung |
| `teams` | id, mission_id, name | unique(mission_id,name) |
| `participants` | id, mission_id, callsign, role enum(`lead`,`fixed`,`mobile`), team_id, joined_at, last_seen_at, is_active | unique(mission_id, callsign) |
| `position_samples` | id bigserial, mission_id, participant_id, geom, accuracy_m, heading_deg, speed_mps, recorded_at (Client), received_at | Index(mission_id, recorded_at), GiST(geom); Purge-Job nach Einsatzende + Frist |
| `transmissions` | id, mission_id, seq int, started_at, ended_at, source enum(`manual`,`relay`,`mqtt`), started_by, ended_by, note | max. 1 offene pro Einsatz (partial unique index auf `ended_at IS NULL`) |
| `bearings` | id (Client-UUID), mission_id, participant_id, transmission_id null, station geom, station_accuracy_m, azimuth_true_deg numeric(5,2) [0,360), azimuth_input_ref enum(`true`,`magnetic`,`compass`), declination_deg_applied, sigma_deg numeric(5,2) NOT NULL >0, rssi_dbm, s_meter, attenuation_db default 0, polarization enum(`h`,`v`,`unknown`), measured_at (Client), received_at, note, is_outlier bool, is_active bool, source enum(`manual`,`sensor`), sensor_id null | Check-Constraints; nie gelöscht |
| `bearing_revisions` | id bigserial, bearing_id, changed_by, changed_at, changes jsonb | append-only |
| `estimates` | id, mission_id, computed_at, scope enum(`current_transmission`,`all`), transmission_id null, input_hash, n_bearings, params jsonb, mle geom, cov_xx, cov_yy, cov_xy, ellipse_1s jsonb, ellipse_2s jsonb, contours jsonb (GeoJSON 50/80/95), raster_png_path null | `input_hash` verhindert doppelte Rechnung; Verlauf bleibt für Protokoll |

### Koordination

| Tabelle | Spalten | Hinweise |
|---|---|---|
| `messages` | id (Client-UUID), mission_id, author_id, team_id null, body, sent_at (Client), received_at | `team_id` = Team-Kanal, sonst Einsatz-Kanal |
| `tasks` | id (Client-UUID), mission_id, title, description, status enum(`open`,`in_progress`,`done`,`cancelled`), assignee_participant_id null, assignee_team_id null, created_by, created_at, updated_at, location geom null | CHECK: höchstens ein Assignee-Typ |
| `task_events` | id, task_id, actor_id, at, change jsonb | Verlauf |
| `push_tokens` | id, participant_id, platform enum(`fcm`,`apns`,`webpush`), token, created_at | |
| `audit_log` | id, mission_id, actor_id, action, entity, entity_id, at, detail jsonb | Join, Einsatz-Ende, Rollenwechsel etc. |

### Spätere Phasen

| Tabelle | Phase | Zweck |
|---|---|---|
| `rssi_samples` (id UUID, mission_id, participant_id, transmission_id, geom, rssi_dbm, attenuation_db, measured_at, received_at) | 3 | RSSI-Spur der Nahpeilung |
| `sensors` (id, mission_id, name, kind, fixed_geom, api_key_hash, last_seen_at) | 4 | MQTT-Peilstationen |
| `suggestions` (id, mission_id, computed_at, candidates jsonb) | 4 | Positionsvorschläge |

Migrationen: Alembic, Phase 1 enthält `missions, invites, teams, participants, position_samples, transmissions, bearings, bearing_revisions, estimates, audit_log`; `messages/tasks/push_tokens` kommen in Phase 2.

## 3. API-Liste

Basis `/api/v1`, Auth `Authorization: Bearer <JWT>`; JWT-Claims: `sub` (participant_id), `mission_id`, `role`.

### Auth / Beitritt
| Methode | Pfad | Zweck |
|---|---|---|
| POST | `/missions` | Einsatz anlegen (liefert ersten Lead-Invite + JWT) |
| POST | `/join` | Body: invite_token, callsign, role → Teilnehmer + JWT (Re-Join mit gleichem Rufzeichen → gleicher Teilnehmer) |
| POST | `/missions/{id}/invites` | Invite erzeugen (lead) |
| DELETE | `/missions/{id}/invites/{inv}` | Invite widerrufen (lead) – Widerruf, keine Datenlöschung |

### Einsätze / Teilnehmer / Teams
| Methode | Pfad |
|---|---|
| GET/PATCH | `/missions/{id}` (Name, Frequenz, Gebiet, Status, `engine_params`) |
| POST | `/missions/{id}/end` |
| GET | `/missions/{id}/participants` · PATCH `/participants/{pid}` (Rolle/Team, lead) |
| GET/POST | `/missions/{id}/teams` · PATCH `/teams/{tid}` |
| POST | `/missions/{id}/positions` (Batch, gedrosselt; zusätzlich via WS) |
| GET | `/missions/{id}/positions?participant=&since=` (Spuren) |

### Aussendungen
| Methode | Pfad |
|---|---|
| POST | `/missions/{id}/transmissions/start` · `/stop` |
| GET | `/missions/{id}/transmissions` |

### Peilungen
| Methode | Pfad | Hinweis |
|---|---|---|
| POST | `/missions/{id}/bearings` | Client-UUID, idempotent; Zuordnung zur offenen Aussendung (oder explizit `transmission_id`) |
| GET | `/missions/{id}/bearings?transmission=&since=&include_inactive=` | |
| GET | `/missions/{id}/bearings/{bid}` · `/revisions` | |
| PATCH | `/missions/{id}/bearings/{bid}` | nur `is_outlier`, `is_active`, `note`; schreibt Revision |
| – | *kein DELETE* | |

### Schätzung
| Methode | Pfad |
|---|---|
| GET | `/missions/{id}/estimate?scope=current\|all&half_life_min=&cell_m=` |
| GET | `/missions/{id}/estimate/history` |
| GET | `/missions/{id}/estimate/raster.png` (optional) |

### Koordination (Phase 2)
`GET/POST /missions/{id}/messages`, `GET/POST/PATCH /missions/{id}/tasks`, `POST /push-tokens`.

### Export (Phase 2)
`GET /missions/{id}/export.gpx|kml|json|pdf`.

### WebSocket `/ws/missions/{id}?token=<JWT>`
- **Server→Client**: `participant_position`, `bearing_created`, `bearing_updated`, `transmission_started`, `transmission_ended`, `estimate_updated`, `message`, `task_updated`. Jedes Event: `{type, mission_id, seq, ts, data}`; `seq` pro Einsatz monoton, Client kann mit `?since_seq=` nachladen (Reconnect ohne Lücke).
- **Client→Server**: `position` (Server drosselt auf ≥5 s pro Teilnehmer), `ping`.
- Fan-out: Redis-Channel `mission:{id}`.

### Sonstiges
`GET /healthz`, `GET /declination?lat=&lon=&t=` (WMM-Wert für Clients ohne lokale Tabelle).

## 4. Phase-1-Umfang und Reihenfolge (Vorschlag)

1. Repo-Gerüst, Compose (api, postgis, redis), `.env.example`, CI-Skelett.
2. `foxgrid_engine` + Tests (isoliert, zuerst, da höchstes Risiko).
3. Alembic + Modelle, Auth/Join, Missions, Positionen.
4. Bearings, Transmissions, Recompute-Worker, WebSocket + Redis.
5. Flutter: Join, Karte (Teilnehmer, Strahlen, MLE, Ellipse), Peilungs-Sheet (manuell), Aussendung Start/Stop. In Phase 1 **ohne** Drift-Queue (die kommt Phase 2); Idempotenz-UUID ist aber schon drin.
6. `tools/simulator` + Abnahmetest.

## 5. Offene Fragen

**Fachlich (Peiltechnik / Funk)**
1. **Peilantenne**: Gehen wir von Richtantennen mit Maximum-Peilung aus (Yagi/Quad/Doppler)? Dann ist „hinter der Station nur ε“ richtig. Bei Minimum-Peilung (Loop, Null) oder Doppler mit 180°-Mehrdeutigkeit bräuchte es ein Flag und ein anderes Likelihood-Modell. Soll ich das vorsehen?
2. **Sigma → κ**: Ich würde κ ≈ 1/σ² (σ in rad) setzen (Normalapproximation). Passt das, oder soll σ als Halbbreite (3 dB) der Antenne verstanden werden?
3. **Mehrere Peilungen vom selben Standort**: unabhängig behandeln oder pro Teilnehmer/Standort korrelationsbewusst abschwächen (sonst dominiert, wer oft peilt)?
4. **Dämpfungsglied/Abschwächung**: Nur Korrektur des RSSI (wie spezifiziert), oder soll es auch als Hinweis dienen, wie „stark“ ein Signal war?
5. **RSSI/S-Meter**: Eingabe als S-Stufen und dBm mit Umrechnung (S9 = −93 dBm bei 144 MHz; für 70 cm üblicherweise −93 dBm nach IARU-Konvention oder −73 dBm bei HF?). Welche Konvention willst du?
6. **Zeitstempel-Drift**: Handy-Uhren sind teils Sekunden daneben. Soll die Altersgewichtung `measured_at` (Client) oder `received_at` nutzen? Vorschlag: `measured_at`, aber Warnung, wenn |Δ| zu `received_at` > 60 s (Offline-Fall ausgenommen).

**Technisch / Betrieb**
7. **Kachel-Offline-Cache**: Die OSM-Tile-Usage-Policy verbietet Massendownload und Nutzung durch Apps ohne eigenen Tileserver. Optionen: (a) eigener Tileserver/PMTiles-Extrakt (z. B. Region per `protomaps`), (b) kommerzieller Anbieter mit Offline-Lizenz, (c) nur Cache beim normalen Betrachten, kleine Zahl Kacheln. Wie willst du das lösen? OpenTopoMap hat ähnliche Einschränkungen.
8. **Push**: FCM (Android + Web) und APNs (iOS) benötigen Firebase-/Apple-Konten und Zertifikate. Haben/willst du die? Web-Push auf iOS geht nur als installierte PWA, und `Vibration` gibt es in Safari nicht. Akzeptabel?
9. **Missweisung**: Berechnung serverseitig (`pygeomag`/`geomag`, endpoint) und/oder im Client (WMM-Koeffizienten als Dart-Tabelle)? Vorschlag: Client rechnet offline mit gebündelter 5°-Gitter-Tabelle für das Suchgebiet, Server prüft nachträglich.
10. **Grid-Größe**: 50 m bei großen Ausdehnungen (z. B. 80 km Peilabstand) ergibt >10⁶ Zellen und sprengt 200 ms. Vorschlag: Zellzahl deckeln (z. B. 250×250) und Auflösung adaptiv vergröbern, optional zweistufig (grob → fein um das Maximum). Einverstanden?
11. **Datenschutz/DSGVO**: Rufzeichen und Standortspuren sind personenbezogen. Reicht Hinweistext + Löschfrist, oder brauchst du eine Einwilligung beim Beitritt und einen Datenauskunfts-/Löschweg? Wer hostet (Einzelinstanz im Verein, öffentlich, Multi-Tenant)?
12. **Invite-Tokens**: Einmal- oder Mehrfachnutzung? Ablauf? Darf jeder mit Token das Rufzeichen frei wählen (keine Verifikation; Rufzeichen-Spoofing möglich)? Reicht das für den Verein?
13. **Rollen**: Was darf `lead` exklusiv (Einsatz beenden, Ausreißer markieren, Invites)? Dürfen alle Teilnehmer Peilungen anderer als Ausreißer markieren?
14. **Aussendungs-Zuordnung**: Peilung ohne laufende Aussendung (z. B. offline erfasst, später synchronisiert) → anhand `measured_at` einer vergangenen Aussendung zuordnen, oder `transmission_id = null`? Vorschlag: per Zeitfenster zuordnen.
15. **Flutter Web + Drift**: Drift im Web läuft über WASM/IndexedDB, mit Einschränkungen. Phase 1 braucht es noch nicht – ok, das erst in Phase 2 zu klären?
16. **Mobile-Targets**: Android-Emulator ist für die Abnahme genannt; iOS-Build brauchen wir ab Phase 1 oder erst später?
17. **Lizenzen**: OSM-Kacheln erfordern Attribution; WMM ist gemeinfrei (NOAA). Ok?
18. **PDF-Protokoll (Phase 2)**: serverseitig (z. B. WeasyPrint/ReportLab mit Karten-Rendering) bevorzugt?

## 6. Annahmen, falls du nichts anderes sagst
- Maximum-Peilung mit Richtantenne (Frage 1), κ ≈ 1/σ² (2), `measured_at` zählt (6), Zellen-Deckel 250×250 (10), Peilungen per Zeitfenster zuordnen (14), Server-JWT-Laufzeit = Einsatzdauer + 24 h.
- Phase 1 ohne Push, Drift-Queue und Kartenkacheln-Offline.
