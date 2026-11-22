"""Configuration & assembly engine (PRD Phase 5 / Software Builder).

- Industry templates: versioned JSON, inheritance via `parent`, resolution with provenance (which template set each value, what was overridden).
- Applying a template copies resolved configuration into *tenant-owned* rows. Existing tenant rows are never overwritten, so
  template updates and re-applying cannot destroy tenant customisation (requirement 4415).
- Modules: activation per tenant with automatic dependency resolution and conflict prevention.
- Products (software editions): a versioned composition of registry modules + template + branding. Nothing is duplicated.
- Navigation is derived from: published apps + activated modules + entitlements + the user's permissions.
- Custom fields / terminology / dashboards are tenant configuration (config before code).
"""

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from ueos.platform import audit, authz, registry
from ueos.platform.db import tx
from ueos.platform.errors import Conflict, Invalid, NotFound
from ueos.platform.principal import Principal

SLUG = re.compile(r"^[a-z][a-z0-9_]*$")
LIST_KEYS = ("business_models", "applications", "modules", "recommended_plans", "compliance", "workflows")
TEMPLATE_KEYS = {*LIST_KEYS, "custom_fields", "terminology", "roles", "dashboards"}
FIELD_TYPES = ("text", "number", "date", "boolean", "select")
KNOWN_ENTITIES = ("platform.company",)
WIDGETS = {  # widget source -> (feature key that must be viewable, table, scope columns)
    "companies": ("platform.org.companies", "companies", {"company": "id"}),
    "branches": ("platform.org.branches", "branches", {"company": "company_id", "branch": "id"}),
    "departments": ("platform.org.departments", "departments", {"company": "company_id", "branch": "branch_id", "department": "id"}),
    "members": ("platform.users.members", "memberships", {}),
}


def _j(x: Any) -> str:
    return json.dumps(x, default=str, sort_keys=True)


# ------------------------------------------------------------------ module / dependency helpers
def _module_key_of(feature_key: str) -> str:
    return ".".join(feature_key.split(".")[:2])


def _module_exists(c: Connection, key: str) -> bool:
    app, _, mod = key.partition(".")
    return bool(c.execute(text("select 1 from platform.modules m join platform.applications a on a.id=m.application_id"
                               " where a.slug=:a and m.slug=:m and a.status='published' and m.status='active'"), {"a": app, "m": mod}).first())


def _features(c: Connection, module_key: str) -> list[Any]:
    app, _, mod = module_key.partition(".")
    return list(c.execute(text("select f.key, f.depends_on, f.conflicts_with, f.actions, f.name, f.status from platform.features f"
                               " join platform.applications a on a.id=f.application_id join platform.modules m on m.id=f.module_id"
                               " where a.slug=:a and m.slug=:m and f.status<>'deprecated' order by f.key"), {"a": app, "m": mod}).all())


def plan_modules(c: Connection, wanted: set[str], active: set[str], auto_deps: bool) -> dict[str, Any]:
    """Resolve dependencies and detect conflicts. Returns {final, added, missing, conflicts}."""
    final = set(wanted)
    added: set[str] = set()
    missing: dict[str, set[str]] = {}
    for m in wanted:
        if m.split(".")[0] == "platform" or not _module_exists(c, m):
            raise Invalid(f"unknown or unavailable module '{m}'")
    changed = True
    while changed:
        changed = False
        for m in sorted(final):
            for f in _features(c, m):
                for dep in f.depends_on:
                    dm = _module_key_of(dep)
                    if dm.split(".")[0] == "platform" or dm in final or dm in active or dm == m:
                        continue
                    if auto_deps:
                        if not _module_exists(c, dm):
                            raise Invalid(f"dependency '{dep}' is not available")
                        final.add(dm)
                        added.add(dm)
                        changed = True
                    else:
                        missing.setdefault(m, set()).add(dm)
    universe = final | active
    conflicts: list[str] = []
    feats: dict[str, Any] = {}
    for m in universe:
        for f in _features(c, m):
            feats[f.key] = f
    for k, f in feats.items():
        for other in f.conflicts_with:
            if other in feats and _module_key_of(other) != _module_key_of(k):
                conflicts.append(f"{k} conflicts with {other}")
    return {"final": final, "added": sorted(added), "missing": {k: sorted(v) for k, v in missing.items()}, "conflicts": sorted(set(conflicts))}


def _active(c: Connection) -> set[str]:
    return {f"{r.application_slug}.{r.module_slug}" for r in c.execute(text("select application_slug, module_slug from platform.tenant_modules")).all()}


def _insert_modules(c: Connection, tenant_id: UUID, keys: list[str], source: str) -> list[str]:
    done = []
    for k in keys:
        app, _, mod = k.partition(".")
        n = c.execute(text("insert into platform.tenant_modules (id, tenant_id, application_slug, module_slug, source) values (:i,:t,:a,:m,:s)"
                           " on conflict (tenant_id, application_slug, module_slug) do nothing"),
                      {"i": uuid4(), "t": tenant_id, "a": app, "m": mod, "s": source}).rowcount
        if n:
            done.append(k)
    return done


