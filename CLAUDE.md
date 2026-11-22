# CLAUDE.md — how to work on UEOS

UEOS = Universal Enterprise Operating System: ONE multi-tenant platform on which many business applications
(Finance, Sales, Inventory, HR, …) are built, configured, licensed and sold. **Build the selling/governing
infrastructure first, then the applications.** Read this file fully at the start of every session.

## 1. Start-of-session checklist (do this, in order)
1. Read `PROJECT_STATUS.md` (what is real today) and `docs/MASTER_PLAN.md` (goals, backlog, parked ideas, open questions).
2. Skim `docs/spec/SPEC_DIGEST.md` for the requirement you are about to build; the full source specs are in `docs/spec/source/` if present, otherwise ask the user.
3. `git status` / `git log -5`, then run the gate: `.\infrastructure\scripts\test.ps1` (ruff, mypy, import-linter, pytest). **Never start new work on a red gate.**
4. State the plan for the turn (task list), then work. After each milestone: tests → fix → security review → migration review → update `PROJECT_STATUS.md` and `docs/MASTER_PLAN.md` → commit.

## 2. Storage rule (hard)
The user's C: drive is almost full. **Everything lives in `D:\OTHER PROJECTS\master erp`**: `.venv`, `.cache\pip`, `.cache\npm`, `.tmp`, `.data` (embedded Postgres), `frontend\web\node_modules`.
Before running installers/builds set `PIP_CACHE_DIR`, `npm_config_cache`, `TEMP`, `TMP` to the project folders (the scripts in `infrastructure/scripts` already do). Never install to C:. Docker Desktop is not used (its image would sit on C:).
Stop embedded Postgres with `pg_ctl stop -m fast` (never just kill it — the next start needs slow crash recovery). Do not use `npx` for tools that should be local (it once fetched an unrelated package); call `node_modules\.bin\*`.

## 3. Commands
```
.\infrastructure\scripts\dev.ps1     # Postgres (.data) + migrations + registry sync + API :8000 (prints a dev-only staff password on first start)
.\infrastructure\scripts\web.ps1     # frontend :3000 (proxies /api to :8000)
.\infrastructure\scripts\test.ps1    # full backend gate
cd frontend\web; node_modules\.bin\tsc --noEmit; node_modules\.bin\next build   # frontend gate
.\.venv\Scripts\python.exe -m ueos.cli create-staff EMAIL ROLE | sync-registry
```
Shell notes: Bash tool = Git Bash (use `/` paths); heredocs containing many quotes break — use the Write tool for big files.

## 4. Architecture rules (non-negotiable)
- Modular monolith. `ueos.apps.X` may import only `ueos.platform.*` and another app's `contracts`; `ueos.platform` never imports `ueos.apps` (import-linter enforces).
- **Tenant isolation in the database**: every tenant-owned table has `tenant_id`, RLS policy, composite FKs including `tenant_id`; API connects as non-owner `ueos_app` (no BYPASSRLS); every transaction goes through `db.tx(tenant_id)`. New tables must be added to the isolation test whitelist only if genuinely global.
- **Every tenant route declares access**: `Depends(public)`, `authenticated`, or `Requires("app.module.feature", "action")`; staff routes use `staff_roles(...)`. Every `Requires` key+action must exist in a feature manifest (tests enforce). Frontend hiding is never authorization.
- **Features come from manifests** (`ueos/platform/manifest.yaml`, `ueos/apps/<app>/manifest.yaml`): slug keys `app.module[.submodule].feature`, `legacy_ref` = spec feature number. Status honest: `specified → implemented → tested → released`.
- Authorization pipeline: tenant active → entitlement → RBAC → ABAC → record scope → field mask. Nobody can grant more than they hold.
- Money/quantities = `Decimal`/`NUMERIC`, never float. Posted financial/stock records are immutable (reversals only). Idempotency keys on payment/posting commands.
- Audit: every state change calls `audit.record(...)` in the same transaction (tenant chain) or `audit.record_platform` (staff chain). Audit tables are append-only.
- No secrets in code. Dev-only defaults are marked `dev-only`. The sandbox payment provider is disabled outside dev/test; no real gateway is implemented — never fake one in production.
- Alembic migrations are hand-written SQL, reversible (`downgrade`), tested up/down. Never edit an applied migration; add a new one.
- Another application's authoritative tables are never written directly (see ownership table in `docs/architecture/GAP_ANALYSIS.md` §3).

## 5. Definition of done (a feature is NOT done until all exist)
Requirements/manifest entry · migration · backend logic · API validation · authz + entitlement · audit · frontend screen · error handling · unit + integration tests **and** a negative/security test · docs · acceptance test. Do not mark features complete when only the UI/endpoint exists. No mock data standing in for logic.
Sanity-check new tests by **mutation**: temporarily break the guard under test and confirm tests fail, then restore.

## 6. Working style
- The user wants speed and has a short deadline (stated 3 days from 2026-11-22). Be efficient, but never skip the gate or fake results. If scope cannot fit, say so plainly and propose the cut.
- Report outcomes faithfully (failures included). Keep final messages short and plain-language; link files; list what is NOT done.
- Ask before: destructive operations, expensive infra, new third-party services, real payment/legal/compliance claims, scope changes. Commit/push only when asked (repo: https://github.com/nomanayubb/mastererp, branch `main`; the user authorised pushing there).
- **"Child"/seed software** (the user's 2026-11-22 idea): recorded in `docs/MASTER_PLAN.md` §7 as *not needed now* — do not build or re-propose it, **and do not delete that record**. Build ERP apps directly as vertical slices on the kernel. **Never remove or descope anything the user's PRD/DRD specifies**, including any child/sub-applications, application families, modules or submodules — those stay in scope. General rule: never delete the user's recorded ideas or requirements; mark their status instead.
- Compliance wording: the platform *supports* controls; never claim GDPR/SOC 2/PCI/HIPAA status.

## 7. Odoo and other references
Odoo may be used **only as a design reference** (domain concepts, workflows, field lists). No runtime dependency, no copied code/templates/data (Community is LGPL-3.0; Enterprise is proprietary — not usable). If the user supplies Odoo files, keep them in `reference/odoo/` (git-ignored), and record in `docs/adr/` which module informed which design decision. UEOS must stay fully independent of Odoo.

## 8. Where things are
`docs/architecture/` (gap analysis, master architecture, application registry) · `docs/adr/ADR-LOG.md` · `docs/roadmap/IMPLEMENTATION_ROADMAP.md` · `docs/MASTER_PLAN.md` · `docs/spec/SPEC_DIGEST.md` · `PROJECT_STATUS.md` · `backend/ueos/platform` (kernel) · `backend/ueos/apps` · `backend/migrations` · `backend/tests` · `frontend/web`.
