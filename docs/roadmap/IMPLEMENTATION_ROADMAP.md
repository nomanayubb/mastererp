# UEOS — Implementation Roadmap (Proposed)

Principle: **build the selling and governing infrastructure before the software it sells** (your priority table). Every milestone is independently testable, ends with a demo against stated acceptance criteria, and updates `PROJECT_STATUS.md`. Sizes are relative (S ≈ days, M ≈ 1–2 weeks, L ≈ 3–6 weeks, XL ≈ 6+ weeks of focused work), not commitments — real estimates need your team/timeline answers.

## Phase 1 — Platform foundation (Wave P)

### M1 — Scaffold & quality harness (M) — ✅ DONE
- **Features:** monorepo, Docker Compose (postgres/redis/minio), FastAPI skeleton, Alembic, CI, import-linter, mypy, pytest with real Postgres, OpenTelemetry/logging, `Requires()` route-coverage test.
- **DB:** `platform` schema, migration framework, RLS helper functions.
- **Tests / acceptance:** CI green; a sample tenant-owned table passes the isolation suite; migration up/down verified.
- **Risks:** RLS + async pool context leakage → covered by dedicated test (connection reuse across tenants).

### M2 — Identity, tenancy, organization, audit (L) — ✅ DONE
- **Features:** tenant registration, user/membership, Argon2id, MFA (TOTP), sessions/refresh rotation, invitations, company/branch/department tree, audit hash chain, platform-staff realm.
- **APIs:** `/auth`, `/users`, `/tenants`, `/organizations`.
- **Frontend:** sign-up/login, tenant workspace shell, org management.
- **Depends:** M1. **Acceptance:** a customer registers, creates an organization, invites a user; cross-tenant access fails on every path; audit chain verifies.
- **Risks:** security-critical — independent review before M3.

### M3 — Registries & manifests (M) — ✅ DONE
- **Features:** capability/application/module/submodule/feature registries, industry & business-model registries, manifest loader + linter (duplicate slugs, dependency cycles), admin CRUD for config-defined items.
- **Acceptance:** administrator creates an app, module, submodule, feature, industry; manifest sync idempotent.

### M4 — Authorization engine (L) — ✅ DONE
- **Features:** roles/permissions generated from registry, RBAC, ABAC policies (scope, thresholds, hours, SoD, delegation, time-limited), record-scope compiler, field masking, "effective permissions" view, break-glass support access.
- **Acceptance:** cashier example from master PRD §10.5 passes; permission-matrix tests generated from manifests; every route covered by `Requires()`.

### M5 — Subscription & entitlement engine (L) — ✅ DONE 2026-11-23 (see PROJECT_STATUS.md)
- **Features:** plans/items (app, module, feature, limits, metered), subscriptions lifecycle (trial, renew, upgrade/downgrade, grace), entitlement materialization + cache, usage metering, invoices/billing events, payment-provider adapter (**test mode only**), enforcement dependency.
- **Acceptance:** expired subscription blocks protected operations; limit breaches enforced; upgrade changes entitlements without redeploy.
- **Risks:** payment provider and tax treatment are external decisions that depend on your target market (GAP_ANALYSIS Decision 2).

### M6 — Configuration & assembly engine; internal catalogue (L) — ✅ DONE 2026-11-23 (see PROJECT_STATUS.md)
- **Features:** industry templates with inheritance + provenance, apply-to-tenant, dependency resolution/incompatibility checks, product (edition) builder with versions, dynamic navigation, configurable forms/fields/dashboards, internal application catalogue + activate/deactivate.
- **Acceptance:** new industry edition created without touching unrelated app code; two tenants on different templates see different nav; template update leaves tenant data intact.

### M7 — Shared services v1 (L)
- **Features:** master data (`party`, `product`, `location`, UoM, currency), tax-engine interface, notifications, document storage/versioning, outbox/inbox, workflow engine v1 + approvals, reporting v1, admin portal MVP.
- **Acceptance:** event duplicate/retry tests; approval workflow with SoD; document upload scanning hook.

### Gate G1 — Foundation validation (your STEP 4)
Demonstrate: independent tenant registration · tenant isolation · user invitation · role creation · permission assignment · application/module/feature registration · industry creation · application assembly · subscription creation · entitlement enforcement. **Stop for your review and approval before any business app.**

## Phase 2 — Core applications (Wave A) — each needs its own feature-level DRD, ERD and API contract first

Order is dependency-driven; each app ships as vertical slices (workflow end-to-end, then breadth):

| Order | App | First slice | Notes |
|---|---|---|---|
| 1 | Finance (1) + tax engine (32) | CoA → journals → period close → AR invoice/payment → trial balance | Acceptance tests 1–20 from Part 1. Ledger invariants first. |
| 2 | Inventory (5) + PIM/product registry | Ledger, receipt/issue/transfer, reservations (concurrency), batches/serials | Needs Part 5 + PIM spec. |
| 3 | CRM (3) | Leads → opportunity → customer | **Part 3 missing.** |
| 4 | Sales (2) | Quote → order → reservation → invoice → payment | Tests 1–24 from Part 2. |
| 5 | Procurement (4) + supplier master | Requisition → PO → receipt → 3-way match | Budget reservations via Finance. |
| 6 | WMS (6), HRM + payroll (7), Projects (11), Assets (12) | per-app first slice | HR payroll tax requires jurisdiction pack. |

## Phase 3 — Advanced (Wave B)
Manufacturing (+MES), Quality, Logistics/TMS, Contracts/CLM, BI semantic layer, Treasury, GRC, PLM, SCM, Advanced reporting.

## Phase 4 — Remaining waves
AI/automation (assistants, workflow builder maturity), integrations (payments, couriers, banks, devices), commerce (E-com, POS, loyalty, marketing, support), third-party developer marketplace (after extension sandbox), mobile/PWA hardening, dedicated-tenant/on-prem packaging, DR drills, performance tuning, and demand-driven verticals (Wave D). Regulated verticals (healthcare, government tenders, payroll tax) start only after jurisdiction and expert-review decisions (G21).

## Per-milestone quality gate (STEP 6)
Run tests → fix → security review → migration review → performance check → docs → `PROJECT_STATUS.md`. A feature is "complete" only per the Definition of Done (backend, API validation, authz, entitlement, UI, audit, tests, docs, acceptance).

## Backlog seed (epics)
| ID | Epic | Milestone |
|---|---|---|
| E-001 | Repo scaffold, CI, isolation harness | M1 |
| E-002 | Identity & sessions | M2 |
| E-003 | Tenancy & org tree | M2 |
| E-004 | Audit chain | M2 |
| E-005 | Registries & manifests | M3 |
| E-006 | RBAC/ABAC engine | M4 |
| E-007 | Plans, subscriptions, entitlements | M5 |
| E-008 | Industry templates & assembly | M6 |
| E-009 | Dynamic navigation & configurable UI | M6 |
| E-010 | Master data services | M7 |
| E-011 | Outbox/inbox & workflow v1 | M7 |
| E-012 | Notifications & documents | M7 |
| E-013 | Admin portal MVP | M7 |
| E-014 | Tax engine + jurisdiction pack framework | Phase 2 |
| E-015+ | Per-app epics, created when each app's DRD is approved | Phase 2+ |

## Open risks
Spec depth uneven (Parts 9–52) · Part 3 missing · no team/timeline/capacity input · regulated domains need external expertise · single-person build of ~20k features is infeasible without strong reuse (manifests + metadata UI) — and even then breadth will trail depth.
