# ruff: noqa: E501
"""A clean production database for go-live: made empty, migrated (the migrations carry the seed:
roles and their permissions, units, categories, the settings rows, the letterheads, the process
rules), then checked to hold no DEMO row and no DEMO user. The real data comes after: the users
from the Excel template, the masters carried over from the development database.

    python -m app.cli go-live --database eespl [--admin-url postgresql+psycopg://...@db:5432/postgres]
"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, make_url, text

from app.config import settings

BACKEND = Path(__file__).resolve().parent.parent.parent
SEED_TABLES = ("roles", "permissions", "role_permissions", "units", "categories", "letterheads", "process_rules", "client_role_defs", "security_settings")


def url_for(database: str) -> str:
    return make_url(settings.database_url).set(database=database).render_as_string(hide_password=False)


def create(database: str) -> bool:
    """The database, made when missing. True when it was made now."""
    admin = create_engine(make_url(url_for("postgres")), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": database}).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{database}"'))
    admin.dispose()
    return not exists


def migrate(database: str) -> None:
    env = dict(os.environ, DATABASE_URL=url_for(database))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True, capture_output=True)


def demo_rows(database: str) -> dict[str, int]:
    """Rows marked DEMO, per table (is_demo, or a name / code / title starting with DEMO)."""
    engine = create_engine(url_for(database))
    out: dict[str, int] = {}
    with engine.connect() as conn:
        cols = conn.execute(text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name IN ('is_demo', 'name', 'code', 'title', 'full_name')")).all()
        by_table: dict[str, list[str]] = {}
        for t, c in cols:
            by_table.setdefault(t, []).append(c)
        for t, cs in by_table.items():
            conds = ["is_demo" if c == "is_demo" else f"upper(btrim({c}::text)) LIKE 'DEMO%'" for c in cs]
            n = conn.execute(text(f'SELECT count(*) FROM "{t}" WHERE ' + " OR ".join(conds))).scalar()
            if n:
                out[t] = n
    engine.dispose()
    return out


def seed_counts(database: str) -> dict[str, int]:
    engine = create_engine(url_for(database))
    with engine.connect() as conn:
        out = {t: conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in SEED_TABLES if conn.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{t}"}).scalar()}
    engine.dispose()
    return out


def run(database: str) -> dict:
    made = create(database)
    migrate(database)
    demo = demo_rows(database)
    seeds = seed_counts(database)
    return {"database": database, "made_now": made, "seed": seeds, "demo_rows": demo, "ok": not demo and bool(seeds.get("roles"))}
