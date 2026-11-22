"""registries, platform-staff realm, platform audit, roles/permissions/assignments, entitlements

Revision ID: 0002
"""
from alembic import op

revision = "0002"
down_revision = "0001"

TENANT_TABLES = ["roles", "role_permissions", "membership_roles", "entitlements"]
POLICY = """
alter table platform.{t} enable row level security;
create policy tenant_isolation on platform.{t}
  using (tenant_id = platform.current_tenant()) with check (tenant_id = platform.current_tenant());
"""

SQL = """
-- org integrity: a department's branch/parent must belong to the same company
alter table platform.branches add unique (tenant_id, id, company_id);
alter table platform.departments add unique (tenant_id, id, company_id);
alter table platform.departments add foreign key (tenant_id, branch_id, company_id)
  references platform.branches (tenant_id, id, company_id);
alter table platform.departments add foreign key (tenant_id, parent_id, company_id)
  references platform.departments (tenant_id, id, company_id);

-- ---------- global registries (no tenant data) ----------
create table platform.capability_domains (
  id uuid primary key, slug text not null unique check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null,
  description text not null default '', status text not null default 'active' check (status in ('active','archived')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now());

create table platform.business_models (like platform.capability_domains including all);

create table platform.industries (
  id uuid primary key, slug text not null unique check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null,
  parent_id uuid references platform.industries(id), description text not null default '',
  status text not null default 'active' check (status in ('active','archived')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now());

create table platform.applications (
  id uuid primary key, slug text not null unique check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null,
  description text not null default '', category text not null default 'general',
  capability_domain_id uuid references platform.capability_domains(id),
  version text not null default '0.1.0', legacy_ref text,
  status text not null default 'published' check (status in ('draft','published','archived')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now());

create table platform.modules (
  id uuid primary key, application_id uuid not null references platform.applications(id),
  slug text not null check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null, description text not null default '',
  legacy_ref text, status text not null default 'active' check (status in ('active','archived')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now(),
  unique (application_id, slug));

create table platform.submodules (
  id uuid primary key, module_id uuid not null references platform.modules(id),
  slug text not null check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null, description text not null default '',
  status text not null default 'active' check (status in ('active','archived')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now(),
  unique (module_id, slug));

create table platform.features (
  id uuid primary key, key text not null unique,
  application_id uuid not null references platform.applications(id),
  module_id uuid not null references platform.modules(id),
  submodule_id uuid references platform.submodules(id),
  slug text not null check (slug ~ '^[a-z][a-z0-9_]*$'), name text not null, description text not null default '',
  actions text[] not null check (array_length(actions, 1) > 0),
  depends_on text[] not null default '{}', sensitive boolean not null default false, audited boolean not null default true,
  default_tier text not null default 'standard', legacy_ref text,
  status text not null default 'specified' check (status in ('specified','implemented','tested','released','deprecated')),
  origin text not null default 'config' check (origin in ('code','config')), created_at timestamptz not null default now());

-- ---------- platform-staff realm ----------
create table platform.staff (
  id uuid primary key, email text not null unique check (email = lower(email)), password_hash text not null,
  display_name text not null default '',
  role text not null check (role in ('super_admin','registry_admin','support_admin')),
  status text not null default 'active' check (status in ('active','disabled')),
  mfa_secret text, mfa_enabled boolean not null default false,
  failed_attempts int not null default 0, locked_until timestamptz, created_at timestamptz not null default now());

create table platform.platform_audit_log (
  id bigserial primary key, seq bigint not null unique, ts timestamptz not null, actor_staff_id uuid,
  action text not null, entity_type text, entity_id text, data jsonb not null default '{}',
  prev_hash text not null, hash text not null);
create trigger platform_audit_no_update_delete before update or delete on platform.platform_audit_log
  for each row execute function platform.audit_immutable();
create trigger platform_audit_no_truncate before truncate on platform.platform_audit_log
  for each statement execute function platform.audit_immutable();

-- ---------- tenant authorization ----------
create table platform.roles (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id), name text not null,
  description text not null default '', is_system boolean not null default false,
  created_at timestamptz not null default now(), unique (tenant_id, id), unique (tenant_id, name));

create table platform.role_permissions (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id), role_id uuid not null,
  feature_key text not null, action text not null, constraints jsonb not null default '{}',
  unique (role_id, feature_key, action),
  foreign key (tenant_id, role_id) references platform.roles (tenant_id, id) on delete cascade);

create table platform.membership_roles (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id),
  membership_id uuid not null, role_id uuid not null, scope jsonb not null default '{}',
  expires_at timestamptz, granted_by uuid, created_at timestamptz not null default now(),
  foreign key (tenant_id, membership_id) references platform.memberships (tenant_id, id) on delete cascade,
  foreign key (tenant_id, role_id) references platform.roles (tenant_id, id) on delete cascade);
create index on platform.membership_roles (tenant_id, membership_id);

create table platform.entitlements (
  id uuid primary key, tenant_id uuid not null references platform.tenants(id), feature_key text not null,
  source text not null default 'manual', expires_at timestamptz, limits jsonb not null default '{}',
  created_at timestamptz not null default now(), unique (tenant_id, feature_key));

create function platform.list_tenants() returns table (id uuid, slug text, name text, status text, created_at timestamptz)
  language sql stable security definer set search_path = platform, pg_temp
  as $$ select id, slug, name, status, created_at from platform.tenants order by created_at $$;
revoke all on function platform.list_tenants() from public;
grant execute on function platform.list_tenants() to ueos_app;

grant select, insert, update, delete on platform.capability_domains, platform.business_models, platform.industries,
  platform.applications, platform.modules, platform.submodules, platform.features, platform.staff,
  platform.roles, platform.role_permissions, platform.membership_roles, platform.entitlements to ueos_app;
grant select, insert on platform.platform_audit_log to ueos_app;
grant usage on sequence platform.platform_audit_log_id_seq to ueos_app;
"""


def upgrade() -> None:
    op.execute(SQL)
    for t in TENANT_TABLES:
        op.execute(POLICY.format(t=t))


def downgrade() -> None:
    for t in ["entitlements", "membership_roles", "role_permissions", "roles", "platform_audit_log", "staff",
              "features", "submodules", "modules", "applications", "industries", "business_models", "capability_domains"]:
        op.execute(f"drop table platform.{t} cascade")
    op.execute("drop function platform.list_tenants()")
    op.execute("alter table platform.departments drop constraint departments_tenant_id_branch_id_company_id_fkey")
    op.execute("alter table platform.departments drop constraint departments_tenant_id_parent_id_company_id_fkey")
    op.execute("alter table platform.departments drop constraint departments_tenant_id_id_company_id_key")
    op.execute("alter table platform.branches drop constraint branches_tenant_id_id_company_id_key")
