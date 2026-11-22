# PROJECT_STATUS

Last updated: 2026-11-23

## Phase
Phase 1 — Platform foundation. **M1–M6 and the frontend shell are done.** M7 (shared services) and Gate G1 are next. See `docs/MASTER_PLAN.md` for goals/backlog/rules and `CLAUDE.md` for how to work.

## Completed milestones
- **M0** Discovery, reconciliation, architecture/roadmap (`docs/`).
- **M1** Scaffold & quality harness (venv, Alembic, embedded Postgres on D:, ruff/mypy/import-linter gates, isolation harness).
- **M2 (backend)** Tenant registration, identity, MFA, rotating sessions, invitations, org tree (same-company integrity enforced by composite FKs), hash-chained audit.
- **M3 Registries** Capability domains, business models, industries (hierarchy), applications → modules → submodules → features. Code-first YAML manifests (`ueos/platform/manifest.yaml`, `ueos/apps/*/manifest.yaml`) with linter (duplicate keys, dangling dependencies, cycles, bad slugs) and idempotent sync that never overwrites admin-created rows and deprecates removed features. Admin CRUD via the platform-staff API; tenant-facing published catalogue.
- **M4 Authorization** Platform-staff realm (separate login/JWT audience/audit stream; roles super_admin, registry_admin, support_admin; TOTP; lockout). Tenant RBAC with wildcard permissions, system roles (Owner/Admin/Member), custom roles, assignments with record scope (company/branch/department → SQL predicate), expiry (temporary delegation), ABAC constraints (working hours, amount limit, no-self-approval, own-records, field hiding), field masking, **anti-escalation guard** (nobody grants more than they hold; last Owner protected), entitlement gate (kernel always on; other apps need an entitlement), tenant-suspension lockout, `Requires(feature, action)` on every tenant route.

- **Frontend shell** (`frontend/web`, Next.js 15 + React 19 + Tailwind 4, same-origin proxy to the API): register / sign in (with MFA step) / accept invitation; permission-driven sidebar; dashboard; organization (companies, branches, departments); members + invitations (+disable); roles & access (permission builder with limits, assignments with company scope and expiry); audit log with integrity check; application catalogue; MFA enrolment. Separate **platform staff console** (`/platform/*`): tenants (suspend/activate, entitlements) and registry (applications, modules, features, industries, manifest sync). Responsive (collapsible menu on phones), light/dark via system preference, keyboard-focus styles, form labels.
  - Verified in a real browser against the live backend: registration → dashboard, company creation, roles/audit/catalogue pages, staff login → tenant list → entitlement grant, phone-width layout. Bug found and fixed during this: staff accounts could be created with emails the login form rejects (`.local`); creation now validates, with a regression test.

- **M5 Subscriptions & billing**: plans (base/add-on, monthly/annual, base + per-user price, trial days, default plan, feature patterns + limits; published plans immutable), subscriptions lifecycle (pending → trialing/active → past_due with grace → expired/canceled; cancel at period end/resume; upgrade prorated immediately, downgrade scheduled for period end and blocked when usage exceeds the new limits), invoices (sequential per tenant, exact Decimal, one per subscription period), payments through a provider abstraction (sandbox `test` provider dev/test only; `manual` for staff-recorded payments; **no real gateway implemented**), idempotency keys, entitlements materialized from subscriptions with automatic expiry, limits (users/companies/branches) enforced with "restricted mode" after lapse, usage records, billing run (renewals/trial end/grace/expiry; simulation clock only in dev/test), staff `subscription_admin` role, tenant Billing page, staff Plans & billing page.
  - Verified live in the browser: subscribe to a paid plan → pending invoice 33.99 (29.00 + 4.99/user) → sandbox pay → active, usage vs limits shown.
- **Project memory docs**: `CLAUDE.md` (rules for every session), `docs/MASTER_PLAN.md` (goals, backlog, parked ideas, open questions, Odoo policy), `docs/spec/SPEC_DIGEST.md` (requirements digest), ADR-017/018.

- **M6 Configuration & assembly engine** (PRD Phase 5 / Software Builder):
  - Industry templates: versioned, draft → published (immutable) → deprecated, new versions; **inheritance** (child extends a published parent) with resolution that merges the chain and records **provenance** (which template set each value) and **overrides** (what a child replaced).
  - Template content: business models, applications, modules, custom fields, terminology, role templates, dashboards, recommended plans, compliance tags, workflow names (stored only — executed in M7).
  - **Apply to tenant** copies resolved configuration into tenant-owned rows and **never overwrites** anything the tenant already has (re-applying or applying a newer version keeps tenant edits); applied roles cannot exceed the applier's own permissions; everything is audited.
  - Module activation per tenant with **automatic dependency resolution**, protected deactivation (blocked while another active module needs it) and **conflict prevention** (`conflicts_with` in feature manifests, checked against already-active modules).
  - **Software editions (products)**: versioned compositions of registry modules + template + branding + recommended plans (no duplication of applications); validate/test (warns when recommended plans do not cover a module's features), publish (immutable), new versions; tenants install an edition (activates modules, applies template, stores branding).
  - **Dynamic navigation** from published apps + activated modules + entitlements + the user's own permissions (only the actions they hold); module launcher page that states honestly when a module's screens are not built yet.
  - **Custom fields** (text/number/date/boolean/select, required) enforced server-side on companies; tenant **terminology**; template-driven **dashboard** widgets that never show counts the user may not view.
  - Staff page "Templates & editions" (JSON template editor, product builder); tenant "Configuration" page (modules, templates with preview, editions, fields, terminology).
  - Verified live in the browser: applying a Hotel template (inherits a base) renamed "Members" → "Staff", added an Applications section with Finance modules, relabelled Organization to "Properties/Hotels", added the inherited + child custom fields to the company form and created Front-desk dashboard widgets.

## In-progress
- None.

## Pending (Phase 1 remainder)
- M7 master data, notifications, documents, workflow engine v1, outbox/inbox · Gate G1.
- M6 gaps: no template un-apply/rollback; custom fields exist only for companies (other entities follow with their apps); no visual form/menu designer yet (config is JSON/fields); workflow templates are stored but not executed until M7; dashboards support only count widgets; product `test` checks plan coverage but there is no automated edition test environment; internal catalogue is per-tenant activation (the third-party developer marketplace is later).
- Billing gaps: no real payment gateway (decision needed), no tax on invoices, no credit notes/refunds, no dunning emails, no invoice PDF, no metered billing (storage/API usage only recorded), billing run must be scheduled (no scheduler yet — staff button/API only).
- Frontend gaps: no Playwright suite (type-check + build + manual browser runs only), no password reset/profile page, no staff MFA screen, tokens in localStorage (move to httpOnly cookies before production).
- Break-glass support access not implemented. Full backlog: `docs/MASTER_PLAN.md` §4.

## Verification (run 2026-11-22)
ruff clean · mypy clean (23 files) · import-linter 1 contract kept · **86 backend tests passed** (15 new for M6) · frontend `tsc --noEmit` clean and `next build` succeeds (20 routes). Mutation checks: template overwriting tenant terminology (1 test fails), dependency resolution disabled (3 fail), conflict detection disabled (1 fails) are all caught.
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
1. M7 shared services (master data, notifications, documents, outbox/inbox, workflow v1); Gate G1 (stop for user review).
3. First business-app slice (Finance or Inventory) after its DRD/ERD; Playwright e2e suite.

## Blocked / needs input
Part 3 (CRM) document · first jurisdiction/vertical · capacity targets · data residency · what the 3-day deliverable must demonstrate.

