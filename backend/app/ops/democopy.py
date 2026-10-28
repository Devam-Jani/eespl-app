# ruff: noqa: E501
"""Copy the DEMO company from one database to another (the PC's to the test server's), with
nothing real in it and nothing twice:

    python -m app.cli demo-copy count                        # DEMO rows per table, this database
    python -m app.cli demo-copy export --out demo.json       # on the PC
    python -m app.cli demo-copy import --in demo.json --dry-run   # on the server: the plan, nothing kept
    python -m app.cli demo-copy import --in demo.json        # the same, kept

What is DEMO: every row flagged is_demo, and every row that hangs off one through a foreign key
(a DEMO site's stages, its BOQ, bills, photos ...), transitively. A row of a flagged table that is
not flagged is never DEMO, and a hanging row that also points at a real row of a flagged table (a
real site, a real client, a real user) is left out: it belongs to the real company. Sessions, the
audit log, sequences and outboxes are never copied.

The import, in one transaction:
- a flagged row the target already has (the same natural key: a site's name, a user's email, a
  product's code ...) is not copied again; the target's own row stands, and the rows hanging only
  off target rows are the target's own (not copied either);
- a row is copied when one of its DEMO parents was copied (the X-ray site's stages, a new DEMO
  user's roles); its ids are new, every foreign key remapped;
- a reference to a shared row (a role, a unit, a system) is matched on the target by its key; a
  reference that cannot be matched (a real user, the real rate library) is emptied when it may be,
  else the row is left out, and both are reported;
- new DEMO users get the target's DEMO_USER_PASSWORD;
- what was copied is remembered (system_status 'demo_copy'), so a second run adds nothing twice.
--exclude-site CODE leaves a DEMO site and everything under it out (one built from a client's
real drawings). Media files are listed in the export (media_files); copying them is a file copy.
"""

import base64
import json
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Table, and_, select, text
from sqlalchemy.orm import Session

from app.models import Base

FLAG = "is_demo"
EXCLUDE = {
    "audit_log", "doc_sequences", "helper_answers", "kylas_cursors", "kylas_outbox", "lead_sequences",
    "notification_outbox", "password_links", "refresh_tokens", "site_sequences", "system_status", "tender_sequences",
}  # fmt: skip
# how a flagged row is recognised on the target (a column ending in _id is compared after remapping)
IDENTITY = {
    "users": ["email"], "sites": ["name"], "tenders": ["name"], "clients": ["name"], "vendors": ["name"],
    "client_standards": ["name"], "products": ["code"], "method_products": ["name"], "method_systems": ["code"],
    "mix_designs": ["code"], "methodologies": ["title"], "estimates": ["site_id", "title"], "work_completions": ["site_id", "code"],
    "issue_log": ["title"], "leads": ["company", "contact_name"], "monthly_summaries": ["month", "site_id"],
    "site_summaries": ["site_id"], "invoice_summaries": ["invoice_id"], "kpi_snapshots": ["on_date"], "coverages": ["product_id"],
}  # fmt: skip
MASTER_KEYS = ("code", "key", "email", "name", "title", "label")  # a shared row's key, the first present
STATE_KEY = "demo_copy"


def tables() -> dict[str, Table]:
    return {n: t for n, t in sorted(Base.metadata.tables.items()) if n not in EXCLUDE}  # the order is _order's job


def _pk(t: Table) -> list[str]:
    return [c.name for c in t.primary_key.columns]


def _fks(t: Table) -> list[tuple[str, str, str]]:
    """(column, parent table, parent column) for each single-column foreign key."""
    return [(fk.parent.name, fk.column.table.name, fk.column.name) for fk in t.foreign_keys]


# --- values in JSON ---------------------------------------------------------------------------------


def enc(v):
    if isinstance(v, Decimal):
        return {"$d": str(v)}
    if isinstance(v, datetime):
        return {"$dt": v.isoformat()}
    if isinstance(v, date):
        return {"$da": v.isoformat()}
    if isinstance(v, time):
        return {"$t": v.isoformat()}
    if isinstance(v, timedelta):
        return {"$td": v.total_seconds()}
    if isinstance(v, uuid.UUID):
        return {"$u": str(v)}
    if isinstance(v, bytes | memoryview):
        return {"$b": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, list | tuple):
        return [enc(x) for x in v]
    if isinstance(v, dict):
        return {"$j": v}
    return v


