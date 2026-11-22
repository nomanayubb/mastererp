# PROJECT_STATUS

Last updated: 2026-11-22

## Phase
Phase 1 — Platform foundation. **M1, M2, M3, M4 and the frontend shell are done.** M5 subscriptions, M6 assembly, M7 shared services, Gate G1 pending.

## Completed milestones
- **M0** Discovery, reconciliation, architecture/roadmap (`docs/`).
- **M1** Scaffold & quality harness (venv, Alembic, embedded Postgres on D:, ruff/mypy/import-linter gates, isolation harness).
- **M2 (backend)** Tenant registration, identity, MFA, rotating sessions, invitations, org tree (same-company integrity enforced by composite FKs), hash-chained audit.
- **M3 Registries** Capability domains, business models, industries (hierarchy), applications → modules → submodules → features. Code-first YAML manifests (`ueos/platform/manifest.yaml`, `ueos/apps/*/manifest.yaml`) with linter (duplicate keys, dangling dependencies, cycles, bad slugs) and idempotent sync that never overwrites admin-created rows and deprecates removed features. Admin CRUD via the platform-staff API; tenant-facing published catalogue.
- **M4 Authorization** Platform-staff realm (separate login/JWT audience/audit stream; roles super_admin, registry_admin, support_admin; TOTP; lockout). Tenant RBAC with wildcard permissions, system roles (Owner/Admin/Member), custom roles, assignments with record scope (company/branch/department → SQL predicate), expiry (temporary delegation), ABAC constraints (working hours, amount limit, no-self-approval, own-records, field hiding), field masking, **anti-escalation guard** (nobody grants more than they hold; last Owner protected), entitlement gate (kernel always on; other apps need an entitlement), tenant-suspension lockout, `Requires(feature, action)` on every tenant route.

- **Frontend shell** (`frontend/web`, Next.js 15 + React 19 + Tailwind 4, same-origin proxy to the API): register / sign in (with MFA step) / accept invitation; permission-driven sidebar; dashboard; organization (companies, branches, departments); members + invitations (+disable); roles & access (permission builder with limits, assignments with company scope and expiry); audit log with integrity check; application catalogue; MFA enrolment. Separate **platform staff console** (`/platform/*`): tenants (suspend/activate, entitlements) and registry (applications, modules, features, industries, manifest sync). Responsive (collapsible menu on phones), light/dark via system preference, keyboard-focus styles, form labels.
  - Verified in a real browser against the live backend: registration → dashboard, company creation, roles/audit/catalogue pages, staff login → tenant list → entitlement grant, phone-width layout. Bug found and fixed during this: staff accounts could be created with emails the login form rejects (`.local`); creation now validates, with a regression test.

## In-progress
- None.

## Pending (Phase 1 remainder)
- M5 plans/subscriptions/billing on top of the entitlement table · M6 industry templates + assembly + dynamic nav · M7 master data, notifications, documents, workflow engine v1, outbox/inbox · Gate G1.
- Frontend gaps: no automated frontend tests yet (no Playwright suite; only type-check + build + manual browser run), no password reset/profile page, no staff MFA enrolment screen, staff console cannot edit module/submodule/feature status in the UI beyond publishing apps, tokens are kept in localStorage (consider httpOnly cookies before production).
- Break-glass support access to tenant data (not implemented; staff can currently see tenant metadata and manage entitlements/status only).

## Verification (run 2026-11-22)
ruff clean · mypy clean (19 files) · import-linter 1 contract kept · **50 backend tests passed** · frontend `tsc --noEmit` clean and `next build` succeeds (15 routes) · mutation checks: disabling the escalation guard or the entitlement check makes tests fail.
Tests cover: tenant isolation (structural + behavioural), auth/MFA/sessions/invitations, org tree, audit tamper/append-only/concurrency, manifest linter & sync, registry admin API, staff realm separation and role limits, platform audit chain, RBAC denials, custom roles, escalation, scope, masking, expiry, hours window, amount/SoD, entitlements per tenant, suspension, route-policy coverage (every route has a policy; every `Requires()` key/action exists in the registry), migration up/down.

## Implemented applications / modules / features
Platform kernel only (registered in `platform/manifest.yaml`, 10 features, status `tested`). Finance has a **partial manifest** (6 features, status `specified`, no implementation) to exercise the registry and entitlements. No business application is implemented.

## Known limitations / bugs
- Invitation token is returned in the API response (no email service until M7) — dev-only.
- Authorization is evaluated from the DB on every request (no cache) — fine now, add an entitlement/grant cache before load testing.
- Hours constraint uses UTC (no per-tenant time zone yet).
- Invited users always receive the base Member role (unscoped org view); scoped users require removing it explicitly. Consider "no base role" invitations in M5/M6.
- `platform.users` (global) and registry tables share the app DB role with tenant tables; writes to the registry are guarded only at the API layer. A separate DB role for staff operations is a future hardening step.
- No rate limiting beyond lockout; no password reset; no SSO.
- Staff accounts are created via CLI only: `python -m ueos.cli create-staff EMAIL ROLE`.

## Technical debt
- Tests in `backend/tests`; no CI pipeline file yet (gates run via `infrastructure/scripts/test.ps1`); no Docker image/compose (Docker Desktop not running; would sit on C:).

## Security issues
None known. Independent review recommended for: RLS context handling, session/refresh logic, audit chains, authz engine.

## Storage policy
All project files, venv, caches, temp and the dev/test databases live in `D:\OTHER PROJECTS\master erp` (`.venv`, `.cache`, `.tmp`, `.data`).

## Next development tasks
1. M5 subscriptions & entitlement engine (plans/items/limits/usage on top of `platform.entitlements`).
2. M6 assembly engine + industry templates + dynamic navigation.
3. Playwright e2e suite for the frontend; M7 shared services; Gate G1.

## Blocked / needs input
Part 3 (CRM) document · first jurisdiction/vertical · capacity targets · data residency · what the 3-day deliverable must demonstrate.