def _not_entitled(c: Connection, modules: list[str]) -> list[str]:
    out = []
    for m in modules:
        fs = _features(c, m)
        if fs and not authz.entitled(c, fs[0].key):
            out.append(m)
    return out


def activate_modules(p: Principal, modules: list[str], with_dependencies: bool, source: str = "tenant") -> dict[str, Any]:
    with tx(p.tenant_id) as c:
        plan = plan_modules(c, set(modules), _active(c), with_dependencies)
        if plan["missing"]:
            raise Invalid("missing dependencies: " + "; ".join(f"{m} needs {', '.join(d)}" for m, d in plan["missing"].items()))
        if plan["conflicts"]:
            raise Invalid("incompatible combination: " + "; ".join(plan["conflicts"]))
        activated = _insert_modules(c, p.tenant_id, sorted(plan["final"]), source)
        audit.record(c, p.tenant_id, p.user_id, "modules.activated", data={"modules": activated, "added_dependencies": plan["added"]})
        return {"activated": activated, "added_dependencies": plan["added"], "not_entitled": _not_entitled(c, activated)}


def deactivate_module(p: Principal, module: str) -> None:
    with tx(p.tenant_id) as c:
        active = _active(c)
        if module not in active:
            raise NotFound("module is not active")
        keys = {f.key for f in _features(c, module)}
        blockers = sorted(m for m in active - {module} for f in _features(c, m) if keys & set(f.depends_on))
        if blockers:
            raise Invalid(f"required by active modules: {', '.join(sorted(set(blockers)))}")
        app, _, mod = module.partition(".")
        c.execute(text("delete from platform.tenant_modules where application_slug=:a and module_slug=:m"), {"a": app, "m": mod})
        audit.record(c, p.tenant_id, p.user_id, "modules.deactivated", data={"module": module})


def module_catalog(tenant_id: UUID) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        active = _active(c)
        out = []
        for a in c.execute(text("select id, slug, name from platform.applications where status='published' and slug<>'platform' order by slug")).all():
            mods = []
            for m in c.execute(text("select slug, name from platform.modules where application_id=:a and status='active' order by slug"), {"a": a.id}).all():
                key = f"{a.slug}.{m.slug}"
                fs = _features(c, key)
                dep_mods = {_module_key_of(d) for f in fs for d in f.depends_on}
                deps = sorted(x for x in dep_mods if x != key and not x.startswith("platform."))
                mods.append({"key": key, "name": m.name, "features": len(fs), "active": key in active, "depends_on_modules": deps,
                             "entitled": bool(fs) and authz.entitled(c, fs[0].key)})
            if mods:
                out.append({"slug": a.slug, "name": a.name, "modules": mods})
        return out


# ------------------------------------------------------------------ templates (staff)
def validate_template_config(c: Connection, cfg: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(cfg, dict):
        raise Invalid("config must be an object")
    bad = set(cfg) - TEMPLATE_KEYS
    if bad:
        raise Invalid(f"unknown template keys: {sorted(bad)} (allowed: {sorted(TEMPLATE_KEYS)})")
    out: dict[str, Any] = {}
    for k in LIST_KEYS:
        v = cfg.get(k, [])
        if not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise Invalid(f"{k} must be a list of strings")
        out[k] = list(dict.fromkeys(v))
    for a in out["applications"]:
        if not c.execute(text("select 1 from platform.applications where slug=:s and status='published'"), {"s": a}).first():
            raise Invalid(f"unknown or unpublished application '{a}'")
    for m in out["modules"]:
        if not _module_exists(c, m):
            raise Invalid(f"unknown module '{m}' (use app.module)")
    for b in out["business_models"]:
        if not c.execute(text("select 1 from platform.business_models where slug=:s"), {"s": b}).first():
            raise Invalid(f"unknown business model '{b}'")
    for pl in out["recommended_plans"]:
        if not c.execute(text("select 1 from platform.plans where slug=:s"), {"s": pl}).first():
            raise Invalid(f"unknown plan '{pl}'")
    fields = cfg.get("custom_fields", [])
    for f in fields:
        _check_field_def(f)
    out["custom_fields"] = fields
    term = cfg.get("terminology", {})
    if not (isinstance(term, dict) and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in term.items())):
        raise Invalid("terminology must map term -> label")
    out["terminology"] = term
    roles = cfg.get("roles", [])
    for r in roles:
        if not (isinstance(r, dict) and isinstance(r.get("name"), str) and len(r["name"]) >= 2 and isinstance(r.get("permissions", []), list)):
            raise Invalid("each role needs a name and a permissions list")
        for pm in r.get("permissions", []):
            registry.validate_permission(c, pm.get("feature_key", ""), pm.get("action", ""))
            authz._check_constraints(pm.get("constraints") or {})
    out["roles"] = roles
    dashboards = cfg.get("dashboards", [])
    for d in dashboards:
        if not (isinstance(d, dict) and isinstance(d.get("name"), str) and isinstance(d.get("widgets", []), list)):
            raise Invalid("each dashboard needs a name and widgets")
        for w in d["widgets"]:
            if w.get("type") != "count" or w.get("source") not in WIDGETS:
                raise Invalid(f"widget must be type 'count' with source in {sorted(WIDGETS)}")
    out["dashboards"] = dashboards
    return out


