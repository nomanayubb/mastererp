# UEOS — Requirements Digest (from the user's PRD/DRD documents)

Source: the Master PRD/DRD, application DRDs Parts 1, 2, 4–8, Parts 9–12, consolidated Parts 13–52 and the final engineering instruction, pasted by the
user on 2026-11-22. **This digest keeps the structure and the binding requirements; it does not reproduce the ~5,166 numbered feature lines
verbatim.** To keep the originals, save them as files in `docs/spec/source/` (e.g. `part-01-finance.md`) and the registry/manifests can index them.
Feature numbers are kept as `legacy_ref`. Part 3 (CRM, numbers 1526–2323) was never supplied.

---
## A. Master PRD / DRD (Sections 1–31)

**Vision.** One universal platform for any organisation type (SMB → multinational, government, NGO, education, healthcare, research, industrial,
professional, service, cooperative, franchise, startup, manufacturing, digital). No predefined industry catalogue; new industries/sub-industries/
business models/apps/modules/features by configuration and extension.
**Core objective (17 items).** Shared infrastructure, identity, database architecture; reusable capabilities; independent apps, modules, per-feature
entitlements; dynamic industry configs; custom software assembly; subscription mgmt; roles/permissions; workflow automation; AI integration;
external integrations; enterprise reporting; mobile+web; SaaS / private cloud / on-prem.
**Philosophy.** Build once reuse everywhere · configure before code · separate shared from industry-specific · modular apps/modules · feature-level
permissions · never hardcode industry counts · subscription ≠ security · backward compatible · fully auditable · extensible through documented APIs.

**Hierarchy (9 levels).** Platform → Capability domains → Applications → Modules → Submodules → Features → Actions & permissions → Workflows/automations →
Reports/dashboards/data services. Industry configurations are a separate layer referencing these. Reuse rule: e.g. Inventory is reused by retail,
wholesale, restaurants, hospitals, farms, factories, labs, construction, universities, govt warehouses, pharma, mining — industries add extensions, never duplicate the app.

**Capability registry (70 domains, extensible).** Finance & Accounting; Banking & Treasury; Taxation; Sales; CRM; Marketing; Procurement; Supplier Mgmt;
Inventory; Warehousing; Manufacturing; Production Planning; Quality; Supply Chain; Logistics; Transportation; Fleet; HR; Recruitment; Payroll; Workforce;
Project Mgmt; Task Mgmt; Asset; Equipment; Maintenance; Property; Facility; Contract; Document; Records; BI; Analytics; Data Warehousing; Data Governance;
BPM; Workflow Automation; RPA; AI; Enterprise Search; Communication; Customer Support; Service Mgmt; Learning; Content; PIM; PLM; Subscription; Revenue;
Risk; Compliance; Governance; Cybersecurity; Identity; Integration; API Mgmt; E-commerce; POS; Payment; Marketplace; Research; Environmental;
Sustainability; Energy; Knowledge; Innovation; Legal; Safety; Operations; Custom Industry Capabilities.

**Industry taxonomy (initial templates).** Commerce (retail, wholesale, distribution, supermarkets, e-commerce, marketplaces, fashion, electronics, pharmacies,
auto dealers) · Food & Hospitality · Manufacturing (textiles, garments, chemicals, electronics, automotive, furniture, packaging, pharma, industrial equipment) ·
Healthcare · Education · Agriculture (crops, fruit, vegetables, organic, greenhouse, livestock, dairy, poultry, fisheries, forestry, agri-trading) ·
Transportation · Construction & Property · Financial Services · Technology · Energy & Natural Resources · Public & Social orgs · Professional Services.
**Business models** (separate from industry; several per org): B2B, B2C, B2B2C, D2C, retail, wholesale, manufacturing, distribution, subscription, marketplace,
franchise, licensing, rental, leasing, service, project, nonprofit, government, cooperative, hybrid.
**Organisation types:** sole prop, partnership, private/public company, holding, subsidiary, franchise, cooperative, nonprofit, foundation, govt dept,
public authority, educational/healthcare institution, professional association, international organisation.

