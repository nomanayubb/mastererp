# UEOS — Universal Enterprise Operating System

Status: Phase 1 (platform foundation) — M1 + M2 backend implemented and tested. See `PROJECT_STATUS.md`.

## Run (everything stays inside this folder)
```powershell
.\infrastructure\scripts\dev.ps1     # embedded Postgres (.data/postgres) + migrations + API at http://127.0.0.1:8000/docs
.\infrastructure\scripts\test.ps1    # ruff, mypy, import-linter, pytest (real Postgres)
```
Open http://localhost:3000 (customers: register a workspace) or http://localhost:3000/platform/login (UEOS staff).
`dev.ps1` creates a **dev-only** staff account on first start and prints its generated password in the console
(`admin@ueos-dev.example.com`). Further staff: `python -m ueos.cli create-staff EMAIL ROLE` (needs `UEOS_DATABASE_URL`).
First-time setup (already done): `python -m venv .venv` then `.venv\Scripts\pip install -e "backend[dev]"`.

## Layout
`frontend/web` (Next.js UI) · `backend/ueos/platform` (shared kernel) · `backend/ueos/apps` (business apps, later) · `backend/migrations` (Alembic) · `backend/tests` · `docs/` · `infrastructure/scripts`.

## Documents
| Document | Purpose |
|---|---|
| `docs/architecture/GAP_ANALYSIS.md` | Reconciliation of the specs, gaps, decisions needed |
| `docs/architecture/MASTER_ARCHITECTURE.md` | Stack, tenancy, authz, events, audit, ERD |
| `docs/architecture/APPLICATION_REGISTRY.md` | 52 domains reconciled to ~43, waves, dependency graph |
| `docs/adr/ADR-LOG.md` | Architecture decisions |
| `docs/roadmap/IMPLEMENTATION_ROADMAP.md` | Milestones, gates, backlog |
| `PROJECT_STATUS.md` | Live status |