def _check_field_def(f: dict[str, Any]) -> None:
    if not (isinstance(f, dict) and f.get("entity") in KNOWN_ENTITIES and SLUG.match(str(f.get("key", ""))) and f.get("label")):
        raise Invalid(f"custom field needs entity (one of {KNOWN_ENTITIES}), a slug key and a label")
    if f.get("type") not in FIELD_TYPES:
        raise Invalid(f"field type must be one of {FIELD_TYPES}")
    if f["type"] == "select" and not (isinstance(f.get("options"), list) and f["options"] and all(isinstance(o, str) for o in f["options"])):
        raise Invalid("select fields need a non-empty options list")


def _template_row(c: Connection, slug: str, version: int | None = None, published_only: bool = True) -> Any:
    q = "select t.*, i.slug as industry_slug from platform.industry_templates t join platform.industries i on i.id=t.industry_id where t.slug=:s"
    if version:
        q += " and t.version=:v"
    elif published_only:
        q += " and t.status='published'"
    row = c.execute(text(q + " order by t.version desc limit 1"), {"s": slug, "v": version}).first()
    if not row:
        raise NotFound(f"template '{slug}' not found")
    return row


def _tpl_dict(r: Any) -> dict[str, Any]:
    return {"id": str(r.id), "slug": r.slug, "name": r.name, "version": r.version, "status": r.status, "industry": r.industry_slug,
            "parent_id": str(r.parent_id) if r.parent_id else None, "config": r.config}


def create_template(staff_id: UUID, industry_slug: str, slug: str, name: str, parent_slug: str | None, cfg: dict[str, Any]) -> dict[str, Any]:
    if not SLUG.match(slug):
        raise Invalid("invalid slug")
    tid = uuid4()
    with tx(None) as c:
        ind = c.execute(text("select id from platform.industries where slug=:s"), {"s": industry_slug}).scalar()
        if not ind:
            raise NotFound(f"industry '{industry_slug}' not found")
        if c.execute(text("select 1 from platform.industry_templates where slug=:s"), {"s": slug}).first():
            raise Conflict("template slug already exists (create a new version instead)")
        parent = _template_row(c, parent_slug).id if parent_slug else None
        norm = validate_template_config(c, cfg)
        c.execute(text("insert into platform.industry_templates (id, industry_id, slug, name, version, parent_id, config)"
                       " values (:i,:ind,:s,:n,1,:p,cast(:c as jsonb))"), {"i": tid, "ind": ind, "s": slug, "n": name, "p": parent, "c": _j(norm)})
        audit.record_platform(c, staff_id, "template.created", "template", tid, {"slug": slug, "parent": parent_slug})
    return {"id": str(tid), "slug": slug, "version": 1}


def update_template_config(staff_id: UUID, template_id: UUID, cfg: dict[str, Any]) -> None:
    with tx(None) as c:
        st = c.execute(text("select status from platform.industry_templates where id=:i"), {"i": template_id}).scalar()
        if st is None:
            raise NotFound("template not found")
        if st != "draft":
            raise Conflict("only draft template versions can be edited; create a new version")
        c.execute(text("update platform.industry_templates set config=cast(:c as jsonb) where id=:i"),
                  {"c": _j(validate_template_config(c, cfg)), "i": template_id})
        audit.record_platform(c, staff_id, "template.config_updated", "template", template_id)


def set_template_status(staff_id: UUID, template_id: UUID, status: str) -> None:
    allowed = {"draft": ("published",), "published": ("deprecated",), "deprecated": ()}
    with tx(None) as c:
        st = c.execute(text("select status from platform.industry_templates where id=:i"), {"i": template_id}).scalar()
        if st is None:
            raise NotFound("template not found")
        if status not in allowed[st]:
            raise Invalid(f"cannot move a {st} template to {status}")
        c.execute(text("update platform.industry_templates set status=:s where id=:i"), {"s": status, "i": template_id})
        audit.record_platform(c, staff_id, "template.status_changed", "template", template_id, {"status": status})