**Industry Configuration Engine.** Template = id, version, parent, business models, required/optional apps+modules, feature deps, custom fields, workflow/role/
dashboard/report templates, terminology, validation rules, regulatory config, recommended plans. Inheritance (e.g. Food&Hospitality → Restaurant → Fine Dining/
Fast Food/Casual/Cloud Kitchen; Bakery; Catering; Hotel) with provenance of source template and overrides.
**Dynamic Software Assembly Engine / Software Builder (22 capabilities).** Product create/name/describe; industry+business model; select apps/modules/submodules/
features; dependency validation (auto-identify deps, prevent incompatible combos, e.g. Restaurant POS needs catalogue, sales engine, tax engine, payment engine,
auth); workflows, dashboards, roles, menus, forms, custom fields, branding, pricing, subscription config, versioning, testing, publishing. Products reference
source apps (no duplication). Configuration for forms/fields/menus/dashboards/workflows/roles/notifications/reports/templates; code extensions only when
unavoidable, never arbitrary customer code without a secure sandbox + authorization.
**Marketplace.** Categories (enterprise, industry, productivity, financial, operational, analytics, AI, integrations, developer extensions, custom);
catalogue, search, descriptions, pricing, trials, install/activate/deactivate, versions, dependencies, compatibility, reviews, licenses, purchase history.
Developer marketplace: registration/verification, submission, security review, compatibility testing, approval, versioning, revenue sharing, analytics,
withdrawal, vulnerability reporting.