def dec(v):
    if isinstance(v, list):
        return [dec(x) for x in v]
    if not isinstance(v, dict):
        return v
    (tag, x), = v.items()
    return {
        "$d": Decimal, "$dt": datetime.fromisoformat, "$da": date.fromisoformat, "$t": time.fromisoformat,
        "$td": lambda s: timedelta(seconds=s), "$u": uuid.UUID, "$b": base64.b64decode, "$j": lambda j: j,
    }[tag](x)  # fmt: skip


def _key(values) -> str:
    return json.dumps([enc(v) for v in values], sort_keys=True, default=str)


# --- what is DEMO -----------------------------------------------------------------------------------


def closure(db: Session, exclude_sites: tuple[str, ...] = ()) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """The DEMO rows of this database, per table (whole rows), and what was left out and why."""
    tabs = tables()
    flagged = {n for n, t in tabs.items() if FLAG in t.c}
    rows: dict[str, dict[str, dict]] = defaultdict(dict)  # table -> pk key -> row
    left_out: dict[str, list[str]] = defaultdict(list)

    def add(name: str, found) -> int:
        t, new = tabs[name], 0
        for r in found:
            r = dict(r._mapping)
            k = _key([r[c] for c in _pk(t)])
            if k not in rows[name]:
                rows[name][k] = r
                new += 1
        return new

    for name in flagged:
        t = tabs[name]
        add(name, db.execute(select(t).where(t.c[FLAG].is_(True))))

    def values(parent: str, col: str) -> list:
        return [r[col] for r in rows[parent].values() if r.get(col) is not None]

    changed = True
    while changed:
        changed = False
        for name, t in tabs.items():
            if name in flagged:
                continue
            for col, parent, pcol in _fks(t):
                vals = values(parent, pcol)
                if not vals:
                    continue
                for i in range(0, len(vals), 5000):
                    if add(name, db.execute(select(t).where(t.c[col].in_(vals[i : i + 5000])))):
                        changed = True

    # a hanging row that also points at a real row: a non-DEMO row of a flagged table (a real site,
    # client, product), or a row that belongs to one (a real site's drawing), a few levels up; who
    # made a row (a user) does not make it real
    real_cache: dict[tuple[str, str, object], bool] = {}

    def is_real(parent: str, pcol: str, v, depth: int = 0) -> bool:
        k = (parent, pcol, v)
        if k not in real_cache:
            real_cache[k] = False
            pt = tabs.get(parent)
            row = db.execute(select(pt).where(pt.c[pcol] == v)).first() if pt is not None else None
            if row is not None and depth < 4:
                row = dict(row._mapping)
                for col, gp, gpcol in _fks(pt):
                    gv = row.get(col)
                    if gv is None or gp == "users":
                        continue
                    if gp in flagged:
                        if not any(x.get(gpcol) == gv for x in rows[gp].values()):
                            real_cache[k] = True
                            break
                    elif not any(x.get(gpcol) == gv for x in rows.get(gp, {}).values()) and is_real(gp, gpcol, gv, depth + 1):
                        real_cache[k] = True
                        break
        return real_cache[k]

    def real_refs(name: str, r: dict) -> list[str]:
        out = []
        for col, parent, pcol in _fks(tabs[name]):
            v = r.get(col)
            if v is None or parent == "users":  # who made it: emptied on the target, never a reason to leave out
                continue
            demo_parent = any(p.get(pcol) == v for p in rows.get(parent, {}).values())
            if parent in flagged and not demo_parent:
                out.append(f"{col} -> a real {parent} row")
            elif parent not in flagged and not demo_parent and is_real(parent, pcol, v):
                out.append(f"{col} -> a {parent} row of the real company")
        return out

    changed = True
    while changed:  # dropping a row can strand the rows under it
        changed = False
        for name in list(rows):
            if name in flagged:
                continue
            for k, r in list(rows[name].items()):
                why = real_refs(name, r)
                if why:
                    del rows[name][k]
                    left_out[name].append(f"{k}: {', '.join(why)}")
                    changed = True
    # an excluded site: everything that hangs off it or off its tender (flagged rows too: the
    # tender's methodology and its exported files)
    if exclude_sites:
        out_vals: dict[tuple[str, str], set] = defaultdict(set)  # (table, column) -> excluded values
        gone: list[tuple[str, dict]] = []  # the excluded site and tender rows
        for k, r in list(rows["sites"].items()):
            if r["code"] in exclude_sites:
                gone.append(("sites", rows["sites"].pop(k)))
        tender_ids = {r["tender_id"] for _, r in gone if r.get("tender_id") is not None}
        for k, r in list(rows["tenders"].items()):
            if r["id"] in tender_ids:
                gone.append(("tenders", rows["tenders"].pop(k)))
        for name, r in gone:
            left_out[name].append(f"{r.get('code')} {r.get('name')}: excluded (built from a client's real files)")

        def drop(name: str, r: dict) -> None:
            for c in tabs[name].c.keys():
                if r.get(c) is not None and isinstance(r[c], int | str | uuid.UUID):
                    out_vals[(name, c)].add(r[c])

        for name, r in gone:
            drop(name, r)

        def propagate() -> None:
            changed = True
            while changed:
                changed = False
                for name in list(rows):
                    t = tabs[name]
                    for k, r in list(rows[name].items()):
                        hit = [col for col, parent, pcol in _fks(t) if r.get(col) is not None and r[col] in out_vals.get((parent, pcol), ())]
                        if hit:
                            del rows[name][k]
                            left_out[name].append(f"{k}: under an excluded site ({', '.join(hit)})")
                            drop(name, r)
                            changed = True

        propagate()
        # the DEMO rows the excluded site and tender pointed at (their client), when nothing kept uses them
        for name, r in gone:
            for col, parent, pcol in _fks(tabs[name]):
                v = r.get(col)
                if v is None or parent not in flagged or parent == "users":
                    continue
                used = any(x.get(c) == v for n2, xs in rows.items() for c, p2, pc2 in _fks(tabs[n2]) if p2 == parent and pc2 == pcol for x in xs.values())
                for k, x in list(rows.get(parent, {}).items()):
                    if x.get(pcol) == v and not used:
                        del rows[parent][k]
                        left_out[parent].append(f"{x.get('code') or x.get('name')}: used only by an excluded site")
                        drop(parent, x)
        propagate()
    return {n: list(v.values()) for n, v in rows.items() if v}, dict(left_out)