def new_template_version(staff_id: UUID, slug: str) -> dict[str, Any]:
    with tx(None) as c:
        last = _template_row(c, slug, published_only=False)
        if c.execute(text("select 1 from platform.industry_templates where slug=:s and status='draft'"), {"s": slug}).first():
            raise Conflict("a draft version already exists")
        tid = uuid4()
        c.execute(text("insert into platform.industry_templates (id, industry_id, slug, name, version, parent_id, config)"
                       " values (:i,:ind,:s,:n,:v,:p,cast(:c as jsonb))"),
                  {"i": tid, "ind": last.industry_id, "s": slug, "n": last.name, "v": last.version + 1, "p": last.parent_id, "c": _j(last.config)})
        audit.record_platform(c, staff_id, "template.version_created", "template", tid, {"slug": slug, "version": last.version + 1})
    return {"id": str(tid), "slug": slug, "version": last.version + 1}


def list_templates(published_only: bool) -> list[dict[str, Any]]:
    with tx(None) as c:
        where = "where t.status='published'" if published_only else ""
        rows = c.execute(text("select t.*, i.slug as industry_slug from platform.industry_templates t join platform.industries i on i.id=t.industry_id"
                              f" {where} order by t.slug, t.version desc")).all()
        if published_only:  # only the latest published version of each slug
            seen: set[str] = set()
            rows = [r for r in rows if not (r.slug in seen or seen.add(r.slug))]  # type: ignore[func-returns-value]
        return [_tpl_dict(r) for r in rows]


def resolve(c: Connection, slug: str, version: int | None = None) -> dict[str, Any]:
    """Merge the inheritance chain (root first). Returns {config, provenance, overrides, chain}."""
    row = _template_row(c, slug, version)
    chain = [row]
    seen = {row.id}
    while chain[-1].parent_id:
        parent = c.execute(text("select t.*, i.slug as industry_slug from platform.industry_templates t join platform.industries i on i.id=t.industry_id"
                                " where t.id=:i"), {"i": chain[-1].parent_id}).first()
        if not parent or parent.id in seen or len(chain) > 10:
            raise Invalid("invalid template inheritance chain")
        seen.add(parent.id)
        chain.append(parent)
    chain.reverse()
    cfg: dict[str, Any] = {k: [] for k in LIST_KEYS}
    cfg.update({"custom_fields": [], "terminology": {}, "roles": [], "dashboards": []})
    prov: dict[str, str] = {}
    overrides: list[dict[str, str]] = []

    def put(path: str, src: str) -> None:
        if path in prov and prov[path] != src:
            overrides.append({"path": path, "from": prov[path], "by": src})
        prov[path] = src

    for t in chain:
        src = f"{t.slug}@{t.version}"
        for k in LIST_KEYS:
            for item in t.config.get(k, []):
                if item not in cfg[k]:
                    cfg[k].append(item)
                    prov[f"{k}:{item}"] = src
        for f in t.config.get("custom_fields", []):
            path = f"custom_fields:{f['entity']}.{f['key']}"
            cfg["custom_fields"] = [x for x in cfg["custom_fields"] if (x["entity"], x["key"]) != (f["entity"], f["key"])] + [f]
            put(path, src)
        for term, label in t.config.get("terminology", {}).items():
            cfg["terminology"][term] = label
            put(f"terminology:{term}", src)
        for key, coll in (("roles", "name"), ("dashboards", "name")):
            for item in t.config.get(key, []):
                cfg[key] = [x for x in cfg[key] if x[coll] != item[coll]] + [item]
                put(f"{key}:{item[coll]}", src)
    return {"slug": slug, "version": row.version, "config": cfg, "provenance": prov, "overrides": overrides,
            "chain": [f"{t.slug}@{t.version}" for t in chain]}


def preview_template(slug: str, published_only: bool = True) -> dict[str, Any]:
    with tx(None) as c:
        row = _template_row(c, slug, published_only=published_only)
        return resolve(c, slug, row.version)


