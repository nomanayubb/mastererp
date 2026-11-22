# UEOS — Master Plan (goals, scope, backlog, rules)

This is the project's long-term memory. Update it whenever scope, status or decisions change.
Companion files: `CLAUDE.md` (working rules), `PROJECT_STATUS.md` (live status), `docs/spec/SPEC_DIGEST.md` (requirements digest),
`docs/architecture/*`, `docs/roadmap/IMPLEMENTATION_ROADMAP.md`, `docs/adr/ADR-LOG.md`.

## 1. Goal
One universal enterprise software platform that can run almost any organisation (retail, manufacturing, healthcare, agriculture,
education, logistics, government, …) through configuration, not per-industry code — and that can **create, license, sell and operate**
many software products from reusable applications → modules → submodules → features.
- Sold as SaaS (also private cloud / on-prem), with plans, add-ons, trials, usage limits, per-user pricing.
- Multi-tenant, multi-company, multi-branch, global (currencies, languages, tax packs), API-first, extensible (industry templates, extensions, marketplace).
- Business rule: build the platform (identity → registries → permissions → subscriptions → industries → assembly) **before** the business applications.

## 2. Principles (from the master PRD)
Build once, reuse across industries · configure before coding · shared capabilities vs industry specifics · independent modules and features ·
never hardcode industries/packages/visibility · subscription never replaces security authorization · backward compatibility · full auditability · documented APIs.

## 3. Milestone status (details in PROJECT_STATUS.md)
| # | Milestone | Status |
|---|---|---|
| M0 | Discovery, reconciliation, architecture, roadmap | ✅ done |
| M1 | Scaffold, quality gates, isolation harness | ✅ done |
| M2 | Identity, tenancy, org tree, audit chain (+ frontend) | ✅ done |
| M3 | Registries + manifest sync | ✅ done |
| M4 | Authorization (RBAC/ABAC/scope/masking/anti-escalation), staff realm | ✅ done |
| M5 | Plans, subscriptions, invoices, payments (sandbox), limits, entitlement sync | ✅ done (live payment gateway NOT implemented) |
| M6 | Industry templates (inheritance + provenance), assembly engine/products, dynamic navigation, configurable forms/fields | ⏳ next |
| M7 | Shared services: master data (party/product/location/UoM/currency), tax-engine interface, notifications, documents, outbox/inbox events, workflow engine v1 + approvals, reporting v1 | ⏳ |
| G1 | Foundation validation gate (spec STEP 4 list) — **stop for user review** | ⏳ |
| A | Core apps: Finance → Inventory → CRM → Sales → Procurement → WMS → HR/Payroll → Projects → Assets | ⏳ (each needs its own feature-level DRD first) |
| B | Advanced: Manufacturing/MES, Quality, Logistics, Contracts, BI, Treasury, GRC, PLM, SCM | ⏳ |
| C | Commerce & people extras, AI/automation, integrations, developer marketplace | ⏳ |
| D | Industry verticals (healthcare, education, agriculture, …) — demand-driven, regulated ones need expert input | ⏳ |

## 4. Remaining platform backlog (do these before business apps)
- **M6**: industry templates + inheritance, tenant apply (copy-on-apply, never overwrite tenant data), dependency resolution / incompatible combos, software "product" (edition) builder with versions, dynamic navigation from entitlements+permissions, configurable forms/fields/dashboards/terminology, internal application catalogue with activate/deactivate.
- **M7**: master data services; tax-engine interface + jurisdiction pack framework; notification service (email/in-app) — also replaces dev-only invitation-token display; document storage/versioning (S3-compatible); transactional outbox + idempotent inbox; workflow engine v1 (JSON definitions, approvals with separation of duties, delays, escalation); reporting v1; enterprise search (Postgres FTS).
- **Security/ops hardening**: break-glass support access (ticketed, time-boxed, tenant-visible), rate limiting, password reset, SSO (OIDC/SAML), httpOnly-cookie sessions for the web app, separate DB role for staff/registry writes, grant/entitlement cache, per-tenant time zone for hour constraints, data-residency (`data_region`), dedicated-DB tenants, per-tenant backup/restore tooling, CI pipeline file, Docker/Compose/Helm (needs a non-C: Docker data root), observability (OpenTelemetry).
- **Billing completion**: real payment gateway adapter (decision needed), tax on invoices, credit notes/refunds, dunning emails, metered usage billing (storage_mb, api_calls), annual-plan proration edge cases, invoice PDF.
- **Frontend**: Playwright e2e suite, password reset/profile, staff MFA screen, i18n + RTL, accessibility audit, theme toggle.
- **Developer platform**: API keys, OAuth apps, webhooks (signed), sandbox tenants, extension sandbox (Tier 1 declarative → Tier 2 out-of-process), third-party marketplace (after sandbox; payouts need legal review).
- **Spec work**: Part 3 (CRM) document missing; feature-level DRDs for Parts 9–52; PIM/Supplier master/Notification/Search specs.

