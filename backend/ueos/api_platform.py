"""Platform-staff API (/api/v1/platform/*). Separate realm: staff tokens are rejected by tenant routes and vice versa."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from ueos.platform import assembly, audit, billing, registry, staff
from ueos.platform.db import tx
from ueos.platform.errors import AuthError, Forbidden
from ueos.platform.principal import StaffPrincipal

bearer = HTTPBearer(auto_error=False, scheme_name="staff")


def current_staff(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> StaffPrincipal:
    if creds is None:
        raise AuthError("missing_token")
    sid, _ = staff.decode(creds.credentials)
    role = staff.current_role(sid)  # disabling staff takes effect immediately
    if role is None:
        raise AuthError("session_revoked")
    return StaffPrincipal(sid, role)


def staff_public() -> None:
    return None


def staff_roles(*roles: str) -> Callable[..., StaffPrincipal]:
    def dep(s: Annotated[StaffPrincipal, Depends(current_staff)]) -> StaffPrincipal:
        if s.role not in roles:
            raise Forbidden(f"requires staff role: {', '.join(roles)}")
        return s

    dep.__ueos_access__ = "staff"  # type: ignore[attr-defined]
    return dep


staff_public.__ueos_access__ = "public"  # type: ignore[attr-defined]
current_staff.__ueos_access__ = "staff"  # type: ignore[attr-defined]

REGISTRY_ADMIN = ("super_admin", "registry_admin")
Any_staff = Annotated[StaffPrincipal, Depends(current_staff)]
RegAdmin = Annotated[StaffPrincipal, Depends(staff_roles(*REGISTRY_ADMIN))]
SuperAdmin = Annotated[StaffPrincipal, Depends(staff_roles("super_admin"))]
BillingAdmin = Annotated[StaffPrincipal, Depends(staff_roles("super_admin", "subscription_admin"))]


class StaffLogin(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None


class CodeIn(BaseModel):
    code: str


class SimpleIn(BaseModel):
    slug: str
    name: str
    description: str = ""


class IndustryIn(SimpleIn):
    parent_slug: str | None = None


class AppIn(SimpleIn):
    category: str = "general"
    version: str = "0.1.0"
    status: str = "draft"
    capability_slug: str | None = None


class ModuleIn(SimpleIn):
    application_slug: str


class SubmoduleIn(SimpleIn):
    application_slug: str
    module_slug: str


class FeatureIn(SimpleIn):
    application_slug: str
    module_slug: str
    submodule_slug: str | None = None
    actions: list[str] = Field(min_length=1)
    depends_on: list[str] = []
    sensitive: bool = False
    audited: bool = True
    default_tier: str = "standard"


class StatusIn(BaseModel):
    status: str


class EntitlementIn(BaseModel):
    feature_key: str
    expires_at: datetime | None = None
    limits: dict[str, Any] = {}


class TenantStatusIn(BaseModel):
    status: str


class PlanIn(BaseModel):
    slug: str
    name: str
    description: str = ""
    kind: str = "base"
    billing_period: str = "monthly"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    base_price: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    per_user_price: Decimal = Field(default=Decimal(0), ge=0, max_digits=12, decimal_places=2)
    trial_days: int = Field(default=0, ge=0, le=365)
    is_default: bool = False
    is_public: bool = True
    features: list[str] = []
    limits: dict[str, int | None] = {}


class PlanItemsIn(BaseModel):
    features: list[str] = []
    limits: dict[str, int | None] = {}


class AssignPlanIn(BaseModel):
    plan: str
    comped: bool = False


class MarkPaidIn(BaseModel):
    reference: str = Field(min_length=1, max_length=80)


class BillingRunIn(BaseModel):
    as_of: datetime | None = None  # simulation clock — accepted only in dev/test environments


class TemplateIn(BaseModel):
    industry: str
    slug: str
    name: str
    parent: str | None = None
    config: dict[str, Any] = {}


class ConfigIn(BaseModel):
    config: dict[str, Any]


class ProductIn(BaseModel):
    slug: str
    name: str
    description: str = ""
    industry: str | None = None
    business_models: list[str] = []


class CompositionIn(BaseModel):
    composition: dict[str, Any]


staff_router = APIRouter(prefix="/api/v1/platform")


@staff_router.post("/auth/login", dependencies=[Depends(staff_public)])
def staff_login(b: StaffLogin) -> dict[str, Any]:
    return staff.login(b.email, b.password, b.mfa_code)


@staff_router.post("/auth/mfa/enroll")
def staff_mfa_enroll(s: Any_staff) -> dict[str, str]:
    return staff.mfa_enroll(s.staff_id)


@staff_router.post("/auth/mfa/confirm", status_code=204)
def staff_mfa_confirm(b: CodeIn, s: Any_staff) -> None:
    staff.mfa_confirm(s.staff_id, b.code)


# ---------------- registry administration
def _audited(s: StaffPrincipal, action: str, entity: str, ident: str | None, data: dict[str, Any]) -> None:
    with tx(None) as c:
        audit.record_platform(c, s.staff_id, action, entity, None, {"id": ident, **data})


@staff_router.post("/registry/sync")
def sync(s: RegAdmin) -> dict[str, int]:
    rep = registry.sync_manifests()
    _audited(s, "registry.synced", "registry", None, rep)
    return rep


@staff_router.get("/registry/{kind}")
def reg_list(kind: str, s: Any_staff) -> list[dict[str, Any]]:
    return registry.list_kind(kind)


@staff_router.post("/registry/capabilities", status_code=201)
def mk_cap(b: SimpleIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_simple("capability_domains", b.slug, b.name, b.description)
    _audited(s, "registry.capability_created", "capability", b.slug, {})
    return r


@staff_router.post("/registry/business-models", status_code=201)
def mk_bm(b: SimpleIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_simple("business_models", b.slug, b.name, b.description)
    _audited(s, "registry.business_model_created", "business_model", b.slug, {})
    return r


@staff_router.post("/registry/industries", status_code=201)
def mk_industry(b: IndustryIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_industry(b.slug, b.name, b.description, b.parent_slug)
    _audited(s, "registry.industry_created", "industry", b.slug, {"parent": b.parent_slug})
    return r


@staff_router.post("/registry/applications", status_code=201)
def mk_app(b: AppIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_application(b.slug, b.name, b.description, b.category, b.version, b.status, b.capability_slug)
    _audited(s, "registry.application_created", "application", b.slug, {})
    return r


@staff_router.post("/registry/modules", status_code=201)
def mk_module(b: ModuleIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_module(b.application_slug, b.slug, b.name, b.description)
    _audited(s, "registry.module_created", "module", f"{b.application_slug}.{b.slug}", {})
    return r


@staff_router.post("/registry/submodules", status_code=201)
def mk_submodule(b: SubmoduleIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_submodule(b.application_slug, b.module_slug, b.slug, b.name, b.description)
    _audited(s, "registry.submodule_created", "submodule", f"{b.application_slug}.{b.module_slug}.{b.slug}", {})
    return r


@staff_router.post("/registry/features", status_code=201)
def mk_feature(b: FeatureIn, s: RegAdmin) -> dict[str, Any]:
    r = registry.create_feature(b.application_slug, b.module_slug, b.submodule_slug, b.slug, b.name, b.description,
                                b.actions, b.depends_on, b.sensitive, b.audited, b.default_tier)
    _audited(s, "registry.feature_created", "feature", r["key"], {})
    return r


@staff_router.patch("/registry/{kind}/{ident}", status_code=204)
def reg_status(kind: str, ident: str, b: StatusIn, s: RegAdmin) -> None:
    registry.set_status(kind, ident, b.status)
    _audited(s, "registry.status_changed", kind, ident, {"status": b.status})


# ---------------- tenants (metadata only — no business data)
@staff_router.get("/tenants")
def tenants(s: Any_staff) -> list[dict[str, Any]]:
    return staff.list_tenants()


@staff_router.post("/tenants/{tenant_id}/status", status_code=204)
def tenant_status(tenant_id: UUID, b: TenantStatusIn, s: SuperAdmin) -> None:
    staff.set_tenant_status(s.staff_id, tenant_id, b.status)


@staff_router.get("/tenants/{tenant_id}/entitlements")
def ent_list(tenant_id: UUID, s: Any_staff) -> list[dict[str, Any]]:
    return staff.list_entitlements(tenant_id)


@staff_router.post("/tenants/{tenant_id}/entitlements", status_code=204)
def ent_grant(tenant_id: UUID, b: EntitlementIn, s: SuperAdmin) -> None:
    staff.grant_entitlement(s.staff_id, tenant_id, b.feature_key, b.expires_at, b.limits)


@staff_router.delete("/tenants/{tenant_id}/entitlements", status_code=204)
def ent_revoke(tenant_id: UUID, feature_key: str, s: SuperAdmin) -> None:
    staff.revoke_entitlement(s.staff_id, tenant_id, feature_key)


@staff_router.get("/audit/verify")
def platform_audit_verify(s: Any_staff) -> dict[str, Any]:
    with tx(None) as c:
        return audit.verify_platform(c)


# ---------------- plans & billing
@staff_router.get("/plans")
def plans(s: Any_staff) -> list[dict[str, Any]]:
    return billing.list_plans(public_only=False)


@staff_router.post("/plans", status_code=201)
def mk_plan(b: PlanIn, s: BillingAdmin) -> dict[str, Any]:
    return billing.create_plan(s.staff_id, b.model_dump())


@staff_router.put("/plans/{plan_id}/items", status_code=204)
def plan_items(plan_id: UUID, b: PlanItemsIn, s: BillingAdmin) -> None:
    billing.replace_plan_items(s.staff_id, plan_id, b.features, b.limits)


@staff_router.patch("/plans/{plan_id}/status", status_code=204)
def plan_status(plan_id: UUID, b: StatusIn, s: BillingAdmin) -> None:
    billing.set_plan_status(s.staff_id, plan_id, b.status)


@staff_router.get("/subscriptions")
def all_subscriptions(s: Any_staff) -> list[dict[str, Any]]:
    return billing.list_all_subscriptions()


@staff_router.post("/tenants/{tenant_id}/subscriptions", status_code=201)
def assign_plan(tenant_id: UUID, b: AssignPlanIn, s: BillingAdmin) -> dict[str, Any]:
    return billing.staff_assign(s.staff_id, tenant_id, b.plan, b.comped)


@staff_router.post("/tenants/{tenant_id}/invoices/{invoice_id}/mark-paid")
def mark_paid(tenant_id: UUID, invoice_id: UUID, b: MarkPaidIn, s: BillingAdmin) -> dict[str, Any]:
    r = billing.pay_invoice(tenant_id, invoice_id, None, b.reference, provider="manual")
    with tx(tenant_id) as c:
        audit.record_platform(c, s.staff_id, "invoice.marked_paid", "invoice", invoice_id, {"reference": b.reference})
    return r


@staff_router.post("/billing/run")
def billing_run(b: BillingRunIn, s: BillingAdmin) -> dict[str, int]:
    from ueos.platform.config import get_settings

    if b.as_of and get_settings().env not in ("dev", "test"):
        raise Forbidden("as_of is only available in dev/test environments")
    rep = billing.run_billing(b.as_of)
    with tx(None) as c:
        audit.record_platform(c, s.staff_id, "billing.run", data=rep)
    return rep


# ---------------- industry templates & products (assembly)
@staff_router.get("/templates")
def tpl_list(s: Any_staff) -> list[dict[str, Any]]:
    return assembly.list_templates(published_only=False)


@staff_router.post("/templates", status_code=201)
def tpl_create(b: TemplateIn, s: RegAdmin) -> dict[str, Any]:
    return assembly.create_template(s.staff_id, b.industry, b.slug, b.name, b.parent, b.config)


@staff_router.put("/templates/{template_id}/config", status_code=204)
def tpl_config(template_id: UUID, b: ConfigIn, s: RegAdmin) -> None:
    assembly.update_template_config(s.staff_id, template_id, b.config)


@staff_router.patch("/templates/{template_id}/status", status_code=204)
def tpl_status(template_id: UUID, b: StatusIn, s: RegAdmin) -> None:
    assembly.set_template_status(s.staff_id, template_id, b.status)


@staff_router.post("/templates/{slug}/versions", status_code=201)
def tpl_version(slug: str, s: RegAdmin) -> dict[str, Any]:
    return assembly.new_template_version(s.staff_id, slug)


@staff_router.get("/templates/{slug}/resolved")
def tpl_resolved(slug: str, s: Any_staff) -> dict[str, Any]:
    return assembly.preview_template(slug, published_only=False)


@staff_router.get("/products")
def prod_list(s: Any_staff) -> list[dict[str, Any]]:
    return assembly.list_products(published_only=False)


@staff_router.post("/products", status_code=201)
def prod_create(b: ProductIn, s: RegAdmin) -> dict[str, Any]:
    return assembly.create_product(s.staff_id, b.slug, b.name, b.description, b.industry, b.business_models)


@staff_router.put("/products/{slug}/versions/{version}/composition")
def prod_composition(slug: str, version: int, b: CompositionIn, s: RegAdmin) -> dict[str, Any]:
    return assembly.set_composition(s.staff_id, slug, version, b.composition)


@staff_router.post("/products/{slug}/versions/{version}/test")
def prod_test(slug: str, version: int, s: Any_staff) -> dict[str, Any]:
    return assembly.test_composition(slug, version)


@staff_router.post("/products/{slug}/versions/{version}/publish", status_code=204)
def prod_publish(slug: str, version: int, s: RegAdmin) -> None:
    assembly.publish_version(s.staff_id, slug, version)


@staff_router.post("/products/{slug}/versions", status_code=201)
def prod_new_version(slug: str, s: RegAdmin) -> dict[str, Any]:
    return assembly.new_product_version(s.staff_id, slug)
