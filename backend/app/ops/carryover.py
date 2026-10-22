# ruff: noqa: E501
"""Our real data from the development database into the production one, without DEMO rows:
products (with the master price list; those still in the review queue wait), vendors, clients, the
rate library (systems, library, T&C, quotation library, stage templates and checklists), the BOQ
knowledge, the methodology library, and the active sites with their places and stages.

Ids are kept, so a re-run adds nothing twice (each row is added only when it is not there).
A row is left out, and counted with the reason, when it is DEMO (is_demo, or a name, code or title
starting with "DEMO"), when it points at a row left out, or when it is a product still in the review
queue (pending: planning accepts, merges or rejects it before go-live).
References to people follow the person by email to the production user (imported first), else
they are left empty. A dry run counts the same and changes nothing.

    python -m app.cli carry-over --from postgresql+psycopg://... [--only products,vendors] [--dry-run]
"""

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import Engine, MetaData, Table, create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

GROUPS: dict[str, list[str]] = {
    "products": ["units", "unit_conversions", "categories", "tags", "products", "product_prices", "product_consumptions"],
    "vendors": ["vendors", "vendor_contacts", "vendor_bank_accounts", "vendor_products"],
    "clients": ["channels", "clients", "client_contacts"],
    "library": ["area_types", "systems", "system_components", "productivity_norms", "library_items", "library_lines", "library_versions",
                "tc_clauses", "tc_templates", "tc_template_clauses", "letterheads", "letter_templates", "spec_blocks", "offer_lines", "offer_items",
                "offer_item_specs", "offer_item_lines", "offer_presets", "quotation_references", "checklist_templates", "checklist_items",
                "stage_templates", "stage_template_steps", "labour_rate_cards", "freight_rates"],
    "knowledge": ["knowledge_files", "knowledge_templates", "knowledge_lines", "knowledge_fixes", "knowledge_product_reviews"],
    "methodology": ["method_products", "method_systems", "method_system_changes", "client_standards", "standard_documents", "standard_rules",
                    "standard_contradictions"],
    "sites": ["sites", "site_nodes", "area_scopes", "tasks", "site_stage_days"],
}  # fmt: skip
ORDER = ["products", "vendors", "clients", "library", "knowledge", "methodology", "sites"]
ACTIVE_SITES = ("active", "planned", "on_hold")
DEMO_COLUMNS = ("name", "code", "title")


@dataclass
class TableResult:
    table: str
    source: int = 0
    added: int = 0
    there: int = 0
    skipped: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    examples: list[str] = field(default_factory=list)

    def skip(self, reason: str, row: dict) -> None:
        self.skipped[reason] += 1
        if len(self.examples) < 5:
            label = next((str(row[c]) for c in ("name", "code", "title", "description") if row.get(c)), f"#{row.get('id')}")
            self.examples.append(f"{label[:60]}: {reason}")

    def out(self) -> dict:
        return {"table": self.table, "source": self.source, "added": self.added, "already_there": self.there, "skipped": dict(self.skipped), "examples": self.examples}


def _tables(metadata: MetaData, groups: list[str]) -> list[Table]:
    """The groups' tables, each after the tables it points at (within the run)."""
    names = [t for g in ORDER if g in groups for t in GROUPS[g] if t in metadata.tables]
    chosen = set(names)
    done: list[str] = []

    def visit(n: str, stack: set[str]) -> None:
        if n in done or n in stack:
            return
        stack.add(n)
        for fk in metadata.tables[n].foreign_keys:
            ref = fk.column.table.name
            if ref in chosen and ref != n:
                visit(ref, stack)
        stack.discard(n)
        done.append(n)

    for n in names:
        visit(n, set())
    return [metadata.tables[n] for n in done]


def _is_demo(table: Table, row: dict) -> bool:
    if "is_demo" in table.c and row.get("is_demo"):
        return True
    return any(isinstance(row.get(c), str) and row[c].strip().upper().startswith("DEMO") for c in DEMO_COLUMNS if c in table.c)


