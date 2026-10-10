"""Admin command line.

    docker compose exec api python -m app.cli create-admin --email you@example.com --name "Name"
    docker compose exec api python -m app.cli set-password --email you@example.com
    docker compose exec api python -m app.cli import-library /data/<rate library>.xlsx
    docker compose exec api python -m app.cli import-tc /data/tc_clauses.json
    docker compose exec api python -m app.cli import-powerplay-materials /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli import-powerplay-vendors /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli import-powerplay-team /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli backtest-rates [--set-default]
    docker compose exec api python -m app.cli kylas-discover
    docker compose exec api python -m app.cli import-powerplay-projects /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli import-offer data/samples/offer-ladani.docx
    docker compose exec api python -m app.cli make-offer-template

The password is prompted for (twice) when run in a terminal. When stdin is not a terminal,
one line is read from stdin instead, so scripts can pipe it in without it appearing in argv.
"""

import argparse
import getpass
import sys
from collections import Counter

from sqlalchemy import select

from app import audit
from app.auth.rbac import SUPER_ADMIN_ROLE_CODE
from app.auth.security import MIN_PASSWORD_LENGTH, hash_password
from app.db import SessionLocal
from app.masters.importers import ImportFormatError, Skipped, import_library, import_tc
from app.masters.powerplay import (
    PowerplayFormatError,
    import_materials,
    import_team,
    import_vendors,
)
from app.models import Role, User


def _read_password() -> str:
    if sys.stdin.isatty():
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            sys.exit("Passwords do not match.")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


def create_admin(email: str, name: str, phone: str | None) -> None:
    email = email.strip().lower()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            sys.exit(f"A user with email {email} already exists.")
        role = db.scalar(select(Role).where(Role.code == SUPER_ADMIN_ROLE_CODE))
        if role is None:
            sys.exit("The super_admin role is missing. Run `alembic upgrade head` first.")
        user = User(
            email=email,
            full_name=name.strip(),
            phone=phone,
            password_hash=hash_password(_read_password()),
            roles=[role],
        )
        db.add(user)
        db.flush()
        audit.record(
            db, "user.create", "user", user.id, after={**audit.user_snapshot(user), "via": "cli"}
        )
        db.commit()
        print(f"Created super admin {email} ({user.id}).")


def set_password(email: str) -> None:
    email = email.strip().lower()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            sys.exit(f"No user with email {email}.")
        user.password_hash = hash_password(_read_password())
        user.failed_logins = 0
        user.locked_until = None
        audit.record(db, "user.password_reset", "user", user.id, after={"via": "cli"})
        db.commit()
        print(f"Password updated for {email}.")


def _print_skipped(skipped: list[Skipped], show: int = 20) -> None:
    print(f"Skipped rows: {len(skipped)}")
    for reason, count in Counter(s.reason.split(" of row")[0] for s in skipped).most_common():
        print(f"  {count:>6}  {reason}")
    for s in skipped[:show]:
        print(f"         {s.sheet} row {s.row}: {s.reason}")


def run_import_library(path: str) -> None:
    with SessionLocal() as db:
        try:
            r = import_library(db, path)
        except (ImportFormatError, FileNotFoundError) as exc:
            sys.exit(f"Import failed: {exc}")
    print(
        f"Library items: {r.items_in_file} in file "
        f"({r.items_inserted} new, {r.items_updated} already present, {r.items_deleted} removed)"
    )
    print(
        f"Library lines: {r.lines_in_file} in file "
        f"({r.lines_inserted} new, {r.lines_updated} already present, {r.lines_deleted} removed)"
    )
    print(
        f"  linked to an item: {r.lines_linked} "
        f"({r.lines_linked_via_parent} via '<parent item> — <description>')"
    )
    print(f"  not linked (no item with the same description and unit): {r.lines_unlinked}")
    if r.ambiguous_match_keys:
        print(
            f"  items sharing a description+unit after unit normalisation: "
            f"{r.ambiguous_match_keys} (lines link to the one in most BOQs)"
        )
    excluded = sum(r.items_excluded.values())
    print(
        f"Items hidden from search by default: {excluded} excluded, "
        f"{r.items_competitor} competitor"
    )
    for reason, count in sorted(r.items_excluded.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>6}  excluded: {reason}")
    print(
        f"Lines flagged: {r.lines_excluded} excluded, {r.lines_competitor} competitor; "
        f"{r.items_stats_from_lines} items have stats recomputed without them (or after merges)"
    )
    if r.unrecognised_units:
        top = ", ".join(f"{u!r} x{n}" for u, n in list(r.unrecognised_units.items())[:12])
        print(f"Units not recognised (stored as blank unit, raw text kept): {top}")
    _print_skipped(r.skipped)