# ------------------------------------------------------------------ apply template to a tenant (never overwrites tenant-owned rows)
def _apply_template(c: Connection, p: Principal, slug: str, version: int | None, source_prefix: str = "template") -> dict[str, Any]:
    res = resolve(c, slug, version)
    cfg, src = res["config"], f"{source_prefix}:{slug}@{res['version']}"
    wanted = set(cfg["modules"])
    for app in cfg["applications"]:
        for m in c.execute(text("select m.slug from platform.modules m join platform.applications a on a.id=m.application_id"
                                " where a.slug=:a and m.status='active'"), {"a": app}).all():
            wanted.add(f"{app}.{m.slug}")
    wanted = {m for m in wanted if m.split(".")[0] != "platform"}
    plan = plan_modules(c, wanted, _active(c), auto_deps=True)
    if plan["conflicts"]:
        raise Invalid("incompatible combination: " + "; ".join(plan["conflicts"]))
    activated = _insert_modules(c, p.tenant_id, sorted(plan["final"]), src)
    created: dict[str, list[str]] = {"custom_fields": [], "terminology": [], "dashboards": [], "roles": []}
    skipped: dict[str, list[str]] = {"custom_fields": [], "terminology": [], "dashboards": [], "roles": []}
    for i, f in enumerate(cfg["custom_fields"]):
        n = c.execute(text("insert into platform.tenant_custom_fields (id, tenant_id, entity, key, label, type, required, options, sort, source)"
                           " values (:i,:t,:e,:k,:l,:ty,:r,cast(:o as jsonb),:s,:src) on conflict (tenant_id, entity, key) do nothing"),
                      {"i": uuid4(), "t": p.tenant_id, "e": f["entity"], "k": f["key"], "l": f["label"], "ty": f["type"],
                       "r": bool(f.get("required")), "o": _j(f.get("options", [])), "s": i, "src": src}).rowcount
        (created if n else skipped)["custom_fields"].append(f"{f['entity']}.{f['key']}")
    for term, label in cfg["terminology"].items():
        n = c.execute(text("insert into platform.tenant_terminology (id, tenant_id, term, label, source) values (:i,:t,:k,:l,:s)"
                           " on conflict (tenant_id, term) do nothing"), {"i": uuid4(), "t": p.tenant_id, "k": term, "l": label, "s": src}).rowcount
        (created if n else skipped)["terminology"].append(term)
    for d in cfg["dashboards"]:
        n = c.execute(text("insert into platform.tenant_dashboards (id, tenant_id, name, config, source) values (:i,:t,:n,cast(:c as jsonb),:s)"
                           " on conflict (tenant_id, name) do nothing"), {"i": uuid4(), "t": p.tenant_id, "n": d["name"], "c": _j(d), "s": src}).rowcount
        (created if n else skipped)["dashboards"].append(d["name"])
    actor_grants = authz.load_grants(c, p.membership_id)
    for r in cfg["roles"]:
        if c.execute(text("select 1 from platform.roles where name=:n"), {"n": r["name"]}).first():
            skipped["roles"].append(r["name"])
            continue
        rid = uuid4()
        c.execute(text("insert into platform.roles (id, tenant_id, name, description) values (:i,:t,:n,:d)"),
                  {"i": rid, "t": p.tenant_id, "n": r["name"], "d": r.get("description", f"From template {slug}")})
        for pm in r.get("permissions", []):  # a template can never grant the applier more than they hold
            authz._escalation_guard(actor_grants, pm["feature_key"], pm["action"], pm.get("constraints") or {})
            c.execute(text("insert into platform.role_permissions (id, tenant_id, role_id, feature_key, action, constraints)"
                           " values (:i,:t,:r,:k,:a,cast(:c as jsonb))"),
                      {"i": uuid4(), "t": p.tenant_id, "r": rid, "k": pm["feature_key"], "a": pm["action"], "c": _j(pm.get("constraints") or {})})
        created["roles"].append(r["name"])
    result = {"activated_modules": activated, "added_dependencies": plan["added"], "created": created, "skipped_existing": skipped,
              "not_entitled": _not_entitled(c, activated), "recommended_plans": cfg["recommended_plans"], "chain": res["chain"]}
    c.execute(text("insert into platform.tenant_template_applications (id, tenant_id, template_slug, template_version, resolved, provenance, result, applied_by)"
                   " values (:i,:t,:s,:v,cast(:r as jsonb),cast(:p as jsonb),cast(:x as jsonb),:b)"),
              {"i": uuid4(), "t": p.tenant_id, "s": slug, "v": res["version"], "r": _j(cfg), "p": _j(res["provenance"]), "x": _j(result), "b": p.user_id})
    c.execute(text("insert into platform.tenant_settings (tenant_id, applied_template, applied_template_version) values (:t,:s,:v)"
                   " on conflict (tenant_id) do update set applied_template=:s, applied_template_version=:v, updated_at=now()"),
              {"t": p.tenant_id, "s": slug, "v": res["version"]})
    audit.record(c, p.tenant_id, p.user_id, "template.applied", data={"template": f"{slug}@{res['version']}", **{k: len(v) for k, v in created.items()}})
    return result


def apply_template(p: Principal, slug: str, version: int | None = None) -> dict[str, Any]:
    with tx(p.tenant_id) as c:
        return _apply_template(c, p, slug, version)


