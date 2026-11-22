"""subscriptions & billing: plans, plan items, subscriptions, invoices, payments, usage, billing events

Revision ID: 0003
"""
from alembic import op

revision = "0003"
down_revision = "0002"

TENANT_TABLES = ["subscriptions", "invoices", "payment_transactions", "usage_records", "billing_events"]
POLICY = """
alter table platform.{t} enable row level security;
create policy tenant_isolation on platform.{t}
  using (tenant_id = platform.current_tenant()) with check (tenant_id = platform.current_tenant());
"""

SQL = """
alter table platform.staff drop constraint staff_role_check;
alter table platform.staff add constraint staff_role_check
  check (role in ('super_admin','registry_admin','support_admin','subscription_admin'));

-- entitlements may now come from several sources (manual grant, subscription) for the same feature
alter table platform.entitlements drop constraint entitlements_tenant_id_feature_key_key;
alter table platform.entitlements add unique (tenant_id, feature_key, source);

create table platform.plans (
  id uuid primary key,
  slug text not null unique check (slug ~ '^[a-z][a-z0-9_]*$'),
  name text not null,
  description text not null default '',
  kind text not null default 'base' check (kind in ('base','addon')),
  status text not null default 'draft' check (status in ('draft','published','archived')),
  billing_period text not null default 'monthly' check (billing_period in ('monthly','annual')),
  currency char(3) not null default 'USD',
  base_price numeric(12,2) not null default 0 check (base_price >= 0),
  per_user_price numeric(12,2) not null default 0 check (per_user_price >= 0),
  trial_days int not null default 0 check (trial_days >= 0),
  is_default boolean not null default false,
  is_public boolean not null default true,
  created_at timestamptz not null default now());
create unique index plans_single_default on platform.plans (is_default) where is_default;

create table platform.plan_items (
  id uuid primary key,
  plan_id uuid not null references platform.plans(id) on delete cascade,
  kind text not null check (kind in ('feature','limit')),
  feature_pattern text,
  limit_key text,
  limit_value int check (limit_value is null or limit_value >= 0),   -- null = unlimited
  check ((kind = 'feature' and feature_pattern is not null and limit_key is null)
      or (kind = 'limit' and limit_key is not null and feature_pattern is null)));
create index on platform.plan_items (plan_id);

create table platform.subscriptions (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  plan_id uuid not null references platform.plans(id),
  kind text not null check (kind in ('base','addon')),
  status text not null check (status in ('pending','trialing','active','past_due','canceled','expired')),
  current_period_start timestamptz,
  current_period_end timestamptz,
  trial_end timestamptz,
  grace_end timestamptz,
  cancel_at_period_end boolean not null default false,
  pending_plan_id uuid references platform.plans(id),
  comped boolean not null default false,
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  unique (tenant_id, id));
create unique index subscriptions_one_live_base on platform.subscriptions (tenant_id)
  where kind = 'base' and status in ('pending','trialing','active','past_due');
create unique index subscriptions_one_live_addon on platform.subscriptions (tenant_id, plan_id)
  where kind = 'addon' and status in ('pending','trialing','active','past_due');

create table platform.invoices (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  subscription_id uuid not null,
  seq int not null,
  number text not null,
  kind text not null check (kind in ('subscription','proration')),
  period_start timestamptz not null,
  period_end timestamptz not null,
  currency char(3) not null,
  subtotal numeric(12,2) not null check (subtotal >= 0),
  total numeric(12,2) not null check (total >= 0),
  lines jsonb not null default '[]',
  status text not null default 'open' check (status in ('open','paid','void')),
  due_at timestamptz not null,
  paid_at timestamptz,
  created_at timestamptz not null default now(),
  unique (tenant_id, id), unique (tenant_id, seq), unique (tenant_id, number),
  foreign key (tenant_id, subscription_id) references platform.subscriptions (tenant_id, id));
-- a renewal run can never create two invoices for the same period
create unique index invoices_one_per_period on platform.invoices (subscription_id, period_start) where kind = 'subscription';

create table platform.payment_transactions (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  invoice_id uuid not null,
  amount numeric(12,2) not null,
  currency char(3) not null,
  status text not null check (status in ('succeeded','failed')),
  provider text not null,
  provider_ref text,
  idempotency_key text,
  created_at timestamptz not null default now(),
  unique (tenant_id, idempotency_key),
  foreign key (tenant_id, invoice_id) references platform.invoices (tenant_id, id));

create table platform.usage_records (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  metric text not null, quantity numeric(14,2) not null check (quantity >= 0),
  recorded_at timestamptz not null default now());
create index on platform.usage_records (tenant_id, metric, recorded_at);

create table platform.billing_events (
  id bigserial primary key,
  tenant_id uuid not null references platform.tenants(id),
  type text not null, data jsonb not null default '{}', created_at timestamptz not null default now());

create function platform.list_subscriptions()
  returns table (tenant_id uuid, tenant_slug text, plan_slug text, kind text, status text, current_period_end timestamptz, grace_end timestamptz)
  language sql stable security definer set search_path = platform, pg_temp
  as $$ select s.tenant_id, t.slug, p.slug, s.kind, s.status, s.current_period_end, s.grace_end
        from platform.subscriptions s join platform.tenants t on t.id = s.tenant_id
        join platform.plans p on p.id = s.plan_id order by t.slug, s.started_at $$;
revoke all on function platform.list_subscriptions() from public;
grant execute on function platform.list_subscriptions() to ueos_app;

grant select, insert, update, delete on platform.plans, platform.plan_items, platform.subscriptions, platform.invoices,
  platform.payment_transactions, platform.usage_records to ueos_app;
grant select, insert on platform.billing_events to ueos_app;
grant usage on sequence platform.billing_events_id_seq to ueos_app;
"""


def upgrade() -> None:
    op.execute(SQL)
    for t in TENANT_TABLES:
        op.execute(POLICY.format(t=t))


def downgrade() -> None:
    op.execute("drop function platform.list_subscriptions()")
    for t in ["billing_events", "usage_records", "payment_transactions", "invoices", "subscriptions", "plan_items", "plans"]:
        op.execute(f"drop table platform.{t} cascade")
    op.execute("delete from platform.entitlements where source <> 'manual'")
    op.execute("alter table platform.entitlements drop constraint entitlements_tenant_id_feature_key_source_key")
    op.execute("alter table platform.entitlements add unique (tenant_id, feature_key)")
    op.execute("alter table platform.staff drop constraint staff_role_check")
    op.execute("update platform.staff set role='super_admin' where role='subscription_admin'")
    op.execute("alter table platform.staff add constraint staff_role_check check (role in ('super_admin','registry_admin','support_admin'))")
