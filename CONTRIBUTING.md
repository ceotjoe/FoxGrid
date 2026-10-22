# Contributing to FoxGrid

Thanks for wanting to help! Issues and pull requests in English or German are welcome. Code, comments, commit messages,
identifiers and documentation are **English**.

## Talk first

For larger changes please open an issue or discussion first. For questions about direction-finding technique or amateur
radio, ask rather than guess.

## Development environment

```bash
cp .env.example .env && docker compose up -d --build        # API + PostGIS + Redis
cd engine  && uv run ruff check . && uv run mypy --strict foxgrid_engine && uv run pytest
cd backend && uv run ruff check . && uv run mypy app && uv run pytest   # PostGIS/Redis via testcontainers
cd app     && flutter analyze && flutter test
```

Details (prerequisites, simulator, per-package notes) are in [docs/development/setup-and-testing.md](docs/development/setup-and-testing.md).
The documentation map is [docs/README.md](docs/README.md). The most important domain rules, in short
(full list: [docs/concepts/domain-rules.md](docs/concepts/domain-rules.md)):

- Azimuth is **always stored as true north**; `sigma_deg` is mandatory.
- Bearings are **never deleted**, only deactivated or flagged as outliers (revisions are append-only).
- Timestamps come from the client in UTC; the server adds `received_at`.
- Every query that feeds an estimate goes through `domain.trusted_only(...)`.
- `foxgrid_engine` has no web or DB dependencies.

## Quality requirements

- `ruff` (backend, engine), `mypy --strict` (engine), `flutter analyze` without warnings.
- Tests for new behaviour; engine coverage > 90 %, API tests against a real PostGIS.
- Do not edit generated files (app icons, store graphics, `database.g.dart`) by hand; regenerate them
  (see [docs/development/](docs/development/)).
- No secrets, keystores or personal data in a commit.
- Update the docs when behaviour or data flow changes. Privacy-relevant changes also need
  `docs/privacy/*.md`, `docs/operations/store-compliance.md` and `app/ios/Runner/PrivacyInfo.xcprivacy` to be kept in sync.

## Pull requests

1. Fork, branch from `main`.
2. Small, traceable commits with a meaningful message (for example `fix(backend): ...`, `feat(app): ...`).
3. Fill in the PR template; CI must be green.

By submitting you agree that your contribution is licensed under the [MIT licence](LICENSE).

Please do not report security vulnerabilities as issues; follow [SECURITY.md](SECURITY.md).