**Administration hierarchy.** Platform Super Admin (software owner; must NOT automatically see tenant business records) → 14 limited platform admin roles
(Operations, Application, Module, Feature Registry, Industry Template, Subscription, Billing, Marketplace, Integration, Security, Infrastructure, Support,
Analytics, Developer) → Tenant Owner → Tenant Admins → Department Admins (Finance, HR, Inventory, Sales, Procurement, Manufacturing, Warehouse, Support) →
Branch Admins → Managers → Supervisors → Employees → External users (customers, suppliers, vendors, contractors, consultants, auditors, delivery partners,
business partners) with separate portals and strictly limited access.
**Permission engine.** Hierarchy: Platform→Tenant→Company→Branch→Department→Application→Module→Submodule→Feature→Action→Record. Actions: view, create, edit,
delete, approve, reject, export, import, print, download, share, archive, restore, configure, manage permissions. Restrictions: record ownership, branch,
department, geography, amount/approval thresholds, working hours, sensitive fields, device, time-limited access, temporary delegation. Models: RBAC, ABAC,
ReBAC (where required), feature entitlements, record- and field-level authorization. Example: a cashier can view POS/create sales/print receipts/process permitted
refunds but cannot access payroll, company-wide profit, supplier payments, accounting config or delete financial records. **Backend must enforce; frontend hiding is not authorization.**
**Subscription & monetisation.** Pricing models: free, freemium, monthly, annual, per user/employee/branch/company/application/module/feature, usage, API,
storage, transaction, custom enterprise; combinable. Features: plan create/edit/publish/suspend, trials, activation, renewal, cancellation, upgrade/downgrade,
add-ons, billing cycles, invoices, payment history, failed-payment handling, grace periods, usage monitoring, analytics. Entitlements generated per subscription
(apps/modules/features + limits: users, branches, warehouses, storage, API calls — all configurable). Every protected op checks: tenant status, subscription status,
application entitlement, module entitlement, feature entitlement, user permission, resource limits, record-level access.
**Multi-tenant.** Tenant create/activate/suspend/archive/isolation/settings/branding/domain/storage/usage/backup/restore/subscription/monitoring. Org features:
multiple companies, parents, subsidiaries, branches, departments, divisions, business units, warehouses, facilities, factories, stores, teams. Isolation: tenant_id,
PostgreSQL RLS, tenant-scoped queries/jobs/cache keys/object paths/search indexes/audit logs, automated cross-tenant tests; shared-DB and dedicated-DB models.
**Global.** Languages/translation/RTL/date-number-currency formats/time zones/units/terminology; multi-currency (rates, sources, conversion, FX gain/loss);
multi-company (legal entities, consolidation, intercompany); configurable tax + country packs (never assume one country).
**Workflow engine.** Visual builder: trigger, condition, action, delay, approval, notification, branch, loop, integration call, human task, exception handler.
Event/scheduled/conditional/multi-level approval/recurring/cross-app, escalation, retry, failure recovery, history, analytics. Safety: sensitive actions (large
payments, payroll release, supplier bank changes, termination, journal posting, destructive ops) need authorization + human approval + immutable audit events.
**AI platform.** Provider-independent adapters. Apps: business, accounting, sales, procurement assistants; inventory/demand forecasting; customer support;
document processing; report generation; data analysis; workflow assistant; knowledge search; anomaly detection; predictive maintenance; scheduling.
Governance: model registry, provider config, model permissions, usage limits, cost monitoring, prompt mgmt, evaluation datasets, output logging, sensitive-data
controls, human approval, model versioning. **AI agents inherit the requesting user's authorization; never access what the user cannot; AI-generated financial/
operational actions must be validated before execution.**
**Reporting/BI.** Standard/custom/scheduled/interactive/consolidated/exportable reports; dashboard builder (charts, tables, KPIs, filters, drill-downs, saved
views); analytics (trend, forecast, variance, profitability…). All respect tenant + user permissions.
**Documents & records.** Registry, storage, classification, versions, approval workflows, e-signatures, contracts, retention, search, archive; preview, metadata,
tags, access control, expiry reminders, audit, secure sharing.
**Security & compliance.** Argon2/bcrypt hashing, MFA, SSO, session expiry, device sessions, password recovery, login anomaly detection; RBAC/ABAC; input validation,
output encoding, CSRF/XSS/SQLi/SSRF protection, rate limiting, secure uploads, dependency scanning, secrets mgmt, TLS + at-rest encryption, security monitoring.
Audit: logins, failures, user/permission/subscription changes, financial transactions, exports, sensitive reads, admin actions, integration activity (protected
against modification). Compliance frameworks configurable (GDPR, SOC 2, ISO 27001, PCI DSS, HIPAA, country tax/data-protection) — **never claim compliance because a feature exists.**
**Integrations.** Categories: payments, commerce, logistics, communication (email/SMS/WhatsApp/push), productivity (Google/Microsoft), business systems, hardware
(scanners, printers, POS, biometric, IoT, industrial). Each: connector registration, auth, encrypted credentials, test, sync, webhooks, retries, error handling,
logging, rate limits, versioning, permissions, disconnect, credential rotation. Never assume a provider API exists; validate each connector.
**Developer platform.** Portal: registration, API keys, OAuth apps, docs, webhooks, SDK docs, sandbox tenants, test data, extension registration, submission,
versioning, usage analytics. Plugin architecture: internal apps, official/third-party/industry extensions, connectors, custom enterprise apps — with permissions,
versioned interfaces, dependency declarations, compatibility checks, security review, resource limits, audit logging.
**UX.** Unified dashboard (navigation, app launcher, search, notifications, tasks, approvals, profile, org/branch selector, help); sidebar generated from
purchased apps + activated modules + user permissions + org config; responsive desktop/tablet/mobile, accessible, keyboard nav, configurable dashboards,
searchable menus, saved filters, light/dark, localisation, RTL.
**Technical.** Modular monolith first; recommended stack Next.js/React/TS/Tailwind; Python/FastAPI/Pydantic/SQLAlchemy; PostgreSQL; Redis; Celery; S3-compatible
storage; Docker/Compose/Nginx (K8s when justified); OpenTelemetry/Prometheus/Grafana; pytest/Playwright/load/security tests. Backend layers: API, auth, authz,
entitlement, application, domain, integration, persistence, background, monitoring. DB: migrations, FKs, indexes, transactions, unique constraints, tenant ownership,
soft delete, retention, audit history, backup/restore; relational for core records, JSONB only for flexible metadata. API: `/api/v1/...`, auth, authz, tenant
validation, input validation, errors, logging, docs, tests, idempotency keys for financial/operational duplicates.
**Targets (engineering goals, not promises).** p95 < 500 ms normal API; < 2 s simple dashboards; background tasks async; large imports/exports in background;
indexed search; monitored queries. Reliability: health/readiness, backups, recovery tests, alerting, retries, DR, migration controls.
**Admin control panel.** Dashboard (tenants, users, subscriptions, MRR/ARR, app/module/API/storage usage, health, errors, integrations); application registry,
feature registry, industry registry, subscription control (plans, pricing, limits, custom plans, discounts, renewals, enterprise contracts); tenant support
(config, health, subscription, authorised audit, integrations, errors) — private records need explicit authorisation, purpose, time limit and audit.
**Customer portal.** Business overview, applications, modules, employees, branches, metrics, notifications, approvals, subscription status; app mgmt (browse,
purchase, activate, deactivate, upgrade, configure, add-ons); org mgmt; billing (plan, invoices, payments, usage, renewals, up/downgrade, add-ons, cancel).
**Testing.** Unit per module; integration (e.g. Sales Order→Inventory Reservation→Warehouse Picking→Delivery→Invoice→Payment→Accounting); security (cross-tenant,
unauthorised API, privilege escalation, permission bypass, sessions, injection, uploads, secret leakage, subscription bypass); subscription tests (disabled apps,
expired, feature restrictions, limits, up/downgrade); industry tests (sample orgs: restaurant, retail, manufacturer, hospital, school, farm, logistics, construction,
professional services, nonprofit); regression.
**Roadmap phases 0–11.** 0 Discovery/spec · 1 Platform foundation · 2 Platform administration (registries) · 3 Permissions & entitlements · 4 Subscriptions &
marketplace · 5 Configuration & assembly engine · 6 Core business apps (Accounting, Sales, CRM, Procurement, Inventory, Warehouse, HR, Payroll, Project, Asset) ·
7 Advanced enterprise apps · 8 Industry apps · 9 AI & automation · 10 Integrations · 11 Mobile & enterprise deployment. Priority order given by the user:
foundation → application registry → module/feature registry → permission engine → subscription engine → industry registry → application assembly → marketplace →
core apps → industry extensions → AI/automation → developer ecosystem.
**Repo structure (suggested).** frontend/{web,mobile,shared-ui}; backend/{platform/*, applications/*, industries/{templates,extensions}, integrations, workflows, ai,
reporting, shared}; database/{migrations,seeds,schemas}; infrastructure/{docker,deployment,monitoring,backup}; tests/{unit,integration,security,performance,e2e};
docs/{PRD,DRD,ADR,API,SECURITY,MODULES,INDUSTRIES}. (Actual repo uses `backend/ueos/...`; boundaries are what matter.)

### Mandatory development rules (35) — binding
1 Read the whole PRD/DRD · 2 don't generate all apps first · 3 inspect repo first · 4 produce an implementation plan · 5 identify missing requirements · 6 write ADRs ·
7 design DB before dependent modules · 8 platform foundation first · 9 reusable domain services · 10 no duplicated business logic · 11 no giant source files ·
12 migrations · 13 automated tests · 14 type checking · 15 validate every API input · 16 backend authorization · 17 backend subscription entitlements · 18 tenant isolation ·
19 never hardcode industry limits · 20 never hardcode subscription packages · 21 never hardcode application visibility · 22 never allow unauthorized feature activation ·
23 API versioning · 24 application versioning · 25 maintain feature identifiers · 26 audit history · 27 document every module · 28 tests for every feature ·
29 never call a feature complete when only the interface exists · 30 no mock responses replacing real logic · 31 no fake payment integrations in production ·
32 no secrets in source · 33 don't silently modify existing schemas · 34 don't break existing tenant configurations on upgrade · 35 don't deploy unfinished functionality.
**Definition of Done:** requirements, DB, backend, API validation, authorization, entitlement enforcement, frontend, error handling, audit, unit tests, integration
tests, documentation, successful acceptance testing.
**Master acceptance criteria** (foundation): platform owner manages ecosystem; tenants register isolated; independent orgs; admins create apps/modules/submodules/
features/industries/software editions; plans, purchases, add-ons, entitlements enforced, usage monitored, billing recorded; limited platform + tenant admin roles;
department/branch/feature permissions with backend enforcement; shared capability reused across industries; new industry registered, inheriting, with extensions;
core apps communicate; financial transactions auditable; workflows reliable; reports respect permissions; integrations monitored; tests pass; backups restorable;
security tests pass; deployment documented; monitoring operational.
**Final instruction (parts 13–52 + engineering directive).** Treat each part as an independently sellable domain; reuse shared infra; configurable industry templates;
no fake/decorative functionality; maintain backlog with implemented/tested/incomplete/blocked; inspect repo before building; wait for approval before large-scale
development (given 2026-11-22: "Approve Phase 1").

**Deliverables list (16):** master architecture; application registry (52 domains); dependency graph; ERDs; migrations; API specs; security architecture; UI/UX design
system; SaaS licensing architecture; workflow architecture; integration architecture; testing strategy; deployment architecture; implementation backlog; feature-completion
tracking; production deployment docs.

---
## B. Application DRDs — structure and acceptance tests

Ownership boundaries (single owner of data; others reference/events): PIM = product identity · Inventory = stock ledger/reservations/traceability · WMS = bin-level execution ·
Procurement = requisitions/RFQ/POs · Finance = GL/AP/AR/accounting · Manufacturing = production orders/BOM · Sales = quotes/orders · Logistics = shipment execution ·
Quality = inspections/decisions · CLM = master contract record · EAM = physical asset record (Finance = depreciation books) · HRM = employee/workforce.

### Part 1 — Finance & Accounting (UEOS-FIN-001), features 1–630
Modules (24): General Ledger · Chart of Accounts · Journal Management · Accounts Receivable · Accounts Payable · Bank Management · Cash Management · Payment Management ·
Financial Reconciliation · Budget Management · Cost Accounting · Fixed Asset Accounting · Depreciation · Tax Management · Financial Consolidation · Financial Planning ·
Expense Management · Credit Management · Revenue Recognition · Financial Reporting · Audit Management · Multi-Currency · Multi-Company · Financial Forecasting.
Accounting rules: double-entry; posted journals never silently edited/deleted (reverse/adjust); balanced before posting; decimal arithmetic; transaction + functional
currency; fiscal-period locking; audit trail; transactional DB ops; idempotency against duplicate processing; clear draft/approved/posted/reversed/cancelled states.
Initial entities: ledger_accounts, ledger_transactions, ledger_entries, ledger_periods, fiscal_years, accounting_journals, journal_entries, journal_approvals, customer_invoices(+lines),
credit/debit notes, customer_payments, payment_allocations, supplier_bills(+lines), supplier payments, bank_accounts/transactions/statements/reconciliations, cash_accounts/transactions,
petty_cash_funds/expenses, cash_closings, budgets(+lines/allocations/revisions/approvals), fixed_assets, asset_categories/acquisitions/disposals, depreciation_schedules/entries,
tax_categories/rates/rules/transactions/periods/returns, financial_reports/templates, audit_plans/findings/events.
**Acceptance tests (20):** 1 chart of accounts · 2 customer invoice · 3 post invoice with balanced entries · 4 partial customer payment · 5 verify receivables · 6 supplier bill ·
7 supplier payment · 8 reconcile bank statement · 9 create+approve budget · 10 register fixed asset · 11 depreciation schedule · 12 financial statements · 13 close period ·
14 cashier unauthorized access · 15 other tenant cannot access · 16 expired subscription blocks protected ops · 17 reverse posted transaction preserving history ·
18 debits = credits · 19 consolidated multi-company report · 20 restore backup and verify integrity.

### Part 2 — Sales Management (UEOS-SAL-002), features 631–1525
Modules (26): Configuration · Channels · Lead Mgmt · Opportunity · Quotation · Sales Order · Pricing · Product & Service Sales · Customer Sales · Sales Team · Commission ·
Targets & Quotas · Forecasting · Contract-Based Sales · Subscription Sales · Recurring Sales · Returns & Refunds · Discounts & Promotions · Delivery Coordination · Invoicing
Integration · Payment Tracking · Approval Mgmt · Analytics · Automation · Customer Experience · Administration.
Sensitive actions are explicit endpoints (`POST /orders/{id}/confirm|cancel`, `quotations/{id}/approve|convert`, `returns|refunds/{id}/approve`), never plain edits.
Roles: Sales App Admin, Sales Manager, Regional/Branch Sales Manager, Team Leader, Sales Rep (field/inside), Coordinator, Analyst, Approver, Pricing Manager, Commission Manager,
Contract Manager, Customer Service Rep, Read-only Auditor, Customer Portal User, External Sales Partner (a rep cannot approve own discounts, change company pricing, export all customers,
see other branches, modify posted financials).
**Acceptance tests (24):** channel · API lead · auto-assign · lead→opportunity · configurable pipeline · multi-line quotation · discount needing approval · quotation PDF · customer
acceptance · quotation→order without duplicating lines · stock check + reservation · partial fulfilment · invoice via Finance · partial payment sync · return · authorised partial refund ·
commission · forecast · actual vs target · restricted records of another salesperson · tenant isolation · expired subscription blocks features · cancellations/changes keep audit ·
concurrent orders cannot oversell.

### Part 3 — CRM: **not supplied** (numbers 1526–2323 reserved).

### Part 4 — Procurement (UEOS-PROC-004), features 2324–3336 (30 modules)
Configuration · Organization & Governance · Purchase Requisition · Planning · Budget · Supplier Sourcing · RFI · RFQ · Supplier Quotation · Tender & Bidding · Supplier Evaluation ·
Purchase Order · Purchase Contract · Service Procurement · Strategic Procurement · Category Mgmt · Scheduling · Delivery & Fulfilment · Goods & Service Receipt Coordination ·
Supplier Performance · Supplier Risk · Compliance · Invoice Coordination (2/3-way match; Finance owns invoices/payments) · Returns & Disputes · Collaboration Portal ·
Automation · AI Procurement (AI never approves/awards) · Analytics · Administration · Industry Extensions. Standard/tender/emergency/service workflows defined; emergency never
bypasses all controls. Packages: Starter, Professional, Enterprise, Government/Institutional (examples, not fixed). Tests cover requisitions, budgets (concurrency), sourcing, sealed-bid
tenders, POs, contracts, receipts/invoice matching, suppliers, tenant isolation (8 paths), industry extensions.

### Part 5 — Inventory (UEOS-INV-005), features 3337–4468 (30 modules)
Configuration & Policies · Item Profiles · Organization & Locations · Stock Master & Balances · Stock Movements (immutable ledger) · Reservation & Allocation (no overselling) ·
Lot/Batch · Serial · Barcode/QR/RFID · Counting · Replenishment · Forecasting · Transfers · Receiving Coordination · Issue & Consumption · Returns · Quality & Quarantine ·
Expiry/Shelf-life · Costing & Valuation (FIFO/weighted/standard/specific; Finance owns GL) · Audit & Reconciliation · Optimization · Traceability/Genealogy · Consignment ·
Packaging/UoM · Automation · AI · Analytics · Administration & Security · Industry Extensions · Integration. Events (versioned, outbox/inbox): inventory.stock.received/issued/adjusted/
transferred/reserved/released …, consumes procurement/warehouse/sales/manufacturing/quality events. 84 acceptance tests (stock, reservations incl. concurrency, batch/serial, counting,
replenishment, receiving/returns, expiry/quality, costing/Finance, consignment/integration, platform).

### Part 6 — WMS (UEOS-WMS-006), features 4469–4945 (30 modules)
Configuration · Structure · Zones/Aisles/Racks/Bins · Receiving · Dock Mgmt · Put-away · Storage · Picking · Wave/Batch picking · Packing · Dispatch · Cross-docking · Replenishment execution ·
Internal transfers · Returns · Inventory verification · Labor · Equipment · Automation · Slotting · Yard · Cold chain · Safety · Task Mgmt · Workflow · AI · Analytics · Administration · Industry
Extensions · Integration. WMS cannot override Inventory ledger. 25 acceptance tests.

### Part 7 — HRM (UEOS-HRM-007), features 4946–5445 (35 modules)
HR Config · Org structure · Workforce planning · Positions/Jobs · Employee master · Lifecycle · Recruitment/ATS · Assessment · Offers · Onboarding · Self-service · Attendance · Shifts/Rosters ·
Leave · Timesheets · Compensation · Payroll (rules by country/jurisdiction — never hardcode a country) · Benefits · Performance · Goals · Learning · Skills · Career/Succession · Engagement ·
Employee relations · Disciplinary · Travel & expense · Documents · Offboarding · Analytics · AI (no unreviewed hiring/dismissal/pay/disciplinary decisions) · Automation · Admin & Security ·
Industry Extensions · Integration. Sensitive HR data has strict field-level permissions + retention. 30 acceptance tests.

### Part 8 — Manufacturing (UEOS-MFG-008), features 5446–5964 (32 modules)
Configuration · Facilities · Engineering coordination · BOM · Routing · Work centers · Production planning · MPS · MRP · Capacity · Production orders · Scheduling · Execution · Work instructions ·
Material issue/consumption · Output & finished goods · Batch/process · Discrete/assembly · Quality coordination · Scrap/waste/rework · Subcontracting · Costing coordination · Tooling · Labor ·
Traceability · Maintenance coordination · Automation/IoT · AI · Analytics · Admin & Security · Industry Extensions · Integration. 30 acceptance tests.

### Parts 9–12 (module-level only)
9 **Quality Mgmt**: planning, control, assurance, incoming/production/final quality, service quality, defects, NCR, CAPA, audits, quality docs, lab, calibration, risk, supplier quality, customer quality,
analytics (+SPC, Six Sigma, FMEA, RCA, Pareto, control charts, AI defect classification). Roles: Quality Admin/Manager/Supervisor/Inspector, Lab Technician, Auditor, Compliance Officer.
10 **Logistics/TMS**: planning, transportation modes, fleet, drivers, shipments, dispatch, route optimisation, freight, carriers, last-mile, international (customs), cargo, reverse logistics, fuel,
vehicle maintenance, warehouse connectivity, tracking (GPS), logistics finance, analytics.
11 **Project Mgmt**: portfolio, planning, creation/templates, tasks/subtasks/dependencies (cycle detection), scheduling, Gantt/CPM/PERT, resources, teams, budgets, costs (EVM: PV/EV/AC/CPI/SPI), time,
risk, issues, documents, collaboration, approvals, change, quality, vendors, procurement, reporting, closure.
12 **EAM/CMMS**: asset registry, acquisition, lifecycle, tracking (QR/RFID/GPS), assignment, fixed asset, equipment, machinery, fleet, facility, land/property, IT assets, maintenance planning,
preventive/predictive/corrective/emergency, work orders, spare parts, workforce, vendors, warranty, calibration, energy, inspection, risk, disposal, analytics (TCO, MTBF, MTTR, OEE); IoT via MQTT.

### Parts 13–52 — see `docs/architecture/APPLICATION_REGISTRY.md` (all 40 listed with modules, advanced features, tables, products).
Common universal rules there: shared permission engine, workflow engine, API/integration framework (REST, webhooks, rate limits, idempotency, integration marketplace), independent commercial
packaging (monthly/annual, per-user, per-org, usage, feature licensing, trials, add-ons, enterprise contracts, up/downgrade, entitlements), industry configuration engine; common DB fields
(id, tenant_id, organization_id, branch_id, department_id, created_by/updated_by, created_at/updated_at, status, metadata) applied only where relevant.

---
## C. Source files
Put original documents in `docs/spec/source/` (not yet present). Until then this digest + `docs/architecture/GAP_ANALYSIS.md` are the record.
