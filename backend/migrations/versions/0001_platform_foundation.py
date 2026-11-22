"""platform foundation: tenants, identity, org tree, sessions, invitations, audit log + RLS

Revision ID: 0001
"""
from alembic import op

revision = "0001"
down_revision = None

TENANT_TABLES = ["memberships", "companies", "branches", "departments", "invitations", "sessions", "audit_log"]

UP = """
create schema if not exists platform;

create function platform.current_tenant() returns uuid language sql stable
as $$ select nullif(current_setting('app.tenant_id', true), '')::uuid $$;

create table platform.tenants (
  id uuid primary key,
  slug text not null unique check (slug ~ '^[a-z0-9][a-z0-9-]{2,40}$'),
  name text not null,
  status text not null default 'active' check (status in ('active','suspended','archived')),
  data_region text not null default 'default',
  created_at timestamptz not null default now()
);

-- global identity (a person can belong to several tenants); never exposed through tenant queries
create table platform.users (
  id uuid primary key,
  email text not null unique check (email = lower(email)),
  password_hash text not null,
  display_name text not null default '',
  mfa_secret text,
  mfa_enabled boolean not null default false,
  failed_attempts int not null default 0,
  locked_until timestamptz,
  created_at timestamptz not null default now()
);

create table platform.memberships (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  user_id uuid not null references platform.users(id),
  role text not null check (role in ('owner','admin','member')),
  status text not null default 'active' check (status in ('active','disabled')),
  created_at timestamptz not null default now(),
  unique (tenant_id, user_id),
  unique (tenant_id, id)
);

create table platform.companies (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  name text not null,
  legal_name text,
  country text,
  base_currency char(3) not null default 'USD',
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, name)
);

create table platform.branches (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  company_id uuid not null,
  name text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  unique (tenant_id, company_id, name),
  foreign key (tenant_id, company_id) references platform.companies (tenant_id, id)
);

create table platform.departments (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  company_id uuid not null,
  branch_id uuid,
  parent_id uuid,
  name text not null,
  status text not null default 'active',
  created_at timestamptz not null default now(),
  unique (tenant_id, id),
  foreign key (tenant_id, company_id) references platform.companies (tenant_id, id),
  foreign key (tenant_id, branch_id) references platform.branches (tenant_id, id),
  foreign key (tenant_id, parent_id) references platform.departments (tenant_id, id)
);

create table platform.invitations (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  email text not null check (email = lower(email)),
  role text not null check (role in ('admin','member')),
  token_hash text not null unique,
  invited_by uuid not null,
  expires_at timestamptz not null,
  accepted_at timestamptz,
  created_at timestamptz not null default now()
);

create table platform.sessions (
  id uuid primary key,
  tenant_id uuid not null references platform.tenants(id),
  user_id uuid not null references platform.users(id),
  refresh_hash text not null,
  prev_refresh_hash text,
  user_agent text,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  created_at timestamptz not null default now()
);
create index on platform.sessions (tenant_id, user_id);

create table platform.audit_log (
  id bigserial primary key,
  tenant_id uuid not null references platform.tenants(id),
  seq bigint not null,
  ts timestamptz not null,
  actor_user_id uuid,
  action text not null,
  entity_type text,
  entity_id uuid,
  data jsonb not null default '{}',
  prev_hash text not null,
  hash text not null,
  unique (tenant_id, seq)
);

create function platform.audit_immutable() returns trigger language plpgsql
as $$ begin raise exception 'platform.audit_log is append-only'; end $$;
create trigger audit_no_update_delete before update or delete on platform.audit_log
  for each row execute function platform.audit_immutable();
create trigger audit_no_truncate before truncate on platform.audit_log
  for each statement execute function platform.audit_immutable();

-- RLS: tenant-owned tables
alter table platform.tenants enable row level security;
create policy tenant_isolation on platform.tenants
  using (id = platform.current_tenant()) with check (id = platform.current_tenant());
"""

POLICY = """
alter table platform.{t} enable row level security;
create policy tenant_isolation on platform.{t}
  using (tenant_id = platform.current_tenant()) with check (tenant_id = platform.current_tenant());
"""

# Pre-authentication lookups run as owner (SECURITY DEFINER), expose a single uuid and nothing else.
FUNCS = """
create function platform.tenant_id_by_slug(p_slug text) returns uuid
  language sql stable security definer set search_path = platform, pg_temp
  as $$ select id from platform.tenants where slug = p_slug and status = 'active' $$;

create function platform.invitation_tenant(p_hash text) returns uuid
  language sql stable security definer set search_path = platform, pg_temp
  as $$ select tenant_id from platform.invitations
        where token_hash = p_hash and accepted_at is null and expires_at > now() $$;

revoke all on function platform.tenant_id_by_slug(text), platform.invitation_tenant(text) from public;
grant execute on function platform.tenant_id_by_slug(text), platform.invitation_tenant(text) to ueos_app;

grant usage on schema platform to ueos_app;
grant select, insert, update, delete on platform.tenants, platform.users, platform.memberships,
  platform.companies, platform.branches, platform.departments, platform.invitations, platform.sessions
  to ueos_app;
grant select, insert on platform.audit_log to ueos_app;
grant usage on sequence platform.audit_log_id_seq to ueos_app;
"""


def upgrade() -> None:
    op.execute(UP)
    for t in TENANT_TABLES:
        op.execute(POLICY.format(t=t))
    op.execute(FUNCS)


def downgrade() -> None:
    op.execute("drop schema platform cascade")