def counts(db: Session, exclude_sites: tuple[str, ...] = ()) -> dict[str, int]:
    found, _ = closure(db, exclude_sites)
    return {n: len(v) for n, v in sorted(found.items())}


# --- export -----------------------------------------------------------------------------------------


def _path_columns(t: Table) -> list[str]:
    return [c.name for c in t.c if c.name.endswith("_path") or c.name in ("path", "stored_path", "file_path")]


def export(db: Session, exclude_sites: tuple[str, ...] = ()) -> dict:
    tabs = tables()
    found, left_out = closure(db, exclude_sites)
    demo_keys = {n: {_key([r[c] for c in _pk(tabs[n])]) for r in rs} for n, rs in found.items()}
    masters: dict[str, dict[str, dict]] = defaultdict(dict)
    media: set[str] = set()
    for name, rs in found.items():
        t = tabs[name]
        for r in rs:
            for col in _path_columns(t):
                if isinstance(r.get(col), str) and r[col]:
                    media.add(r[col])
            for col, parent, pcol in _fks(t):
                v = r.get(col)
                if v is None or parent not in tabs or FLAG in tabs[parent].c:
                    continue
                pt = tabs[parent]
                if _pk(pt) == [pcol] and _key([v]) in demo_keys.get(parent, set()):
                    continue  # a DEMO row itself
                mk = _key([parent, pcol, v])
                if mk not in masters[parent]:
                    m = db.execute(select(pt).where(pt.c[pcol] == v)).first()
                    if m is not None:
                        masters[parent][mk] = {"col": pcol, "row": {k: enc(x) for k, x in dict(m._mapping).items()}}
    return {
        "version": 1,
        "tables": {n: [{k: enc(v) for k, v in r.items()} for r in rs] for n, rs in found.items()},
        "masters": {n: list(v.values()) for n, v in masters.items()},
        "media_files": sorted(media),
        "left_out": left_out,
    }


# --- import -----------------------------------------------------------------------------------------


