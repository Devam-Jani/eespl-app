"""Demo team: one invented user per role (DEMO Planning, DEMO Billing ...), marked demo, the
site-based ones members of the DEMO Shela site. The password comes from DEMO_USER_PASSWORD in
.env and is never printed."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.auth.security import MIN_PASSWORD_LENGTH, hash_password
from app.config import settings
from app.models import Role, User
from app.sites.models import Site, SiteMember

# role code: (name, invented job title, member role on the demo site or None)
TEAM = {
    "director": ("DEMO Director", "Director", None),
    "office_admin": ("DEMO Office Admin", "Office Administrator", None),
    "planning": ("DEMO Planning", "Sr Engineer Billing & Planning", None),
    "billing": ("DEMO Billing", "Assistant Manager Billing", None),
    "accounts": ("DEMO Accounts", "Accounts Executive", None),
    "sales": ("DEMO Sales", "Sales Executive", "sales"),
    "estimator": ("DEMO Estimator", "Estimation Engineer", None),
    "site_engineer": ("DEMO Site Engineer", "Sr Engineer Site", "incharge"),
    "site_supervisor": ("DEMO Site Supervisor", "Sr Supervisor Site", "supervisor"),
    "store_purchase": ("DEMO Store", "Store & Purchase Executive", None),
}
DEMO_SITE_NAME = "%Shela%"


def email_for(role: str) -> str:
    return f"demo-{role.replace('_', '-')}@demo.invalid"


def seed(db: Session) -> list[str]:
    secret = settings.demo_user_password
    password = secret.get_secret_value() if secret else ""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit("Set DEMO_USER_PASSWORD in .env (at least the minimum password length).")
    pw_hash = hash_password(password)
    site = db.scalar(select(Site).where(Site.name.ilike(DEMO_SITE_NAME)).order_by(Site.id).limit(1))
    out = []
    for code, (name, title, on_site) in TEAM.items():
        role = db.scalar(select(Role).where(Role.code == code))
        if role is None:
            raise SystemExit(f"The {code} role is missing: run alembic upgrade head first.")
        user = db.scalar(select(User).where(User.email == email_for(code)))
        if user is None:
            user = User(email=email_for(code), full_name=name)
            db.add(user)
        user.full_name, user.job_title, user.is_demo, user.is_active = name, title, True, True
        user.password_hash, user.roles = pw_hash, [role]
        user.failed_logins, user.locked_until = 0, None
        db.flush()
        if on_site and site is not None:
            m = db.scalar(
                select(SiteMember).where(
                    SiteMember.site_id == site.id, SiteMember.user_id == user.id
                )
            )
            if m is None:
                db.add(SiteMember(site_id=site.id, user_id=user.id, role_on_site=on_site))
        audit.record(db, "user.demo_seed", "user", user.id, after={"role": code})
        out.append(
            f"{name} <{user.email}> {code}"
            + (f", member of {site.code}" if on_site and site else "")
        )
    db.commit()
    return out
