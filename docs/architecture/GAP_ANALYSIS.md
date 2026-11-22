# UEOS — Reconciliation & Gap Analysis

Status: **Proposed — awaiting approval.** No application code has been written.
Scope reviewed: Master PRD/DRD, Parts 1–2 (Finance, Sales), Parts 4–8 (Procurement, Inventory, WMS, HRM, Manufacturing), Parts 9–12, consolidated Parts 13–52, and the final engineering directive.
Repository state at review: empty directory (greenfield). Toolchain: Python 3.11.5, Node 24, Docker 29. No local PostgreSQL (will run in Docker).

---

## 1. What is actually in the documents

| Fact | Evidence |
|---|---|
| **Part 3 is missing.** | Feature numbering jumps from 1525 (end of Sales) to 2324 (start of Procurement). 798 feature numbers (1526–2323) are unaccounted for; by sequence Part 3 is CRM. The Part 2 text is also truncated mid-sentence in its header. |
| Only **5,166 features** are specified at feature level. | Finance 630 · Sales 895 · Procurement 1,013 · Inventory 1,132 · WMS 477 · HRM 500 · Manufacturing 519. |
| Parts 9–12 have **modules/submodules and entity lists, but no numbered features.** | QMS, TMS, PMS, EAM. |
| Parts 13–52 are **one paragraph each** (module list, "advanced" list, table names). | Not implementable without a further DRD pass. |
| The master PRD itself says it is *not* a 10,000-feature implementation spec. | "each application should receive its own detailed feature-level DRD … before Claude Code implements it". |

**Scale reality check.** Extrapolating the 5,166 specified features to 43 distinct domains gives roughly 20,000+ features. That is a multi-year, multi-team programme. The roadmap below therefore delivers *vertical slices on a fixed platform*, not breadth. It does not claim the whole catalogue can be finished in one pass.

---

## 2. Duplicates and overlaps across the 52 "domains"

The "52 applications" are really **~43 distinct domains** (see `APPLICATION_REGISTRY.md`).

**Direct duplicates (9)** — Parts 13–52 re-specify Parts 1–12:
17 CRM = Part 3 · 18 Sales = Part 2 · 25 HRM, 26 Recruitment, 27 Payroll, 28 Workforce = Part 7 · 37 MES ≈ Part 8 · 40 WMS = Part 6 · 41 Procurement/SRM = Part 4.
**Proposal:** one implementation each. Parts 13–52 versions become *packaging SKUs and extra requirements merged into the original domain*, never a second codebase.

**Overlaps (7)** — distinct product but shared engine: 23 Subscription billing (↔ Sales modules 15/16 and platform billing) · 24 Loyalty (↔ Sales promotions) · 29 LMS (↔ HR learning) · 30 Performance (↔ HR modules 19–23) · 31 Treasury (↔ Finance bank/cash) · 32 Tax (↔ Finance Tax Management) · 33 GRC (↔ Finance audit, Procurement compliance, QMS audit/risk).

**Platform services dressed as applications (6)** — 13 BI · 14 AI · 15 Data Mgmt · 16 BPA/RPA · 35 DMS · 36 Security. These are shared infrastructure. They are built once in the platform and exposed as sellable apps through the entitlement layer.

**Referenced but never specified (4)** — Product Information Management (PIM), Supplier Management, Notification service, Enterprise Search. Inventory, Procurement and Manufacturing all *depend* on PIM and Supplier Management. These need specs before Wave 1.

---

## 3. Ownership conflicts and proposed single owners

| Concern | Conflict in docs | Proposed owner (others hold references/events only) |
|---|---|---|
| Customer / supplier / employee identity | Finance profiles, Sales profile, CRM customers, Procurement suppliers, HR employees all define their own | `master.party` (+ role profiles per app). HR `employee` stays authoritative for workforce, linked to `identity.user`. |
| Product identity | Inventory, Sales, Mfg, PLM, e-commerce each have products | `master.product` registry (PIM extends it). Apps keep *profiles* referencing product id. |
| Fixed assets & depreciation | Finance (fixed_assets, depreciation) vs EAM (assets, asset_depreciation) | EAM owns the physical asset; Finance owns capitalization/depreciation books referencing `asset_id`. |
| Budgets | Finance, Procurement, Projects, HR dept budgets | Finance owns the budget ledger. Others create reservations/commitments via API. |
| Contracts | Sales, Procurement, Legal/CLM | CLM owns the master contract record. Sales/Procurement hold typed references. |
| Locations / bins | Inventory `inv_locations` vs WMS `wms_bins` | One `master.location` tree. Inventory uses it down to stock location; WMS extends leaf nodes with bin/rack attributes. |
| Valuation / GL | Inventory costing vs Finance | Inventory emits valuation events; Finance posts. |
| Subscriptions | Platform billing vs Sales subscriptions vs Part 23 | Two namespaces: `platform.billing` (UEOS selling to tenants) and tenant-scoped `rev.*` (tenants selling to their customers). Shared billing library. |
| Tax | Finance, Part 32, HR payroll tax | One tax-engine service with jurisdiction packs, called by all. |
| Table-name collisions | `invoices`, `purchase_orders`, `shipments`, `warehouses`, `stock_movements`, `production_orders`, `projects`, `assets`, `bank_transactions` appear in several parts | **PostgreSQL schema per module** (`fin`, `inv`, `wms`, …). The spec's `inv_`/`wms_` prefixes are kept where given. |

---

## 4. Numbering defects