# ------------------------------------------------------------------ products (software editions)
def _validate_composition(c: Connection, comp: dict[str, Any]) -> dict[str, Any]:
    bad = set(comp) - {"modules", "template", "branding", "plans"}
    if bad:
        raise Invalid(f"unknown composition keys: {sorted(bad)}")
    mods = comp.get("modules", [])
    if not (isinstance(mods, list) and all(isinstance(m, str) for m in mods)):
        raise Invalid("modules must be a list of app.module keys")
    plan = plan_modules(c, set(mods), set(), auto_deps=True)
    if plan["conflicts"]:
        raise Invalid("incompatible combination: " + "; ".join(plan["conflicts"]))
    tpl = comp.get("template")
    if tpl:
        _template_row(c, tpl)
    plans = comp.get("plans", [])
    for pl in plans:
        if not c.execute(text("select 1 from platform.plans where slug=:s"), {"s": pl}).first():
            raise Invalid(f"unknown plan '{pl}'")
    br = comp.get("branding", {})
    if not isinstance(br, dict) or set(br) - {"name", "primary_color", "logo_url"}:
        raise Invalid("branding allows: name, primary_color, logo_url")
    if br.get("primary_color") and not re.fullmatch(r"#[0-9a-fA-F]{6}", br["primary_color"]):
        raise Invalid("primary_color must be #RRGGBB")
    warnings: list[str] = []
    if plans:  # product test: every feature must be sellable through at least one recommended plan
        patterns = [r.feature_pattern for r in c.execute(text(
            "select pi.feature_pattern from platform.plan_items pi join platform.plans p on p.id=pi.plan_id"
            " where p.slug = any(cast(:s as text[])) and pi.kind='feature'"), {"s": plans}).all()]
        for m in sorted(plan["final"]):
            for f in _features(c, m):
                if not any(authz.matches(pt, f.key) for pt in patterns):
                    warnings.append(f"feature {f.key} is not covered by any recommended plan")
    return {"modules": sorted(plan["final"]), "added_dependencies": plan["added"], "template": tpl, "plans": plans, "branding": br,
            "warnings": warnings}


def create_product(staff_id: UUID, slug: str, name: str, description: str, industry_slug: str | None, business_models: list[str]) -> dict[str, Any]:
    if not SLUG.match(slug):
        raise Invalid("invalid slug")
    pid = uuid4()
    with tx(None) as c:
        if industry_slug and not c.execute(text("select 1 from platform.industries where slug=:s"), {"s": industry_slug}).first():
            raise NotFound(f"industry '{industry_slug}' not found")
        for b in business_models:
            if not c.execute(text("select 1 from platform.business_models where slug=:s"), {"s": b}).first():
                raise Invalid(f"unknown business model '{b}'")
        try:
            with c.begin_nested():
                c.execute(text("insert into platform.products (id, slug, name, description, industry_slug, business_models) values (:i,:s,:n,:d,:ind,:bm)"),
                          {"i": pid, "s": slug, "n": name, "d": description, "ind": industry_slug, "bm": business_models})
        except Exception as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("product slug already exists") from e
            raise
        c.execute(text("insert into platform.product_versions (id, product_id, version) values (:i,:p,1)"), {"i": uuid4(), "p": pid})
        audit.record_platform(c, staff_id, "product.created", "product", pid, {"slug": slug})
    return {"id": str(pid), "slug": slug, "version": 1}


def _version_row(c: Connection, slug: str, version: int) -> Any:
    r = c.execute(text("select v.*, p.slug from platform.product_versions v join platform.products p on p.id=v.product_id"
                       " where p.slug=:s and v.version=:v"), {"s": slug, "v": version}).first()
    if not r:
        raise NotFound("product version not found")
    return r


def set_composition(staff_id: UUID, slug: str, version: int, comp: dict[str, Any]) -> dict[str, Any]:
    with tx(None) as c:
        v = _version_row(c, slug, version)
        if v.status != "draft":
            raise Conflict("published versions are immutable; create a new version")
        resolved = _validate_composition(c, comp)
        canonical = {k: resolved[k] for k in ("modules", "template", "plans", "branding") if resolved.get(k)}  # warnings/added_deps are derived, not stored
        c.execute(text("update platform.product_versions set composition=cast(:c as jsonb) where id=:i"), {"c": _j(canonical), "i": v.id})
        audit.record_platform(c, staff_id, "product.composition_set", "product", v.product_id, {"slug": slug, "version": version})
        return resolved


def test_composition(slug: str, version: int) -> dict[str, Any]:
    with tx(None) as c:
        v = _version_row(c, slug, version)
        return _validate_composition(c, v.composition)


def publish_version(staff_id: UUID, slug: str, version: int) -> None:
    with tx(None) as c:
        v = _version_row(c, slug, version)
        if v.status != "draft":
            raise Conflict("already published")
        if not v.composition.get("modules"):
            raise Invalid("a product needs at least one module before publishing")
        _validate_composition(c, v.composition)
        c.execute(text("update platform.product_versions set status='published', published_at=now() where id=:i"), {"i": v.id})
        c.execute(text("update platform.products set status='published' where id=:p and status='draft'"), {"p": v.product_id})
        audit.record_platform(c, staff_id, "product.version_published", "product", v.product_id, {"slug": slug, "version": version})


