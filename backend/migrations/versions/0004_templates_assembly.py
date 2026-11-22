"""industry templates (inheritance), tenant configuration (modules, fields, terminology, dashboards), products (editions)

Revision ID: 0004
"""
from alembic import op

revision = "0004"
down_revision = "0003"

TENANT_TABLES = ["tenant_modules", "tenant_custom_fields", "tenant_terminology", "tenant_dashboards", "tenant_settings",
                 "tenant_template_applications"]
POLICY = """
alter table platform.{t} enable row level security;
create policy tenant_isolation on platform.{t}
  using (tenant_id = platform.current_tenant()) with check (tenant_id = platform.current_tenant());
"""

SQL = """
alter table platform.features add column conflicts_with text[] not null default '{}';
alter table platform.companies add column custom jsonb not null default '{}';

-- ---------- global: industry templates (versioned, inheritable) ----------
create table platform.industry_templates (
  id uuid primary key,
  industry_id uuid not null references platform.industries(id),
  slug text not null check (slug ~ '^[a-z][a-z0-9_]*$'),
  name text not null,
  version int not null default 1 check (version >= 1),
  parent_id uuid references platform.industry_templates(id),
  status text not null default 'draft' check (status in ('draft','published','deprecated')),
  config jsonb not null default '{}',
  created_at timestamptz not null default now(),
  unique (slug, version));

-- ---------- global: products (software editions assembled from registry items) ----------
create table platform.products (
  id uuid primary key,
  slug text not null unique check (slug ~ '^[a-z][a-z0-9_]*$'),
  name text not null,
  description text not null default '',
  industry_slug text,
  business_models text[] not null default '{}',
  status text not null default 'draft' check (status in ('draft','published','archived')),
  created_at timestamptz not null default now());

create table platform.product_versions (
  id uuid primary key,
  product_id uuid not null references platform.products(id) on delete cascade,
  version int not null check (version >= 1),
  status text not null default 'draft' check (status in ('draft','published')),
  composition jsonb not null default '{}',
  notes text not null default '',
  created_at timestamptz not null default now(),
  published_at timestamptz,
  unique (product_id, version));

-- ---------- tenant-owned configuration (never overwritten by template updates) ----------
create table platform.tenant_modules (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  application_slug text not null, module_slug text not null, source text not null default 'tenant',
  activated_at timestamptz not null default now(), unique (tenant_id, application_slug, module_slug));

create table platform.tenant_custom_fields (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  entity text not null, key text not null check (key ~ '^[a-z][a-z0-9_]*$'), label text not null,
  type text not null check (type in ('text','number','date','boolean','select')),
  required boolean not null default false, options jsonb not null default '[]', sort int not null default 0,
  source text not null default 'tenant', created_at timestamptz not null default now(),
  unique (tenant_id, entity, key));

create table platform.tenant_terminology (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  term text not null, label text not null, source text not null default 'tenant', unique (tenant_id, term));

create table platform.tenant_dashboards (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  name text not null, config jsonb not null default '{}', source text not null default 'tenant', unique (tenant_id, name));

create table platform.tenant_settings (
  tenant_id uuid primary key references platform.tenants(id),
  branding jsonb not null default '{}',
  applied_template text, applied_template_version int,
  installed_product text, installed_product_version int,
  updated_at timestamptz not null default now());

create table platform.tenant_template_applications (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  template_slug text not null, template_version int not null,
  resolved jsonb not null, provenance jsonb not null, result jsonb not null default '{}',
  applied_by uuid, applied_at timestamptz not null default now());

grant select, insert, update, delete on platform.industry_templates, platform.products, platform.product_versions,
  platform.tenant_modules, platform.tenant_custom_fields, platform.tenant_terminology, platform.tenant_dashboards,
  platform.tenant_settings, platform.tenant_template_applications to ueos_app;
"""


def upgrade() -> None:
    op.execute(SQL)
    for t in TENANT_TABLES:
        op.execute(POLICY.format(t=t))


def downgrade() -> None:
    for t in ["tenant_template_applications", "tenant_settings", "tenant_dashboards", "tenant_terminology",
              "tenant_custom_fields", "tenant_modules", "product_versions", "products", "industry_templates"]:
        op.execute(f"drop table platform.{t} cascade")
    op.execute("alter table platform.companies drop column custom")
    op.execute("alter table platform.features drop column conflicts_with")