- Header ranges disagree with content: WMS says 4469–4968 but its last feature is 4945; HRM starts at 4946, so the stated ranges overlap. Manufacturing says 5446–5945 but runs to 5964.
- Numbers are ordinal, so they break whenever a feature is inserted.

**Proposal:** stable slug IDs (`fin.gl.period.close`) become the key; the spec number is stored as `legacy_ref`. A manifest linter rejects duplicate slugs. The 798-number gap is reserved for Part 3.

---

## 5. Technical gaps and proposed solutions

| # | Gap | Proposed solution |
|---|---|---|
| G1 | "Independently deployable apps" vs "start with modular monolith" | One codebase and deployable; module boundaries enforced in CI (`import-linter`): an app may import only `platform.*` and another app's `contracts` package. Extraction later is mechanical. |
| G2 | Tenant isolation: RLS vs dedicated DB vs "tenant backup/restore" | Shared DB + RLS first. Non-owner DB role without `BYPASSRLS`; composite FKs include `tenant_id`; `SET LOCAL app.tenant_id` per transaction. Per-tenant restore needs export/import tooling (not just PITR), so tenants who need it go to a dedicated DB. Same migrations serve both. |
| G3 | Data residency not specified (global + GDPR) | Add `data_region` to tenant; region-pinned DB/object storage; decide before first EU tenant. |
| G4 | Platform admin "must not see tenant data" vs support needs | Break-glass access: ticket-linked grant, scoped, time-boxed, dual-approved, fully audited, tenant-visible. |
| G5 | "Immutable" audit logs | Append-only table, per-tenant hash chain, DB role with no UPDATE/DELETE, monthly partitions, periodic anchor export. Honest wording: *tamper-evident*. |
| G6 | Dynamic industries/fields vs "no giant JSON table" | Registry-defined custom fields stored in `custom jsonb` on typed relational tables; validated against registry schema; GIN-indexed; promoted to columns when hot. |
| G7 | ~20k features × (permission + entitlement + test) | Code-first YAML manifests per module generate registry, permission and entitlement rows. A traceability matrix (feature → tests) computes status automatically: `specified → implemented → tested → released`. |
| G8 | 43 domains × screens, with "no placeholder UI" | Metadata-driven UI: navigation from registry; forms/grids from schemas; custom pages where needed. This is real functionality, not decoration. |
| G9 | Third-party extensions and "never run customer code" | Tier 1 declarative (fields, workflows, templates, reports). Tier 2 out-of-process apps via OAuth + webhooks. Tier 3 first-party in-process only. Third-party code never runs in the core process. |
| G10 | On-prem deployment can't call SaaS entitlement service | Signed offline licence bundles (entitlements + expiry) verified locally. |
| G11 | Offline POS / mobile scanning sync | Client-generated idempotency keys + server-side conflict policy per document type; design before Part 22 / Inventory scanning. |
| G12 | Stock concurrency / overselling | Append-only ledger + balance projection updated in same transaction with row locks and `CHECK (available >= 0)` where policy forbids negatives. Concurrency tests mandatory. |
| G13 | Double-entry integrity | Deferred constraint trigger: debits = credits per transaction; posted rows immutable by trigger; reversal-only corrections; `NUMERIC` money, no floats. |
| G14 | Event delivery | Transactional outbox → worker → Redis Streams; idempotent inbox. One broker initially (Redis). RabbitMQ only if needed. |
| G15 | Workflow engine scope | Postgres-persisted state-machine engine executing JSON definitions; visual builder emits the same JSON. Evaluate Temporal only if durable-timer needs outgrow it (ADR-009). |
| G16 | AI permissions | AI gateway executes tools with the *user's* token. Retrieval filters by stored ACL labels (pgvector). AI output creates *proposals*, never direct writes to financial/stock/HR records. |
| G17 | Search, analytics, mobile stacks unspecified | Postgres FTS → OpenSearch when justified. Read replica + materialized views → warehouse later. Mobile: PWA first, native only if device features demand it. |
| G18 | No capacity assumptions | Need target tenants/users/transactions to size anything (see Decisions). |
| G19 | Compliance claims | Platform provides controls and evidence only. No claim of GDPR/SOC2/PCI/HIPAA status. Cards: tokenised via provider, no PAN storage. |
| G20 | Marketplace revenue share / payouts | Regulated money movement. Catalogue and entitlements first; third-party payouts only after legal review. |
| G21 | Healthcare, government tender, payroll tax | Jurisdiction- and regulation-specific. Built as country/regulatory packs with expert review; not started until a target jurisdiction and reviewer are named. |
| G22 | Priority table puts Marketplace (#8) before core apps (#9) | Split it: **internal catalogue + activation** (before apps, rides on entitlements) and **third-party developer marketplace** (after extension sandbox, Phase 8+). Flagged as a deviation for your approval. |

---

## 6. Decisions needed from you

1. **Part 3 (CRM) document** — please supply, or approve me drafting it from Parts 2/17 for your review.
2. **First target market** — which jurisdiction(s) for the first tax/payroll/compliance packs, and the first vertical/customer type to validate against? The spec deliberately does not say.
3. **Capacity targets** — rough expected tenants, users per tenant, and daily transactions in year 1 and year 3.
4. **Team/timeline** — who else will work on this (people, budget, deadline)? It changes whether the roadmap is sequential or parallel.
5. **Data residency** — single region at launch, or multi-region?
6. **Approve the Marketplace split** (G22) and the "duplicate parts become SKUs" rule (§2).
7. **Approve Phase 1** (repo scaffold + foundation M1–M2) to begin.
