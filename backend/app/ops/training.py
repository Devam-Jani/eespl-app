# ruff: noqa: E501
"""The training company: the same app on its own database (training.APP_DOMAIN), where people
practise without touching real data. Every night it is rebuilt: the database emptied and migrated,
the DEMO data loaded (the DEMO sites, tenders, bills, close-out), and the real users' logins copied
from the production database (the same password works; their roles too) and made members of the
DEMO sites so each role has something to work on. Nothing goes back to the real database, no email
is sent (EMAIL_ENABLED is off here) and Kylas is off.

    python -m app.cli training-reset [--if-empty]     # on the training api (TRAINING_MODE=true)
"""

import logging
import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, select, text

from app.config import settings

log = logging.getLogger("eespl.training")
STEPS = ("analytics", "team", "field", "closeout", "measure", "estimate")  # all but analytics use the team's DEMO people


def _require_training() -> None:
    if not settings.training_mode:
        raise SystemExit("Only on the training company's api (TRAINING_MODE=true): this empties its database")


def _empty_and_migrate() -> None:
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    engine = create_engine(settings.database_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    command.upgrade(cfg, "head")


def _seed_demo() -> dict:
    """The DEMO data, step by step (a step that fails is reported, the others still run)."""
    import app.main  # noqa: F401, PLC0415  (every model registered)
    from app.db import SessionLocal  # noqa: PLC0415

    done: dict[str, str] = {}
    for step in STEPS:
        try:
            with SessionLocal() as db:
                if step == "analytics":
                    from app.analytics import demo  # noqa: PLC0415

                    demo.seed(db, sites=12, leads=60)
                elif step == "field":
                    from app.field.demo import seed  # noqa: PLC0415

                    seed(db)
                elif step == "team":
                    from app.team.demo import seed  # noqa: PLC0415

                    seed(db)
                elif step == "closeout":
                    from app.closeout import demo as cdemo  # noqa: PLC0415

                    cdemo.run(db)
                elif step == "measure":
                    from app.measure import demo as mdemo  # noqa: PLC0415

                    mdemo.run(db)
                elif step == "estimate":
                    from app.estimate import demo as edemo  # noqa: PLC0415

                    edemo.run(db)
                db.commit()
            done[step] = "ok"
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            log.exception("training seed %s failed", step)
            done[step] = f"failed: {type(exc).__name__}: {exc}"[:300]
    return done


def copy_users(main_url: str) -> int:
    """The real users' logins (name, email, password hash, roles; never their data) into the
    training company, members of the DEMO sites with their job's role there."""
    from app.db import SessionLocal  # noqa: PLC0415
    from app.models import Role, User  # noqa: PLC0415
    from app.ops.users_import import _member_role  # noqa: PLC0415
    from app.sites.models import Site, SiteMember  # noqa: PLC0415

    main = create_engine(main_url)
    with main.connect() as m:
        people = m.execute(text("SELECT id, email, full_name, phone, password_hash, job_title FROM users WHERE is_active AND NOT is_demo AND email IS NOT NULL")).all()
        roles = m.execute(text("SELECT ur.user_id, r.code FROM user_roles ur JOIN roles r ON r.id = ur.role_id")).all()
    main.dispose()
    by_user: dict = {}
    for uid, code in roles:
        by_user.setdefault(uid, []).append(code)
    n = 0
    with SessionLocal() as db:
        known = {r.code: r for r in db.scalars(select(Role))}
        demo_sites = list(db.scalars(select(Site).where(Site.is_demo)))
        for p in people:
            codes = [c for c in by_user.get(p.id, []) if c in known and c != "client"]
            if not codes or db.scalar(select(User.id).where(User.email == p.email)):
                continue
            u = User(id=p.id, email=p.email, full_name=p.full_name, phone=p.phone, password_hash=p.password_hash, job_title=p.job_title, is_active=True,
                     roles=[known[c] for c in codes])  # fmt: skip
            db.add(u)
            db.flush()
            for s in demo_sites:
                db.add(SiteMember(site_id=s.id, user_id=u.id, role_on_site=_member_role(codes)))
            n += 1
        db.commit()
    return n


def reset(if_empty: bool = False) -> dict:
    _require_training()
    if if_empty:
        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            has_users = conn.execute(text("SELECT to_regclass('public.users') IS NOT NULL")).scalar() and conn.execute(text("SELECT count(*) FROM users")).scalar()
        engine.dispose()
        if has_users:
            return {"skipped": "already set up"}
    started = datetime.now(UTC)
    _empty_and_migrate()
    seeded = _seed_demo()
    main_url = os.environ.get("MAIN_DATABASE_URL", "")
    users = copy_users(main_url) if main_url else 0
    from app.db import SessionLocal  # noqa: PLC0415
    from app.ops import service  # noqa: PLC0415

    out = {"reset_at": started.isoformat(), "seeded": seeded, "users_copied": users, "seconds": round((datetime.now(UTC) - started).total_seconds())}
    with SessionLocal() as db:
        service.put(db, "training", out)
        db.commit()
    return out