def run_import_tc(path: str) -> None:
    with SessionLocal() as db:
        try:
            r = import_tc(db, path)
        except (ImportFormatError, FileNotFoundError, ValueError) as exc:
            sys.exit(f"Import failed: {exc}")
    print(
        f"T&C clauses: {r.clauses_in_file} in file "
        f"({r.clauses_inserted} new, {r.clauses_updated} already present)"
    )
    state = "created" if r.template_created else "already exists, left unchanged"
    print(f"Template 'EESPL Standard': {state} ({r.template_clauses} clauses)")
    _print_skipped(r.skipped)


POWERPLAY = {
    "import-powerplay-materials": (import_materials, "materials -> products"),
    "import-powerplay-vendors": (import_vendors, "vendors"),
    "import-powerplay-team": (import_team, "team members -> inactive users, no password"),
}


def run_import_powerplay(command: str, path: str) -> None:
    importer, label = POWERPLAY[command]
    with SessionLocal() as db:
        try:
            r = importer(db, path)
        except (PowerplayFormatError, FileNotFoundError) as exc:
            sys.exit(f"Import failed: {exc}")
    print(f"Powerplay {label}: sheet {r.sheet!r}")
    print(f"  header row: {r.header}")
    print("  columns used: " + ", ".join(f"{k} <- {v!r}" for k, v in r.mapping.items()))
    print(
        f"  rows: {r.rows_in_file}; created {r.created}; already present {r.already_present}; "
        f"duplicates merged {r.duplicates_merged}; skipped {len(r.skipped)}"
    )
    if r.categories_created:
        print(f"  material categories created: {', '.join(r.categories_created)}")
    for number, reason in r.skipped[:30]:
        print(f"  skipped row {number}: {reason}")
    for number, warning in r.warnings[:30]:
        print(f"  warning row {number}: {warning}")