def _order(names: set[str]) -> list[str]:
    """Parents first; the cycle edges (all nullable) are filled in afterwards."""
    tabs = tables()
    deps = {n: {p for _, p, _ in _fks(tabs[n]) if p in names and p != n} for n in names}
    required = {n: {fk.column.table.name for fk in tabs[n].foreign_keys if not fk.parent.nullable and fk.column.table.name in names and fk.column.table.name != n} for n in names}
    out: list[str] = []
    while deps:
        ready = sorted(n for n, d in deps.items() if not d - set(out))
        if not ready:  # a cycle: by the required links only (the optional ones are filled in afterwards)
            ready = sorted(n for n in deps if not required[n] - set(out))[:1]
        if not ready:
            ready = [min(deps, key=lambda n: (len(deps[n] - set(out)), n))]
        for n in ready:
            out.append(n)
            del deps[n]
    return out


def _master_match(db: Session, t: Table, col: str, row: dict):
    """The target's value for a shared row's referenced column, or None."""
    v = row[col]
    keys = [k for k in MASTER_KEYS if k in t.c and row.get(k) is not None]
    same = db.execute(select(t).where(t.c[col] == v)).first()
    if same is not None and all(same._mapping[k] == row[k] for k in keys):
        return v
    if keys:
        other = db.execute(select(t.c[col]).where(and_(*[t.c[k] == row[k] for k in keys]))).first()
        if other is not None:
            return other[0]
    return None