def new_product_version(staff_id: UUID, slug: str) -> dict[str, Any]:
    with tx(None) as c:
        row = c.execute(text("select p.id, max(v.version) as last from platform.products p join platform.product_versions v on v.product_id=p.id"
                             " where p.slug=:s group by p.id"), {"s": slug}).first()
        if not row:
            raise NotFound("product not found")
        last = _version_row(c, slug, row.last)
        if last.status == "draft":
            raise Conflict("a draft version already exists")
        c.execute(text("insert into platform.product_versions (id, product_id, version, composition) values (:i,:p,:v,cast(:c as jsonb))"),
                  {"i": uuid4(), "p": row.id, "v": row.last + 1, "c": _j(last.composition)})
        audit.record_platform(c, staff_id, "product.version_created", "product", row.id, {"slug": slug, "version": row.last + 1})
    return {"slug": slug, "version": row.last + 1}


def list_products(published_only: bool) -> list[dict[str, Any]]:
    with tx(None) as c:
        out = []
        for p in c.execute(text("select * from platform.products" + (" where status='published'" if published_only else "") + " order by slug")).all():
            vs = c.execute(text("select version, status, composition, published_at from platform.product_versions where product_id=:p"
                                + (" and status='published'" if published_only else "") + " order by version desc"), {"p": p.id}).mappings().all()
            out.append({"slug": p.slug, "name": p.name, "description": p.description, "industry": p.industry_slug,
                        "business_models": p.business_models, "status": p.status, "versions": [dict(v) for v in vs]})
        return out


def install_product(p: Principal, slug: str) -> dict[str, Any]:
    with tx(p.tenant_id) as c:
        v = c.execute(text("select v.*, pr.name, pr.slug from platform.product_versions v join platform.products pr on pr.id=v.product_id"
                           " where pr.slug=:s and v.status='published' order by v.version desc limit 1"), {"s": slug}).first()
        if not v:
            raise NotFound("product not found or not published")
        comp = v.composition
        plan = plan_modules(c, set(comp.get("modules", [])), _active(c), auto_deps=True)
        if plan["conflicts"]:
            raise Invalid("incompatible with your active modules: " + "; ".join(plan["conflicts"]))
        activated = _insert_modules(c, p.tenant_id, sorted(plan["final"]), f"product:{slug}@{v.version}")
        tpl = _apply_template(c, p, comp["template"], None, "product") if comp.get("template") else None
        c.execute(text("insert into platform.tenant_settings (tenant_id, branding, installed_product, installed_product_version) values (:t,cast(:b as jsonb),:s,:v)"
                       " on conflict (tenant_id) do update set branding=excluded.branding, installed_product=:s, installed_product_version=:v, updated_at=now()"),
                  {"t": p.tenant_id, "b": _j(comp.get("branding", {})), "s": slug, "v": v.version})
        audit.record(c, p.tenant_id, p.user_id, "product.installed", data={"product": f"{slug}@{v.version}", "modules": activated})
        return {"product": slug, "version": v.version, "activated_modules": activated, "not_entitled": _not_entitled(c, activated),
                "template": tpl["chain"] if tpl else None, "recommended_plans": comp.get("plans", [])}


# ------------------------------------------------------------------ navigation & settings (tenant)
def navigation(p: Principal) -> list[dict[str, Any]]:
    with tx(p.tenant_id) as c:
        grants = authz.load_grants(c, p.membership_id)
        out: dict[str, dict[str, Any]] = {}
        for key in sorted(_active(c)):
            app, _, mod = key.partition(".")
            if app == "platform" or not _module_exists(c, key):
                continue
            feats = []
            for f in _features(c, key):
                if not authz.entitled(c, f.key):
                    continue
                allowed = [a for a in f.actions if any(authz.matches(g.pattern, f.key) and g.action in ("*", a) for g in grants)]
                if allowed:
                    feats.append({"key": f.key, "name": f.name, "actions": allowed, "status": f.status})
            if feats:
                names = c.execute(text("select a.name as an, m.name as mn from platform.modules m join platform.applications a on a.id=m.application_id"
                                       " where a.slug=:a and m.slug=:m"), {"a": app, "m": mod}).first()
                entry = out.setdefault(app, {"slug": app, "name": names.an if names else app, "modules": []})
                entry["modules"].append({"slug": mod, "name": names.mn if names else mod, "features": feats})
        return list(out.values())


def get_terminology(tenant_id: UUID) -> dict[str, str]:
    with tx(tenant_id) as c:
        return {r.term: r.label for r in c.execute(text("select term, label from platform.tenant_terminology")).all()}


