"""Capability/application/module/submodule/feature/industry/business-model registries + code-first manifest sync.

Code manifests (`ueos/platform/manifest.yaml`, `ueos/apps/*/manifest.yaml`) own rows with origin='code'.
Admin-created rows have origin='config' and are never overwritten by a sync.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from sqlalchemy import Connection, text

from ueos.platform.db import tx
from ueos.platform.errors import Conflict, Invalid, NotFound

PKG = Path(__file__).resolve().parent.parent
SLUG = re.compile(r"^[a-z][a-z0-9_]*$")
FEATURE_STATUSES = ("specified", "implemented", "tested", "released", "deprecated")


class ManifestError(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


# ------------------------------------------------------------------ manifests
def load_manifests() -> list[dict[str, Any]]:
    paths = [PKG / "platform" / "manifest.yaml", *sorted((PKG / "apps").glob("*/manifest.yaml"))]
    out = []
    for p in paths:
        m = yaml.safe_load(p.read_text(encoding="utf-8"))
        m["_path"] = str(p)
        out.append(m)
    return out


def flatten(m: dict[str, Any]) -> Iterator[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any], str]]:
    app = m["application"]["slug"]
    for mod in m.get("modules", []):
        for f in mod.get("features", []):
            yield mod, None, f, f"{app}.{mod['slug']}.{f['slug']}"
        for sub in mod.get("submodules", []):
            for f in sub.get("features", []):
                yield mod, sub, f, f"{app}.{mod['slug']}.{sub['slug']}.{f['slug']}"


def lint(manifests: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validate manifests; returns {key: feature}. Raises ManifestError listing every problem."""
    errs: list[str] = []
    feats: dict[str, dict[str, Any]] = {}
    apps: set[str] = set()
    for m in manifests:
        a = m.get("application") or {}
        slug = a.get("slug", "")
        if not SLUG.match(slug) or not a.get("name"):
            errs.append(f"{m.get('_path')}: application needs a valid slug and name")
            continue
        if slug in apps:
            errs.append(f"duplicate application slug '{slug}'")
        apps.add(slug)
        seen_mod: set[str] = set()
        for mod in m.get("modules", []):
            if not SLUG.match(mod.get("slug", "")) or not mod.get("name"):
                errs.append(f"{slug}: module needs valid slug and name: {mod.get('slug')}")
            if mod.get("slug") in seen_mod:
                errs.append(f"{slug}: duplicate module '{mod.get('slug')}'")
            seen_mod.add(mod.get("slug", ""))
        for _mod, _sub, f, key in flatten(m):
            if not SLUG.match(f.get("slug", "")) or not f.get("name"):
                errs.append(f"{key}: invalid slug/name")
            acts = f.get("actions")
            if not acts or not all(isinstance(x, str) and SLUG.match(x) for x in acts):
                errs.append(f"{key}: actions must be a non-empty list of slugs")
            if f.get("status", "specified") not in FEATURE_STATUSES:
                errs.append(f"{key}: invalid status {f.get('status')}")
            if key in feats:
                errs.append(f"duplicate feature key '{key}'")
            feats[key] = f
    for key, f in feats.items():
        for d in f.get("depends_on", []):
            if d not in feats:
                errs.append(f"{key}: depends_on unknown feature '{d}'")
    for key, f in feats.items():
        for d in f.get("conflicts_with", []):
            if d not in feats:
                errs.append(f"{key}: conflicts_with unknown feature '{d}'")
            if d == key:
                errs.append(f"{key}: cannot conflict with itself")
    # cycle detection (iterative DFS)
    state: dict[str, int] = {}
    for start, first in feats.items():
        stack = [(start, iter(first.get("depends_on", [])))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
            elif nxt in feats:
                if state.get(nxt) == 1:
                    errs.append(f"dependency cycle through '{nxt}'")
                elif state.get(nxt) is None:
                    state[nxt] = 1
                    stack.append((nxt, iter(feats[nxt].get("depends_on", []))))
    if errs:
        raise ManifestError(sorted(set(errs)))
    return feats


def sync_manifests(manifests: list[dict[str, Any]] | None = None) -> dict[str, int]:
    ms = manifests if manifests is not None else load_manifests()
    feats = lint(ms)
    rep = {"applications": 0, "modules": 0, "submodules": 0, "features": 0, "deprecated": 0}
    with tx(None) as c:
        for m in ms:
            a = m["application"]
            r = c.execute(
                text("""insert into platform.applications (id, slug, name, description, category, version, legacy_ref, status, origin)
                        values (:id, :s, :n, :d, :cat, :v, :lr, 'published', 'code')
                        on conflict (slug) do update set name=excluded.name, description=excluded.description,
                          category=excluded.category, version=excluded.version, legacy_ref=excluded.legacy_ref
                        where platform.applications.origin = 'code' returning id, (xmax = 0) as inserted"""),
                {"id": uuid4(), "s": a["slug"], "n": a["name"], "d": a.get("description", ""),
                 "cat": a.get("category", "general"), "v": a.get("version", "0.1.0"), "lr": a.get("legacy_ref")},
            ).first()
            if r is None:
                raise ManifestError([f"application '{a['slug']}' exists as config-defined; refusing to overwrite"])
            app_id = r.id
            rep["applications"] += int(r.inserted)
            mod_ids: dict[str, Any] = {}
            sub_ids: dict[tuple[str, str], Any] = {}
            for mod in m.get("modules", []):
                rr = c.execute(
                    text("""insert into platform.modules (id, application_id, slug, name, description, legacy_ref, origin)
                            values (:id, :a, :s, :n, :d, :lr, 'code')
                            on conflict (application_id, slug) do update set name=excluded.name,
                              description=excluded.description, legacy_ref=excluded.legacy_ref
                            where platform.modules.origin = 'code' returning id, (xmax = 0) as inserted"""),
                    {"id": uuid4(), "a": app_id, "s": mod["slug"], "n": mod["name"], "d": mod.get("description", ""),
                     "lr": mod.get("legacy_ref")},
                ).first()
                if rr is None:
                    raise ManifestError([f"module '{a['slug']}.{mod['slug']}' exists as config-defined"])
                mod_ids[mod["slug"]] = rr.id
                rep["modules"] += int(rr.inserted)
                for sub in mod.get("submodules", []):
                    sr = c.execute(
                        text("""insert into platform.submodules (id, module_id, slug, name, description, origin)
                                values (:id, :m, :s, :n, :d, 'code')
                                on conflict (module_id, slug) do update set name=excluded.name, description=excluded.description
                                where platform.submodules.origin = 'code' returning id, (xmax = 0) as inserted"""),
                        {"id": uuid4(), "m": rr.id, "s": sub["slug"], "n": sub["name"], "d": sub.get("description", "")},
                    ).first()
                    if sr is None:
                        raise ManifestError([f"submodule '{sub['slug']}' exists as config-defined"])
                    sub_ids[(mod["slug"], sub["slug"])] = sr.id
                    rep["submodules"] += int(sr.inserted)
            for mod, sub, f, key in flatten(m):
                fr = c.execute(
                    text("""insert into platform.features (id, key, application_id, module_id, submodule_id, slug, name, description,
                              actions, depends_on, conflicts_with, sensitive, audited, default_tier, legacy_ref, status, origin)
                            values (:id, :k, :a, :m, :sm, :s, :n, :d, :act, :dep, :cw, :sens, :aud, :tier, :lr, :st, 'code')
                            on conflict (key) do update set name=excluded.name, description=excluded.description,
                              actions=excluded.actions, depends_on=excluded.depends_on, conflicts_with=excluded.conflicts_with,
                              sensitive=excluded.sensitive,
                              audited=excluded.audited, default_tier=excluded.default_tier, legacy_ref=excluded.legacy_ref,
                              status=excluded.status, submodule_id=excluded.submodule_id, module_id=excluded.module_id
                            where platform.features.origin = 'code' returning (xmax = 0) as inserted"""),
                    {"id": uuid4(), "k": key, "a": app_id, "m": mod_ids[mod["slug"]],
                     "sm": sub_ids[(mod["slug"], sub["slug"])] if sub else None, "s": f["slug"], "n": f["name"],
                     "d": f.get("description", ""), "act": f["actions"], "dep": f.get("depends_on", []), "cw": f.get("conflicts_with", []),
                     "sens": bool(f.get("sensitive", False)), "aud": bool(f.get("audited", True)),
                     "tier": f.get("default_tier", "standard"), "lr": f.get("legacy_ref"), "st": f.get("status", "specified")},
                ).first()
                if fr is None:
                    raise ManifestError([f"feature '{key}' exists as config-defined"])
                rep["features"] += int(fr.inserted)
        gone = c.execute(
            text("update platform.features set status='deprecated' where origin='code' and status<>'deprecated'"
                 " and not (key = any(cast(:keys as text[])))"), {"keys": list(feats)}).rowcount
        rep["deprecated"] = gone
    return rep


# ------------------------------------------------------------------ lookups
def feature(conn: Connection, key: str) -> dict[str, Any] | None:
    r = conn.execute(text("select key, actions, sensitive, audited, status from platform.features where key=:k"),
                     {"k": key}).mappings().first()
    return dict(r) if r else None


def validate_permission(conn: Connection, pattern: str, action: str) -> None:
    """A permission targets an exact feature key, a prefix wildcard ('fin.*') or '*'; action must exist (or be '*')."""
    if pattern == "*":
        return
    if pattern.endswith(".*"):
        prefix = pattern[:-1]
        n = conn.execute(text("select count(*) from platform.features where key like :p and status<>'deprecated'"),
                         {"p": prefix.replace("_", r"\_") + "%"}).scalar()
        if not n:
            raise Invalid(f"no feature matches '{pattern}'")
        if action != "*":
            ok = conn.execute(text("select 1 from platform.features where key like :p and :a = any(actions) limit 1"),
                              {"p": prefix.replace("_", r"\_") + "%", "a": action}).first()
            if not ok:
                raise Invalid(f"action '{action}' is not defined by any feature under '{pattern}'")
        return
    f = feature(conn, pattern)
    if not f:
        raise Invalid(f"unknown feature '{pattern}'")
    if action != "*" and action not in f["actions"]:
        raise Invalid(f"feature '{pattern}' has no action '{action}' (has: {', '.join(f['actions'])})")


# ------------------------------------------------------------------ admin CRUD (staff)
def _id(conn: Connection, table: str, slug: str, what: str, extra: str = "") -> Any:
    r = conn.execute(text(f"select id from platform.{table} where slug=:s {extra}"), {"s": slug}).scalar()
    if not r:
        raise NotFound(f"{what} '{slug}' not found")
    return r


def _ins(conn: Connection, table: str, cols: dict[str, Any]) -> str:
    rid = uuid4()
    names = ["id", *cols, "origin"]
    try:
        with conn.begin_nested():
            conn.execute(text(f"insert into platform.{table} ({','.join(names)}) values ({','.join(':' + n for n in names)})"),
                         {"id": rid, **cols, "origin": "config"})
    except Exception as e:
        if getattr(getattr(e, "orig", None), "sqlstate", None) == "23505":
            raise Conflict("already exists") from e
        raise
    return str(rid)


def _check_slug(s: str) -> None:
    if not SLUG.match(s):
        raise Invalid(f"invalid slug '{s}' (lowercase letters, digits, underscore; must start with a letter)")


def create_simple(table: str, slug: str, name: str, description: str) -> dict[str, Any]:
    _check_slug(slug)
    with tx(None) as c:
        rid = _ins(c, table, {"slug": slug, "name": name, "description": description})
    return {"id": rid, "slug": slug}


def create_industry(slug: str, name: str, description: str, parent_slug: str | None) -> dict[str, Any]:
    _check_slug(slug)
    with tx(None) as c:
        parent = _id(c, "industries", parent_slug, "parent industry") if parent_slug else None
        rid = _ins(c, "industries", {"slug": slug, "name": name, "description": description, "parent_id": parent})
    return {"id": rid, "slug": slug}


def create_application(slug: str, name: str, description: str, category: str, version: str, status: str,
                       capability_slug: str | None) -> dict[str, Any]:
    _check_slug(slug)
    with tx(None) as c:
        cap = _id(c, "capability_domains", capability_slug, "capability domain") if capability_slug else None
        rid = _ins(c, "applications", {"slug": slug, "name": name, "description": description, "category": category,
                                       "version": version, "status": status, "capability_domain_id": cap})
    return {"id": rid, "slug": slug}


def create_module(app_slug: str, slug: str, name: str, description: str) -> dict[str, Any]:
    _check_slug(slug)
    with tx(None) as c:
        rid = _ins(c, "modules", {"application_id": _id(c, "applications", app_slug, "application"), "slug": slug,
                                  "name": name, "description": description})
    return {"id": rid, "slug": slug}


def create_submodule(app_slug: str, module_slug: str, slug: str, name: str, description: str) -> dict[str, Any]:
    _check_slug(slug)
    with tx(None) as c:
        app_id = _id(c, "applications", app_slug, "application")
        mid = _id(c, "modules", module_slug, "module", "and application_id = :a".replace(":a", f"'{app_id}'"))
        rid = _ins(c, "submodules", {"module_id": mid, "slug": slug, "name": name, "description": description})
    return {"id": rid, "slug": slug}


def create_feature(app_slug: str, module_slug: str, submodule_slug: str | None, slug: str, name: str, description: str,
                   actions: list[str], depends_on: list[str], sensitive: bool, audited: bool, tier: str) -> dict[str, Any]:
    _check_slug(slug)
    if not actions or not all(SLUG.match(a) for a in actions):
        raise Invalid("actions must be a non-empty list of slugs")
    with tx(None) as c:
        app_id = _id(c, "applications", app_slug, "application")
        mod_id = _id(c, "modules", module_slug, "module", f"and application_id = '{app_id}'")
        sub_id = _id(c, "submodules", submodule_slug, "submodule", f"and module_id = '{mod_id}'") if submodule_slug else None
        key = ".".join([app_slug, module_slug, *([submodule_slug] if submodule_slug else []), slug])
        known = {r[0]: r[1] for r in c.execute(text("select key, depends_on from platform.features")).all()}
        for d in depends_on:
            if d not in known:
                raise Invalid(f"depends_on unknown feature '{d}'")
        # a new key cannot be anyone's existing dependency, so a cycle is impossible unless it depends on itself
        if key in depends_on:
            raise Invalid("feature cannot depend on itself")
        rid = _ins(c, "features", {"key": key, "application_id": app_id, "module_id": mod_id, "submodule_id": sub_id,
                                   "slug": slug, "name": name, "description": description, "actions": actions,
                                   "depends_on": depends_on, "sensitive": sensitive, "audited": audited,
                                   "default_tier": tier, "status": "specified"})
    return {"id": rid, "key": key}


STATUS_TABLES = {
    "capabilities": ("capability_domains", "slug", ("active", "archived")),
    "business-models": ("business_models", "slug", ("active", "archived")),
    "industries": ("industries", "slug", ("active", "archived")),
    "applications": ("applications", "slug", ("draft", "published", "archived")),
    "modules": ("modules", "id", ("active", "archived")),
    "submodules": ("submodules", "id", ("active", "archived")),
    "features": ("features", "key", FEATURE_STATUSES),
}


def set_status(kind: str, ident: str, status: str) -> None:
    if kind not in STATUS_TABLES:
        raise NotFound(f"unknown registry kind '{kind}'")
    table, col, allowed = STATUS_TABLES[kind]
    if status not in allowed:
        raise Invalid(f"status must be one of {', '.join(allowed)}")
    with tx(None) as c:
        n = c.execute(text(f"update platform.{table} set status=:s where {col} = :i" + (" " if col != "id" else "")),
                      {"s": status, "i": ident}).rowcount
    if not n:
        raise NotFound(f"{kind} '{ident}' not found")


def list_kind(kind: str) -> list[dict[str, Any]]:
    tables = {
        "capabilities": "select slug, name, description, status, origin from platform.capability_domains order by slug",
        "business-models": "select slug, name, description, status, origin from platform.business_models order by slug",
        "industries": "select i.slug, i.name, i.description, i.status, i.origin, p.slug as parent from platform.industries i"
                      " left join platform.industries p on p.id = i.parent_id order by i.slug",
        "applications": "select slug, name, category, version, status, origin, legacy_ref from platform.applications order by slug",
        "features": "select key, name, actions, depends_on, sensitive, status, origin, legacy_ref from platform.features order by key",
    }
    if kind not in tables:
        raise NotFound(f"unknown registry kind '{kind}'")
    with tx(None) as c:
        return [dict(r) for r in c.execute(text(tables[kind])).mappings().all()]


def catalog() -> list[dict[str, Any]]:
    """Published applications -> modules -> submodules -> features (tenant-facing)."""
    with tx(None) as c:
        apps = c.execute(text("select id, slug, name, category, version from platform.applications"
                              " where status='published' order by slug")).mappings().all()
        out = []
        for a in apps:
            mods = c.execute(text("select id, slug, name from platform.modules where application_id=:a and status='active' order by slug"),
                             {"a": a["id"]}).mappings().all()
            fs = c.execute(text("select f.key, f.name, f.actions, f.status, f.module_id, s.slug as sub from platform.features f"
                                " left join platform.submodules s on s.id = f.submodule_id"
                                " where f.application_id=:a and f.status<>'deprecated' order by f.key"), {"a": a["id"]}).mappings().all()
            out.append({"slug": a["slug"], "name": a["name"], "category": a["category"], "version": a["version"],
                        "modules": [{"slug": m["slug"], "name": m["name"],
                                     "features": [{"key": f["key"], "name": f["name"], "actions": f["actions"],
                                                   "status": f["status"], "submodule": f["sub"]}
                                                  for f in fs if f["module_id"] == m["id"]]} for m in mods]})
    return out