def run_backtest(set_default: bool) -> None:
    """Leave-one-BOQ-out comparison of the rate policies on the imported library."""
    from sqlalchemy import func

    from app.masters.models import CompanyProfile, LibraryLine
    from app.masters.rate_policy import POLICIES, UNAVAILABLE, backtest, load_histories, winner

    with SessionLocal() as db:
        total = db.scalar(select(func.count()).where(LibraryLine.rate.is_not(None)))
        unlinked = db.scalar(
            select(func.count()).where(
                LibraryLine.rate.is_not(None),
                LibraryLine.library_item_id.is_(None),
                ~LibraryLine.is_competitor,
                ~LibraryLine.is_excluded,
            )
        )
        flagged = db.scalar(
            select(func.count()).where(
                LibraryLine.rate.is_not(None), LibraryLine.is_competitor | LibraryLine.is_excluded
            )
        )
        histories = load_histories(db)
        files = {o.file for h in histories.values() for o in h.lines}
        print(
            f"Library lines with a rate: {total}; left out: {flagged} competitor/excluded; "
            f"{unlinked} without a library item (count as not suggested)"
        )
        print(f"Items: {len(histories)}; BOQ files: {len(files)}")
        for reason in UNAVAILABLE.values():
            print(f"Skipped: {reason}")
        rows = backtest(histories, unlinked=unlinked)
        print()
        print("| Policy | ±5% | ±10% | ±20% | Median abs error % | Above quote >10% | Coverage % |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for r in rows:
            print(
                f"| {POLICIES[r['policy']]} ({r['policy']}) | {r['within_5']} | "
                f"{r['within_10']} | {r['within_20']} | {r['median_abs_error']} | "
                f"{r['above_by_10']} | {r['coverage']} |"
            )
        best = winner(rows)
        print()
        print(
            f"Lines scored: {rows[0]['lines']}. "
            f"Winner (most within ±10%, then fewest over-quotes): {best}"
        )
        if set_default:
            profile = db.get(CompanyProfile, 1)
            if profile is not None:
                before = profile.rate_policy
                profile.rate_policy = best
                audit.record(
                    db,
                    "company.update",
                    "company",
                    1,
                    before={"rate_policy": before},
                    after={"rate_policy": best},
                )
                db.commit()
                print(f"Company default rate policy: {before} -> {best}")


def run_import_projects(paths: list[str]) -> None:
    """Past Powerplay projects as closed sites (see app.sites.powerplay_projects)."""
    import glob
    from pathlib import Path

    from app.sites.powerplay_projects import import_projects

    files = sorted(
        {p for pattern in paths for p in glob.glob(pattern)}
        | {p for p in paths if Path(p).exists()}
    )
    if not files:
        print(f"file not found: {' '.join(paths)}")
        sys.exit(1)
    with SessionLocal() as db:
        for path in files:
            try:
                result = import_projects(db, path)
            except ValueError as exc:
                print(f"{Path(path).name}: {exc}")
                sys.exit(1)
            audit.record(
                db,
                "import.powerplay_projects",
                "site",
                None,
                after={
                    "file": Path(path).name,
                    "rows": result.rows,
                    "imported": len(result.imported),
                    "already": result.already,
                    "skipped": len(result.skipped),
                    "merged": result.merged,
                    "near_duplicates": result.near_duplicates,
                },
            )
            db.commit()
            print(f"{Path(path).name}: {result.rows} projects read")
            print(
                f"  imported as closed sites: {len(result.imported)}; already there: "
                f"{result.already}"
            )
            print(f"  skipped ({len(result.skipped)}):")
            for name, reason in result.skipped:
                print(f"    - {name!r}: {reason}")
            print(f"  merged exact duplicates ({len(result.merged)}):")
            for name, n in result.merged:
                print(f"    - {name!r} x{n}")
            print(f"  near-duplicates kept separate, flagged ({len(result.near_duplicates)}):")
            for a, b in result.near_duplicates:
                print(f"    - {a!r} / {b!r}")


def run_kylas_discover() -> None:
    """Ids and names of Kylas lead sources, users, deal pipelines and their stages: nothing else
    (no emails, phones or keys), for Settings > Integrations > Kylas. Read-only GETs."""
    from app.crm import kylas_client

    kylas = kylas_client.client()
    if not kylas.is_configured:
        print("KYLAS_API_KEY is not set in .env: nothing to discover")
        return
    sections = (
        ("Sources (lead source picklist)", kylas_client.lead_sources),
        ("Users", kylas_client.users),
        ("Deal pipelines and stages", kylas_client.deal_pipelines),
    )
    for title, lookup in sections:
        print(f"{title}:")
        found = lookup(kylas)
        if not found.ok:
            print(f"  (no answer: HTTP {found.status_code})")
            continue
        for item in found.items:
            flag = "  (inactive)" if item.get("active") is False else ""
            print(f"  {item['id']}  {item['name']}{flag}")
            for stage in item.get("stages") or []:
                print(f"      stage {stage['id']}  {stage['name']}")


def run_import_offer(path: str, again: bool, preset: str | None = None) -> None:
    """A hand-made techno-commercial offer (.docx) -> the quotation libraries. A path under data/
    is read from the /data mount (where the company files live in the container)."""
    from pathlib import Path

    import app.main  # noqa: F401  (every model, for the foreign keys)
    from app.quotations.importer import import_offer

    p = Path(path)
    if not p.exists() and Path("/" + path).exists():
        p = Path("/" + path)
    if not p.exists():
        sys.exit(f"Not found: {path}")
    with SessionLocal() as db:
        try:
            res = import_offer(db, p, again=again, preset=preset)
        except ValueError as e:
            sys.exit(str(e))
        audit.record(
            db,
            "quotation.import_offer",
            "quotation_library",
            None,
            user_id=None,
            after={**res.counts, "file": p.name},
        )
        db.commit()
    print(f"Imported {p.name} into the quotation libraries (every row marked 'imported, check'):")
    for k, v in res.counts.items():
        print(f"  {k}: {v}")
    print("Typos fixed:")
    for k, v in res.fixes.items():
        print(f"  {k}: {v}")
    for n in res.notes:
        print(f"Note: {n}")


def run_make_offer_template() -> None:
    from app.quotations.docx_out import TEMPLATE, make_template

    make_template(TEMPLATE)
    print(f"Wrote the default Word template with the offer styles: {TEMPLATE}")


def run_demo(purge: bool, sites: int, leads: int) -> None:
    from app.analytics import demo

    with SessionLocal() as db:
        if purge:
            removed = demo.purge(db)
            print(f"Demo data removed: {sum(removed.values())} rows")
            for table, n in sorted(removed.items()):
                print(f"  {table}: {n}")
            return
        try:
            made = demo.seed(db, sites=sites, leads=leads)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Demo data created (invented, is_demo): {sum(made.values())} rows")
        for table, n in made.items():
            print(f"  {table}: {n}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create a user with the super_admin role")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--phone")

    p = sub.add_parser("set-password", help="Set a user's password and clear any lockout")
    p.add_argument("--email", required=True)

    p = sub.add_parser("import-library", help="Import the historical rate library workbook")
    p.add_argument("path")

    p = sub.add_parser("import-tc", help="Import T&C clauses and the default template")
    p.add_argument("path")

    sub.add_parser("kylas-discover", help="Print Kylas source / user / pipeline / stage ids")

    p = sub.add_parser(
        "import-powerplay-projects", help="Import past Powerplay projects as closed sites"
    )
    p.add_argument("paths", nargs="+")

    p = sub.add_parser(
        "backtest-rates", help="Compare rate policies on the library (leave-one-BOQ-out)"
    )
    p.add_argument("--set-default", action="store_true", help="Make the winner the company default")

    p = sub.add_parser(
        "seed-demo-analytics", help="Create (or --purge) the invented demo company (dashboards)"
    )
    p.add_argument("--purge", action="store_true", help="Delete every demo row and nothing else")
    p.add_argument("--sites", type=int, default=60)
    p.add_argument("--leads", type=int, default=400)

    p = sub.add_parser(
        "import-offer", help="Import a techno-commercial offer .docx into the quotation libraries"
    )
    p.add_argument("path")
    p.add_argument(
        "--again", action="store_true", help="Import a second copy (a new letterhead name)"
    )
    p.add_argument(
        "--preset", help="Also save the imported items as an offer preset with this name"
    )

    sub.add_parser("make-offer-template", help="Write the default Word template for quotations")
    sub.add_parser(
        "seed-demo-team",
        help="One invented demo user per role (password from DEMO_USER_PASSWORD in .env)",
    )

    for command, (_, label) in POWERPLAY.items():
        p = sub.add_parser(command, help=f"Import a Powerplay Excel export: {label}")
        p.add_argument("path")

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        create_admin(args.email, args.name, args.phone)
    elif args.command == "set-password":
        set_password(args.email)
    elif args.command == "import-library":
        run_import_library(args.path)
    elif args.command == "import-tc":
        run_import_tc(args.path)
    elif args.command == "kylas-discover":
        run_kylas_discover()
    elif args.command == "import-powerplay-projects":
        run_import_projects(args.paths)
    elif args.command == "backtest-rates":
        run_backtest(args.set_default)
    elif args.command == "seed-demo-analytics":
        run_demo(args.purge, args.sites, args.leads)
    elif args.command == "import-offer":
        run_import_offer(args.path, args.again, args.preset)
    elif args.command == "make-offer-template":
        run_make_offer_template()
    elif args.command == "seed-demo-team":
        from app.team.demo import seed  # noqa: PLC0415

        with SessionLocal() as db:
            for line in seed(db):
                print(line)
        print("Password: DEMO_USER_PASSWORD from .env (not shown).")
    elif args.command in POWERPLAY:
        run_import_powerplay(args.command, args.path)