def run(source_url: str, target: Engine, groups: list[str] | None = None, dry_run: bool = False) -> dict:
    """Carry the groups over; returns per table what was added, already there and left out."""
    from app.models import Base  # noqa: PLC0415  (every model registered by app.main)

    groups = groups or list(ORDER)
    unknown = set(groups) - set(GROUPS)
    if unknown:
        raise SystemExit(f"Unknown groups: {', '.join(sorted(unknown))} (choose from {', '.join(ORDER)})")
    src = create_engine(source_url, pool_pre_ping=True)
    metadata = Base.metadata
    results: list[TableResult] = []
    with src.connect() as s, target.connect() as t:
        # people: the production user with the same email (imported first)
        src_users = {r.id: (r.email or "").lower() for r in s.execute(text("SELECT id, email FROM users"))}
        tgt_users = {(r.email or "").lower(): r.id for r in t.execute(text("SELECT id, email FROM users"))}
        user_map = {sid: tgt_users.get(email) for sid, email in src_users.items() if email}
        present: dict[str, set] = {}

        def ids_in_target(name: str) -> set:
            if name not in present:
                tab = metadata.tables.get(name)
                pk = list(tab.primary_key.columns)[0] if tab is not None and len(tab.primary_key.columns) == 1 else None
                present[name] = set(t.execute(select(pk)).scalars()) if pk is not None else set()
            return present[name]

        for table in _tables(metadata, groups):
            res = TableResult(table.name)
            pk_cols = list(table.primary_key.columns)
            q = select(table)
            if table.name == "sites":
                q = q.where(table.c.status.in_(ACTIVE_SITES))
            rows = [dict(r._mapping) for r in s.execute(q)]
            res.source = len(rows)
            keep = []
            for row in rows:
                if _is_demo(table, row):
                    res.skip("DEMO", row)
                    continue
                if table.name == "knowledge_product_reviews" and row.get("status") == "pending":
                    res.skip("still to review: planning accepts, merges or rejects it first", row)
                    continue
                ok = True
                for fk in table.foreign_keys:
                    col = fk.parent
                    v = row.get(col.name)
                    if v is None:
                        continue
                    ref = fk.column.table.name
                    if ref == "users":
                        mapped = user_map.get(v)
                        if mapped is None and not col.nullable:
                            res.skip("its person is not a production user", row)
                            ok = False
                            break
                        row[col.name] = mapped
                        continue
                    if ref == table.name:
                        continue  # a row of the same table (parent): checked by the database
                    if v not in ids_in_target(ref):
                        if col.nullable:
                            row[col.name] = None
                        else:
                            res.skip(f"points at a {ref} row left out", row)
                            ok = False
                            break
                if ok:
                    keep.append(row)
            there = ids_in_target(table.name) if len(pk_cols) == 1 else set()
            pk = pk_cols[0].name if len(pk_cols) == 1 else None
            new = [r for r in keep if pk is None or r[pk] not in there]
            res.there = len(keep) - len(new)
            if not dry_run and new:
                # parents before children within a self-referencing table (site nodes, categories)
                self_fk = [fk.parent.name for fk in table.foreign_keys if fk.column.table.name == table.name]
                if self_fk and pk:
                    new = _parents_first(new, pk, self_fk)
                inserted = 0
                for i in range(0, len(new), 500):
                    chunk = new[i : i + 500]
                    stmt = pg_insert(table).values(chunk).on_conflict_do_nothing()
                    if pk:  # count what went in (rowcount is not reliable for a many-row insert)
                        inserted += len(t.execute(stmt.returning(table.c[pk])).all())
                    else:
                        inserted += max(t.execute(stmt).rowcount or 0, 0)
                res.added = inserted
                res.there += len(new) - inserted
                if pk:
                    present.pop(table.name, None)
                    _bump_identity(t, table, pk)
            else:
                res.added = len(new) if dry_run else 0
                if pk and dry_run:  # the dry run counts children of rows it would add
                    present.setdefault(table.name, set(there)).update(r[pk] for r in new)
            results.append(res)
        if dry_run:
            t.rollback()
        else:
            t.commit()
    src.dispose()
    return {"dry_run": dry_run, "groups": groups, "tables": [r.out() for r in results],
            "added": sum(r.added for r in results), "left_out": sum(sum(r.skipped.values()) for r in results)}  # fmt: skip


def _parents_first(rows: list[dict], pk: str, self_fk: list[str]) -> list[dict]:
    by_id = {r[pk]: r for r in rows}
    ordered: list[dict] = []
    seen: set = set()

    def add(r: dict) -> None:
        if r[pk] in seen:
            return
        seen.add(r[pk])
        for c in self_fk:
            parent = by_id.get(r.get(c))
            if parent is not None and parent is not r:
                add(parent)
        ordered.append(r)

    for r in rows:
        add(r)
    return ordered


def _bump_identity(conn, table: Table, pk: str) -> None:
    """After rows with their own ids: the next new row gets a free id."""
    col = table.c[pk]
    if not (col.identity is not None or col.autoincrement is True or str(col.type).upper().startswith(("INTEGER", "BIGINT"))):
        return
    biggest = conn.execute(select(func.max(col))).scalar()
    if not isinstance(biggest, int):
        return
    is_identity = conn.execute(text("SELECT is_identity FROM information_schema.columns WHERE table_name = :t AND column_name = :c"), {"t": table.name, "c": pk}).scalar()
    if is_identity == "YES":
        conn.execute(text(f'ALTER TABLE "{table.name}" ALTER COLUMN "{pk}" RESTART WITH {biggest + 1}'))
    else:
        seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, :c)"), {"t": table.name, "c": pk}).scalar()
        if seq:
            conn.execute(text("SELECT setval(:s, :v)"), {"s": seq, "v": biggest})
