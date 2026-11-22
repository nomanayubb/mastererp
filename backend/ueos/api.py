"""Tenant-facing HTTP layer. Every route MUST declare an access policy: public / authenticated / Requires(feature, action).
tests enforce this, and that every Requires() key+action exists in the feature registry."""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from ueos.platform import authz, billing, identity, organization, registry
from ueos.platform.authz import Authz
from ueos.platform.config import get_settings
from ueos.platform.errors import AuthError, DomainError
from ueos.platform.principal import Principal
from ueos.platform.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def public() -> None:
    return None


def authenticated(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
    if creds is None:
        raise AuthError("missing_token")
    c = decode_access_token(creds.credentials)
    p = Principal(UUID(c["sub"]), UUID(c["tid"]), UUID(c["mid"]), UUID(c["sid"]), c["role"])
    role = identity.session_active(p.tenant_id, p.session_id, p.membership_id)  # logout/disable take effect at once
    if role is None:
        raise AuthError("session_revoked")
    return Principal(p.user_id, p.tenant_id, p.membership_id, p.session_id, role)


def Requires(key: str, action: str) -> Callable[..., Authz]:
    """Route dependency: session + tenant status + entitlement + RBAC + static ABAC. Returns the Authz for scope/masking."""

    def dep(p: Annotated[Principal, Depends(authenticated)]) -> Authz:
        return authz.authorize(p, key, action)

    dep.__ueos_access__ = "feature"  # type: ignore[attr-defined]
    dep.__ueos_feature__ = (key, action)  # type: ignore[attr-defined]
    return dep


public.__ueos_access__ = "public"  # type: ignore[attr-defined]
authenticated.__ueos_access__ = "authenticated"  # type: ignore[attr-defined]

Me = Annotated[Principal, Depends(authenticated)]
UA = Annotated[str | None, Header(alias="user-agent")]


def _need(key: str, action: str) -> Any:
    return Annotated[Authz, Depends(Requires(key, action))]


class RegisterIn(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=120)
    slug: str
    email: EmailStr
    password: str
    display_name: str = ""


class LoginIn(BaseModel):
    tenant_slug: str
    email: EmailStr
    password: str
    mfa_code: str | None = None


class RefreshIn(BaseModel):
    refresh_token: str


class CodeIn(BaseModel):
    code: str


class InviteIn(BaseModel):
    email: EmailStr
    role: str = "member"


class AcceptIn(BaseModel):
    token: str
    password: str
    display_name: str = ""


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = None
    country: str | None = Field(default=None, max_length=2)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)


class BranchIn(BaseModel):
    company_id: UUID
    name: str = Field(min_length=1, max_length=200)


class DepartmentIn(BaseModel):
    company_id: UUID
    branch_id: UUID | None = None
    parent_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)


class PermissionIn(BaseModel):
    feature_key: str
    action: str
    constraints: dict[str, Any] = {}


class RoleIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = ""
    permissions: list[PermissionIn] = []


class PermissionsIn(BaseModel):
    permissions: list[PermissionIn]


class AssignIn(BaseModel):
    membership_id: UUID
    role_id: UUID
    scope: dict[str, list[UUID]] = {}
    expires_at: datetime | None = None


class SubscribeIn(BaseModel):
    plan: str


class ChangePlanIn(BaseModel):
    plan: str


class PayIn(BaseModel):
    payment_method: str = "test_ok"


v1 = APIRouter(prefix="/api/v1")


@v1.get("/health", dependencies=[Depends(public)])
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------- authentication (self-service)
@v1.post("/auth/register", status_code=201, dependencies=[Depends(public)])
def register(b: RegisterIn, ua: UA = None) -> dict[str, Any]:
    return identity.register_tenant(tenant_name=b.tenant_name, slug=b.slug, email=b.email, password=b.password,
                                    display_name=b.display_name, ua=ua)


@v1.post("/auth/login", dependencies=[Depends(public)])
def login(b: LoginIn, ua: UA = None) -> dict[str, Any]:
    return identity.login(tenant_slug=b.tenant_slug, email=b.email, password=b.password, mfa_code=b.mfa_code, ua=ua)


@v1.post("/auth/refresh", dependencies=[Depends(public)])
def refresh(b: RefreshIn) -> dict[str, Any]:
    return identity.refresh(b.refresh_token)


