"""Admin command line.

    docker compose exec api python -m app.cli create-admin --email you@example.com --name "Name"
    docker compose exec api python -m app.cli set-password --email you@example.com
    docker compose exec api python -m app.cli import-library /data/<rate library>.xlsx
    docker compose exec api python -m app.cli import-tc /data/tc_clauses.json
    docker compose exec api python -m app.cli import-powerplay-materials /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli import-powerplay-vendors /data/powerplay/<file>.xlsx
    docker compose exec api python -m app.cli import-powerplay-team /data/powerplay/<file>.xlsx

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
    print(f"  rows: {r.rows_in_file}; created {r.created}; already present {r.already_present}; "
          f"duplicates merged {r.duplicates_merged}; skipped {len(r.skipped)}")
    if r.categories_created:
        print(f"  material categories created: {', '.join(r.categories_created)}")
    for number, reason in r.skipped[:30]:
        print(f"  skipped row {number}: {reason}")
    for number, warning in r.warnings[:30]:
        print(f"  warning row {number}: {warning}")


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
    elif args.command in POWERPLAY:
        run_import_powerplay(args.command, args.path)
