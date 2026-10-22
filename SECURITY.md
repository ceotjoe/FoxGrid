# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting instead:
[Report a vulnerability](https://github.com/ceotjoe/FoxGrid/security/advisories/new)
(tab *Security* → *Report a vulnerability*).

Helpful details: affected component (backend, app, engine, MQTT), version or commit, steps to reproduce and the
possible impact. I usually acknowledge receipt within a few days; FoxGrid is a volunteer project, so deadlines are
guidelines.

## Supported versions

Only the current state of `main` and the latest release are supported.

## Operating a server

Guidance for secure operation (invite links, approval, rate limits, reverse proxy) is in
[docs/user-guide/mission-lead-security.md](docs/user-guide/mission-lead-security.md) and
[docs/operations/deployment.md](docs/operations/deployment.md). Secrets never belong in the repository; `.env` is ignored,
`.env.example` contains placeholders only.