@v1.post("/auth/logout", status_code=204)
def logout(p: Me) -> None:
    identity.logout(p.tenant_id, p.session_id, p.user_id)


@v1.post("/auth/mfa/enroll")
def mfa_enroll(p: Me) -> dict[str, str]:
    return identity.mfa_enroll(p.tenant_id, p.user_id)


@v1.post("/auth/mfa/confirm", status_code=204)
def mfa_confirm(b: CodeIn, p: Me) -> None:
    identity.mfa_confirm(p.tenant_id, p.user_id, b.code)


@v1.post("/auth/accept-invitation", dependencies=[Depends(public)])
def accept(b: AcceptIn, ua: UA = None) -> dict[str, Any]:
    return identity.accept_invitation(b.token, b.password, b.display_name, ua)


@v1.get("/authz/me")
def my_permissions(p: Me) -> dict[str, Any]:
    return {"user_id": str(p.user_id), "tenant_id": str(p.tenant_id), "permissions": authz.effective_permissions(p)}


# ---------------- tenant / users
@v1.get("/tenants/current")
def tenant(a: _need("platform.tenant.settings", "view")) -> dict[str, Any]:  # type: ignore[valid-type]
    return organization.get_tenant(a.p.tenant_id)


@v1.get("/users")
def users(a: _need("platform.users.members", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return identity.list_members(a.p.tenant_id)


@v1.post("/users/invitations", status_code=201)
def invite(b: InviteIn, a: _need("platform.users.invitations", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    return identity.create_invitation(a.p.tenant_id, a.p.user_id, b.email, b.role)


@v1.post("/users/{membership_id}/disable", status_code=204)
def disable(membership_id: UUID, a: _need("platform.users.members", "edit")) -> None:  # type: ignore[valid-type]
    identity.disable_member(a.p.tenant_id, a.p.user_id, membership_id)


# ---------------- organization (scope-aware)
@v1.post("/organizations/companies", status_code=201)
def mk_company(b: CompanyIn, a: _need("platform.org.companies", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    a.require_unrestricted()
    return organization.create_company(a.p.tenant_id, a.p.user_id, b.name, b.legal_name, b.country, b.base_currency)


@v1.get("/organizations/companies")
def ls_companies(a: _need("platform.org.companies", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    hidden = a.hidden_fields()
    return [{k: v for k, v in r.items() if k not in hidden} for r in organization.list_companies(a.p.tenant_id, a.scope())]


@v1.post("/organizations/branches", status_code=201)
def mk_branch(b: BranchIn, a: _need("platform.org.branches", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    a.require_scope(company_id=b.company_id)
    return organization.create_branch(a.p.tenant_id, a.p.user_id, b.company_id, b.name)


@v1.get("/organizations/branches")
def ls_branches(a: _need("platform.org.branches", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return organization.list_branches(a.p.tenant_id, a.scope())


@v1.post("/organizations/departments", status_code=201)
def mk_department(b: DepartmentIn, a: _need("platform.org.departments", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    a.require_scope(company_id=b.company_id, branch_id=b.branch_id)
    return organization.create_department(a.p.tenant_id, a.p.user_id, b.company_id, b.branch_id, b.parent_id, b.name)


@v1.get("/organizations/departments")
def ls_departments(a: _need("platform.org.departments", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return organization.list_departments(a.p.tenant_id, a.scope())


# ---------------- access control
@v1.get("/authz/roles")
def ls_roles(a: _need("platform.authz.roles", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return authz.list_roles(a.p.tenant_id)


@v1.post("/authz/roles", status_code=201)
def mk_role(b: RoleIn, a: _need("platform.authz.roles", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    return authz.create_role(a.p, b.name, b.description, [x.model_dump() for x in b.permissions])


@v1.put("/authz/roles/{role_id}/permissions", status_code=204)
def put_role_perms(role_id: UUID, b: PermissionsIn, a: _need("platform.authz.roles", "manage_permissions")) -> None:  # type: ignore[valid-type]
    authz.replace_role_permissions(a.p, role_id, [x.model_dump() for x in b.permissions])


@v1.delete("/authz/roles/{role_id}", status_code=204)
def rm_role(role_id: UUID, a: _need("platform.authz.roles", "delete")) -> None:  # type: ignore[valid-type]
    authz.delete_role(a.p, role_id)


@v1.get("/authz/assignments")
def ls_assignments(a: _need("platform.authz.assignments", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return authz.list_assignments(a.p.tenant_id)


@v1.post("/authz/assignments", status_code=201)
def mk_assignment(b: AssignIn, a: _need("platform.authz.assignments", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    return authz.assign_role(a.p, b.membership_id, b.role_id, {k: [str(x) for x in v] for k, v in b.scope.items()}, b.expires_at)


@v1.delete("/authz/assignments/{assignment_id}", status_code=204)
def rm_assignment(assignment_id: UUID, a: _need("platform.authz.assignments", "delete")) -> None:  # type: ignore[valid-type]
    authz.unassign_role(a.p, assignment_id)


# ---------------- audit / catalogue
@v1.get("/audit")
def audit_list(a: _need("platform.audit.log", "view"), limit: int = 100) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return organization.audit_list(a.p.tenant_id, limit)


@v1.get("/audit/verify")
def audit_verify(a: _need("platform.audit.log", "view")) -> dict[str, Any]:  # type: ignore[valid-type]
    return organization.audit_verify(a.p.tenant_id)


@v1.get("/registry/catalog")
def catalog(a: _need("platform.registry.catalog", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return registry.catalog()


# ---------------- billing (tenant side)
@v1.get("/billing/plans")
def billing_plans(a: _need("platform.billing.subscription", "view")) -> list[dict[str, Any]]:  # type: ignore[valid-type]
    return billing.list_plans(public_only=True)


@v1.get("/billing/overview")
def billing_overview(a: _need("platform.billing.subscription", "view")) -> dict[str, Any]:  # type: ignore[valid-type]
    return billing.overview(a.p.tenant_id)


@v1.post("/billing/subscriptions", status_code=201)
def billing_subscribe(b: SubscribeIn, a: _need("platform.billing.subscription", "create")) -> dict[str, Any]:  # type: ignore[valid-type]
    return billing.subscribe(a.p.tenant_id, a.p.user_id, b.plan)


@v1.post("/billing/subscriptions/{sub_id}/change-plan")
def billing_change(sub_id: UUID, b: ChangePlanIn, a: _need("platform.billing.subscription", "edit")) -> dict[str, Any]:  # type: ignore[valid-type]
    return billing.change_plan(a.p.tenant_id, a.p.user_id, sub_id, b.plan)


@v1.post("/billing/subscriptions/{sub_id}/cancel", status_code=204)
def billing_cancel(sub_id: UUID, a: _need("platform.billing.subscription", "cancel")) -> None:  # type: ignore[valid-type]
    billing.cancel(a.p.tenant_id, a.p.user_id, sub_id)


@v1.post("/billing/subscriptions/{sub_id}/resume", status_code=204)
def billing_resume(sub_id: UUID, a: _need("platform.billing.subscription", "edit")) -> None:  # type: ignore[valid-type]
    billing.resume(a.p.tenant_id, a.p.user_id, sub_id)


@v1.post("/billing/invoices/{invoice_id}/pay")
def billing_pay(invoice_id: UUID, b: PayIn, a: _need("platform.billing.invoices", "pay"),  # type: ignore[valid-type]
                idempotency_key: Annotated[str | None, Header(alias="idempotency-key")] = None) -> dict[str, Any]:
    try:
        return billing.pay_invoice(a.p.tenant_id, invoice_id, a.p.user_id, b.payment_method, idempotency_key=idempotency_key)
    except NotImplementedError as e:
        raise DomainError(str(e)) from e


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, e: DomainError) -> JSONResponse:
        return JSONResponse({"type": e.code, "title": e.code, "status": e.status, "detail": e.detail},
                            status_code=e.status, media_type="application/problem+json")

    @app.exception_handler(NotImplementedError)
    async def _not_impl(_: Request, e: NotImplementedError) -> JSONResponse:
        return JSONResponse({"type": "not_implemented", "title": "not_implemented", "status": 501, "detail": str(e)},
                            status_code=501, media_type="application/problem+json")

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        return JSONResponse({"type": "invalid", "title": "invalid", "status": 422,
                             "detail": [{"loc": x["loc"], "msg": x["msg"]} for x in e.errors()]},
                            status_code=422, media_type="application/problem+json")


def create_app() -> FastAPI:
    from ueos.api_platform import staff_router

    get_settings().validate_for_runtime()
    app = FastAPI(title="UEOS", version="0.2.0")
    app.include_router(v1)
    app.include_router(staff_router)
    install_handlers(app)
    return app


app = create_app()
