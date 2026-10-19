# Sicherheitsrichtlinie / Security policy

## Sicherheitslücke melden / Reporting a vulnerability

Bitte **kein öffentliches Issue** anlegen. Nutze stattdessen die private Meldung über GitHub:
[Report a vulnerability](https://github.com/ceotjoe/FoxGrid/security/advisories/new)
(Reiter *Security* → *Report a vulnerability*).

Please do not open a public issue. Use GitHub's private vulnerability reporting (link above).

Hilfreich sind: betroffene Komponente (Backend, App, Engine, MQTT), Version oder Commit, Schritte zum Nachstellen
und mögliche Auswirkungen. Ich bestätige den Eingang in der Regel innerhalb weniger Tage; FoxGrid ist ein
ehrenamtliches Projekt, Fristen sind Richtwerte.

## Unterstützte Versionen / Supported versions

Es wird jeweils nur der aktuelle Stand von `main` und das jüngste Release unterstützt.

## Betrieb / Operating a server

Hinweise zum sicheren Betrieb (Einladungslinks, Freigabe, Rate-Limits, Reverse-Proxy) stehen in
[docs/sicherheit.md](docs/sicherheit.md). Secrets gehören nie ins Repository; `.env` ist ignoriert,
`.env.example` enthält nur Platzhalter.