def set_term(p: Principal, term: str, label: str) -> None:
    if not SLUG.match(term) or not label.strip():
        raise Invalid("term must be a slug and label non-empty")
    with tx(p.tenant_id) as c:
        c.execute(text("insert into platform.tenant_terminology (id, tenant_id, term, label) values (:i,:t,:k,:l)"
                       " on conflict (tenant_id, term) do update set label=excluded.label, source='tenant'"),
                  {"i": uuid4(), "t": p.tenant_id, "k": term, "l": label.strip()})
        audit.record(c, p.tenant_id, p.user_id, "terminology.set", data={"term": term, "label": label})


def list_fields(tenant_id: UUID, entity: str | None = None) -> list[dict[str, Any]]:
    with tx(tenant_id) as c:
        q = "select entity, key, label, type, required, options, source from platform.tenant_custom_fields"
        rows = c.execute(text(q + (" where entity=:e" if entity else "") + " order by entity, sort, key"), {"e": entity}).mappings().all()
        return [dict(r) for r in rows]


def create_field(p: Principal, f: dict[str, Any]) -> None:
    _check_field_def(f)
    with tx(p.tenant_id) as c:
        try:
            with c.begin_nested():
                c.execute(text("insert into platform.tenant_custom_fields (id, tenant_id, entity, key, label, type, required, options)"
                               " values (:i,:t,:e,:k,:l,:ty,:r,cast(:o as jsonb))"),
                          {"i": uuid4(), "t": p.tenant_id, "e": f["entity"], "k": f["key"], "l": f["label"], "ty": f["type"],
                           "r": bool(f.get("required")), "o": _j(f.get("options", []))})
        except Exception as e:
            if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
                raise Conflict("field already exists") from e
            raise
        audit.record(c, p.tenant_id, p.user_id, "custom_field.created", data={"entity": f["entity"], "key": f["key"]})


def delete_field(p: Principal, entity: str, key: str) -> None:
    with tx(p.tenant_id) as c:
        if not c.execute(text("delete from platform.tenant_custom_fields where entity=:e and key=:k"), {"e": entity, "k": key}).rowcount:
            raise NotFound("field not found")
        audit.record(c, p.tenant_id, p.user_id, "custom_field.deleted", data={"entity": entity, "key": key})


def validate_custom_values(c: Connection, entity: str, values: dict[str, Any], require_all: bool) -> dict[str, Any]:
    defs = {r.key: r for r in c.execute(text("select key, label, type, required, options from platform.tenant_custom_fields where entity=:e"), {"e": entity}).all()}
    unknown = set(values) - set(defs)
    if unknown:
        raise Invalid(f"unknown custom fields: {sorted(unknown)}")
    clean: dict[str, Any] = {}
    for k, v in values.items():
        d = defs[k]
        if v is None or v == "":
            if d.required:
                raise Invalid(f"{d.label} is required")
            continue
        try:
            if d.type == "number":
                if isinstance(v, bool):
                    raise InvalidOperation()
                clean[k] = float(Decimal(str(v)))
            elif d.type == "boolean":
                if not isinstance(v, bool):
                    raise InvalidOperation()
                clean[k] = v
            elif d.type == "date":
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
                    raise InvalidOperation()
                clean[k] = str(v)
            elif d.type == "select":
                if v not in d.options:
                    raise Invalid(f"{d.label} must be one of {d.options}")
                clean[k] = v
            else:
                clean[k] = str(v)[:2000]
        except InvalidOperation as e:
            raise Invalid(f"{d.label} must be a valid {d.type}") from e
    if require_all:
        for k, d in defs.items():
            if d.required and k not in clean:
                raise Invalid(f"{d.label} is required")
    return clean


def dashboard(p: Principal) -> dict[str, Any]:
    with tx(p.tenant_id) as c:
        row = c.execute(text("select name, config from platform.tenant_dashboards order by name limit 1")).first()
        if not row:
            return {"name": None, "widgets": []}
        grants = authz.load_grants(c, p.membership_id)
        widgets = []
        for w in row.config.get("widgets", []):
            feature, table, cols = WIDGETS[w["source"]]
            gs = [g for g in grants if authz.matches(g.pattern, feature) and g.action in ("*", "view")]
            if not gs:
                continue  # never reveal counts the user cannot see
            az = authz.Authz(p, feature, "view", gs)
            where, params = az.scope().where(**cols) if cols else ("true", {})
            n = c.execute(text(f"select count(*) from platform.{table} where {where}"), params).scalar()
            widgets.append({"title": w.get("title") or w["source"].title(), "source": w["source"], "value": int(n or 0)})
        return {"name": row.name, "widgets": widgets}


def settings(tenant_id: UUID) -> dict[str, Any]:
    with tx(tenant_id) as c:
        r = c.execute(text("select branding, applied_template, applied_template_version, installed_product, installed_product_version"
                           " from platform.tenant_settings")).mappings().first()
        return dict(r) if r else {"branding": {}, "applied_template": None, "installed_product": None}

