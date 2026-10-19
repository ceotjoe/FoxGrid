# Mitarbeit an FoxGrid / Contributing

Danke, dass du helfen willst! Issues und Pull Requests auf Deutsch oder Englisch sind willkommen.
Code, Kommentare, Commit-Messages und Bezeichner sind **englisch**, README und Anwenderdoku **deutsch**.

## Vorher abstimmen

Für größere Änderungen bitte zuerst ein Issue oder eine Discussion eröffnen. Bei Fragen zur Peiltechnik oder zum
Amateurfunk lieber nachfragen als raten.

## Entwicklungsumgebung

```bash
cp .env.example .env && docker compose up -d --build        # API + PostGIS + Redis
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # PostGIS/Redis per testcontainers
cd app     && flutter analyze && flutter test
```

Weitere Konventionen (Stack, Repo-Layout, Fachregeln) stehen in [CLAUDE.md](CLAUDE.md). Die wichtigsten Fachregeln:

- Azimut wird **immer rechtweisend (true north)** gespeichert; `sigma_deg` ist Pflicht.
- Peilungen werden **nie gelöscht**, nur deaktiviert oder als Ausreißer markiert (Revisionen sind append-only).
- Zeitstempel kommen als UTC vom Client; der Server ergänzt `received_at`.
- Jede Abfrage, die in eine Schätzung einfließt, läuft über `domain.trusted_only(...)`.
- `foxgrid_engine` hat keine Web- oder DB-Abhängigkeiten.

## Qualitätsanforderungen

- `ruff` (Backend, Engine), `mypy --strict` (Engine), `flutter analyze` ohne Warnungen.
- Tests für neues Verhalten; Engine-Abdeckung > 90 %, API-Tests gegen echtes PostGIS.
- Generierte Dateien (App-Icons, Store-Grafiken, `database.g.dart`) nicht von Hand ändern, sondern neu erzeugen
  (siehe CLAUDE.md).
- Keine Secrets, Keystores oder personenbezogenen Daten im Commit.

## Pull Requests

1. Fork, Branch von `main`.
2. Kleine, nachvollziehbare Commits mit aussagekräftiger Message (z. B. `fix(backend): ...`, `feat(app): ...`).
3. PR-Vorlage ausfüllen, CI muss grün sein.

Mit dem Einreichen stimmst du zu, dass dein Beitrag unter der [MIT-Lizenz](LICENSE) steht.

Sicherheitslücken bitte nicht als Issue melden, sondern nach [SECURITY.md](SECURITY.md).