def import_(db: Session, data: dict, demo_password_hash: str | None, dry_run: bool = False) -> dict:
    tabs = tables()
    state_row = db.execute(text("SELECT value FROM system_status WHERE key = :k"), {"k": STATE_KEY}).first()
    copied: dict[str, dict[str, list]] = (state_row[0] or {}).get("map", {}) if state_row else {}
    copied = {n: dict(v) for n, v in copied.items()}
    src = {n: [{k: dec(v) for k, v in r.items()} for r in rs] for n, rs in data["tables"].items()}
    masters = {n: [(m["col"], {k: dec(v) for k, v in m["row"].items()}) for m in ms] for n, ms in data["masters"].items()}
    flagged = {n for n in src if FLAG in tabs[n].c}

    # (table, column, source value) -> the target's value, and the fate of the row it came from
    vmap: dict[tuple[str, str, str], object] = {}
    vstatus: dict[tuple[str, str, str], str] = {}  # new | copied | existing | dropped
    srcvals = {(n, c, _key([r[c]])) for n, rs in src.items() for r in rs for c in r}
    report: dict[str, dict] = {k: defaultdict(int) for k in ("inserted", "existing", "under_existing", "already_copied", "emptied", "mixed")}
    dropped: dict[str, list[str]] = defaultdict(list)
    new_names: dict[str, list[str]] = defaultdict(list)
    media: set[str] = set()

    for name, ms in masters.items():
        t = tabs[name]
        for col, row in ms:
            vmap[(name, col, _key([row[col]]))] = _master_match(db, t, col, row)

    def remember(name: str, srow: dict, trow: dict | None, st: str) -> None:
        for c in tabs[name].c.keys():
            if c in srow:
                k = (name, c, _key([srow[c]]))
                vstatus[k] = st
                if trow is not None and c in trow:
                    vmap[k] = trow[c]

    later: list[tuple[str, dict, str, tuple]] = []  # cycle edges to fill: table, target pk, column, parent value
    order = _order(set(src))
    for name in order:
        t = tabs[name]
        pk = _pk(t)
        for r in src[name]:
            skey = _key([r[c] for c in pk])
            # 1. copied by an earlier run
            if skey in copied.get(name, {}):
                tpk = [dec(v) for v in copied[name][skey]]
                trow = db.execute(select(t).where(and_(*[t.c[c] == v for c, v in zip(pk, tpk, strict=True)]))).first()
                if trow is not None:
                    remember(name, r, dict(trow._mapping), "copied")
                    report["already_copied"][name] += 1
                    continue
            # 2. the parents' fate and the remapped row
            new_row = {c: r.get(c) for c in t.c.keys() if t.c[c].computed is None}
            parent_states: set[str] = set()
            user_states: set[str] = set()  # a user is who acted; it decides only when it is the sole DEMO parent
            drop_why, cycle = None, []
            for col, parent, pcol in _fks(t):
                v = r.get(col)
                if v is None:
                    continue
                k = (parent, pcol, _key([v]))
                if k in vstatus:
                    st = vstatus[k]
                    tv = None if st == "dropped" else vmap.get(k)
                    if st != "dropped":
                        (user_states if parent == "users" else parent_states).add(st)
                elif k in srcvals and parent in src:  # a DEMO row not placed yet: a cycle edge
                    cycle.append((col, k))
                    new_row[col] = None
                    continue
                else:  # a shared row (role, unit, system) or a real one
                    tv = vmap.get(k)
                if tv is None:
                    if t.c[col].nullable:
                        new_row[col] = None
                        report["emptied"][f"{name}.{col}"] += 1
                    else:
                        drop_why = drop_why or f"{col} -> {parent} not on the target"
                else:
                    new_row[col] = tv
            # 3. the target's own row?
            if name in flagged:
                ident = IDENTITY.get(name) or [c for c in ("code", "name") if c in t.c][:1]
                found = db.execute(select(t).where(t.c[FLAG].is_(True), *[t.c[c] == new_row[c] for c in ident])).first() if ident else None
                if found is not None:
                    remember(name, r, dict(found._mapping), "existing")
                    report["existing"][name] += 1
                    continue
            elif not parent_states and user_states and not user_states & {"new", "copied"} and "name" in t.c and ("code" not in t.c or str(new_row.get("code") or "").startswith("DEMO")):
                # a DEMO master (named; its code, if any, a fixed DEMO-... one) only a user links to: a DEMO system, a DEMO
                # stage template; copied unless the target has one of the same name
                by = "code" if "code" in t.c else "name"
                same = db.execute(select(t).where(t.c[by] == new_row[by])).first()
                if same is not None:
                    remember(name, r, dict(same._mapping), "existing")
                    report["existing"][name] += 1
                    continue
            elif not (parent_states or user_states) & {"new", "copied"} or parent_states and not parent_states & {"new", "copied"}:
                remember(name, r, None, "existing")  # hangs only off the target's own DEMO rows: theirs stand
                report["under_existing"][name] += 1
                continue
            if drop_why:
                remember(name, r, None, "dropped")
                dropped[name].append(drop_why)
                continue
            if "existing" in parent_states and parent_states & {"new", "copied"}:
                report["mixed"][name] += 1
            # 4. insert, new ids
            if pk == ["id"] and str(t.c.id.type) in ("INTEGER", "BIGINT"):
                new_row.pop("id", None)
            if name == "users" and demo_password_hash:
                new_row["password_hash"] = demo_password_hash
            sp = db.begin_nested()
            try:
                tpk = list(db.execute(t.insert().values(**new_row).returning(*[t.c[c] for c in pk])).first())
                sp.commit()
            except Exception as exc:  # noqa: BLE001  e.g. a unique key the target already uses
                sp.rollback()
                remember(name, r, None, "dropped")
                dropped[name].append("not insertable: " + str(getattr(exc, "orig", exc)).splitlines()[0][:160])
                continue
            trow = {**new_row, **dict(zip(pk, tpk, strict=True))}
            remember(name, r, trow, "new")
            copied.setdefault(name, {})[skey] = [enc(x) for x in tpk]
            report["inserted"][name] += 1
            media.update(r[c] for c in _path_columns(t) if isinstance(r.get(c), str) and r[c])
            if name in flagged:
                ident = IDENTITY.get(name) or [c for c in ("code", "name") if c in t.c][:1]
                new_names[name].append(" / ".join(str(r.get(c)) for c in ident if not c.endswith("_id")) or skey)
            for col, k in cycle:
                later.append((name, dict(zip(pk, tpk, strict=True)), col, k))
    for name, tpk, col, k in later:
        tv = vmap.get(k) if vstatus.get(k) not in (None, "dropped") else None
        if tv is not None:
            t = tabs[name]
            db.execute(t.update().where(and_(*[t.c[c] == x for c, x in tpk.items()])).values({col: tv}))
    db.execute(
        text("INSERT INTO system_status (key, value, at) VALUES (:k, CAST(:v AS jsonb), now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, at = EXCLUDED.at"),
        {"k": STATE_KEY, "v": json.dumps({"map": copied})},
    )
    out = {k: dict(sorted(v.items())) for k, v in report.items()}
    out["dropped"] = {n: len(x) for n, x in sorted(dropped.items())}
    out["new_flagged_rows"] = dict(new_names)
    out["media_files"] = sorted(media)  # the files to copy: those of the rows copied, nothing else
    out["dropped_reasons"] = {n: sorted(set(x))[:5] for n, x in sorted(dropped.items())}
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return out


def media_root() -> Path:
    from app.config import settings  # noqa: PLC0415

    return Path(settings.media_dir)
