# Architecture Decision Records (log)

All entries are **Proposed** until approved. Each will be promoted to its own file when accepted.

| ID | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| ADR-001 | Modular monolith with import-linter-enforced boundaries | 43 domains with shared transactions (ledger, stock); services add distributed-transaction cost with no current benefit | Microservices per app |
| ADR-002 | Shared DB + Postgres RLS by default; dedicated DB as deployment option | Cheapest isolation that is testable; same migrations serve both | Schema-per-tenant (migration fan-out), DB-per-tenant only |
| ADR-003 | Schema-per-module (`fin`, `inv`, …) | Resolves table-name collisions across parts; clear ownership | Global prefixes only |
| ADR-004 | Slug feature IDs; spec numbers kept as `legacy_ref` | Spec numbering has overlaps, gaps and breaks on insert | Keep ordinal numbers |
| ADR-005 | Code-first YAML manifests sync to DB registries | Gives permissions, entitlements and test traceability for ~20k features without hand entry | Admin-UI-only registry |
| ADR-006 | Authorization pipeline: entitlement → RBAC → ABAC → record scope → field mask; `Requires()` mandatory on routes | "Frontend hiding is not authorization"; CI can verify coverage | Per-endpoint ad-hoc checks |
| ADR-007 | Extension tiers: declarative / out-of-process / first-party in-process | Never run customer code in core | In-process Python plugins |
| ADR-008 | Transactional outbox + idempotent inbox on Redis Streams | Reliable events without a second broker | RabbitMQ/Kafka first |
| ADR-009 | Workflow engine v1 = Postgres-persisted state machine; revisit Temporal later | Avoid infra weight until durable-timer needs prove it | Temporal/Camunda from day one |
| ADR-010 | Single owners for party, product, location, contract, budget, asset, tax (see GAP_ANALYSIS §3) | Prevents duplicate master data across apps | Per-app copies |
| ADR-011 | Parts 13–52 duplicates merge into originals as SKUs | One implementation, many packages | Second codebases |
| ADR-012 | Metadata-driven UI with custom-page escape hatch | Only feasible way to ship consistent UI across 43 domains | Hand-built screens per app |
| ADR-013 | Append-only, hash-chained audit log (tamper-evident) | Honest claim; meets "protected against modification" | Plain audit table |
| ADR-014 | Offline licence bundles for on-prem entitlements | On-prem cannot call SaaS | Phone-home only |
| ADR-016 | Sync SQLAlchemy Core + psycopg3 (not async ORM) for the platform; embedded Postgres (pgserver) for dev/test stored in project folder | Transaction-local RLS context and ledger code are simpler synchronously; Docker Desktop unavailable and its disk image would use C: | Async ORM; Docker Compose Postgres (kept as deployment target) |
| ADR-015 | PWA before native mobile | One codebase; device features not yet required | React Native |
| ADR-017 | Billing: payment-provider abstraction (`test` sandbox dev/test only, `manual` staff-recorded, real gateways not implemented); published plans immutable; subscription entitlements materialized into `platform.entitlements` with `expires_at = access_until` so lapses need no job; limits computed from subscriptions at check time; tenants that once subscribed but lapsed go to "restricted mode" (limit 0) | Prevents faking production payments; lapse can never remove limits; billing job is idempotent (unique invoice per subscription period) | Mutable plans; storing limits in entitlements; phone-home gateway first |
| ADR-018 | Odoo is a design reference only: no dependency, no copied code/templates/data; supplied files kept in git-ignored `reference/odoo/`; influences recorded in ADRs | Licence safety (LGPL-3 Community, proprietary Enterprise) and independence | Forking/depending on Odoo |

