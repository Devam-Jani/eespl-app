"""Admin command line.

    docker compose exec api python -m app.cli create-admin --email you@example.com --name "Name"
    docker compose exec api python -m app.cli set-password --email you@example.com

The password is prompted for (twice) when run in a terminal. When stdin is not a terminal,
one line is read from stdin instead, so scripts can pipe it in without it appearing in argv.
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app import audit
from app.auth.rbac import SUPER_ADMIN_ROLE_CODE
from app.auth.security import MIN_PASSWORD_LENGTH, hash_password
from app.db import SessionLocal
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="Create a user with the super_admin role")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--phone")

    p = sub.add_parser("set-password", help="Set a user's password and clear any lockout")
    p.add_argument("--email", required=True)

    args = parser.parse_args(argv)
    if args.command == "create-admin":
        create_admin(args.email, args.name, args.phone)
    elif args.command == "set-password":
        set_password(args.email)


if __name__ == "__main__":
    main()