## 5. Business-application backlog (summary; full registry in APPLICATION_REGISTRY.md)
Wave A: Finance (630 features), Inventory (1,132), CRM (≈798 reserved, missing), Sales (895), Procurement (1,013), WMS (477), HRM+Payroll (500), Projects, Assets.
Wave B: Manufacturing (519), Quality, Logistics/TMS, Contracts/CLM, BI, Treasury, GRC, PLM, SCM.
Then commerce (E-com, POS, loyalty, marketing, support), people extras (LMS, performance), AI/data platform, verticals.
Per-app method: DRD → ERD → API contract → manifest → migration → services → API → UI → tests → docs → acceptance tests → update status.

## 6. Rules for how we work (also in CLAUDE.md)
Gate first (never build on red) · isolation + authz + audit on everything · manifests are the single source of features · honest status ·
mutation-check tests · everything on D: · commit/push only when asked · ask before destructive/expensive/regulated steps · no fake payments/mock logic ·
don't claim compliance · vertical slices over breadth.

## 7. Recorded ideas and decisions (records are never deleted)
- **"Child" software first — RECORDED, status: NOT NEEDED NOW.** User idea (2026-11-22): before creating the massive ERP, build separate small software as its "child" (small standalone products / reusable kits, e.g. contacts, products, invoicing-lite, stock-lite) so the ERP can be assembled from them more easily. Same day the user paused it ("no child software yet"), and on 2026-11-23 said "we dont need child". **Do not build or propose it now.** The idea stays recorded here (not deleted) in case the user brings it back; the ERP applications are built directly as vertical slices on the platform kernel.
- **Nothing in the PRD/DRD is removed or descoped.** If the user's PRD/DRD documents specify any child / sub-application, application family, module or submodule, it stays in scope (see `docs/spec/SPEC_DIGEST.md` and `docs/architecture/APPLICATION_REGISTRY.md`). The "no child" decision applies only to the extra seed software Claude proposed, never to requirements the user wrote.
- Odoo is a design reference only (see §9) — never a dependency.

## 8. Open questions for the user
1. Part 3 (CRM) document — supply or approve drafting.
2. First target jurisdiction(s) and first vertical/customer (tax/payroll/compliance packs).
3. Capacity targets (tenants/users/transactions) and team/timeline beyond the 3-day window.
4. Data residency: single region or multi-region.
5. Payment gateway choice (Stripe or other) and whether real charging is in scope for the first release.
6. Approve Marketplace split (internal catalogue first, third-party later) and duplicate-merge rule (Parts 13–52 duplicates become SKUs).
7. What must be demo-able at the 3-day mark?

## 9. Odoo reference policy
Odoo is a useful reference for ERP domain design, but UEOS must not depend on it. Allowed: study structure/concepts from public docs or supplied files
and write our own implementation. Not allowed: copying code, XML views, translations, data files; importing Odoo packages; mimicking trademarks.
Odoo Community is LGPL-3.0 (copying code carries licence obligations); Odoo Enterprise is proprietary and must not be used. Supplied files go in
`reference/odoo/` (git-ignored). Record each influence in an ADR.

## 10. Deadline reality check
The user stated a 3-day window (from 2026-11-22). The full 52-domain catalogue is a multi-year effort (~20k features). Within the window the realistic
deliverable is: a working, secure, sellable platform foundation (done through M5) + M6/M7 + one business application slice (Finance chart of accounts/journals
or Inventory ledger) with honest status. Everything else stays in the backlog above.

## 11. How to resume after a break
`CLAUDE.md` §1 checklist → `PROJECT_STATUS.md` → this file → run the gate → continue with the next ⏳ milestone.
