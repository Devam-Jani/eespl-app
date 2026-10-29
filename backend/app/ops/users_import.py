# ruff: noqa: E501
"""Users for go-live from an Excel template the app makes: name, email, phone, role(s), manager,
sites, tracked, travel eligible, rate per km. Every row is checked (the roles exist, the email is
new and not twice in the file, the manager is a user or a row above, the sites exist) and the
errors are listed before anything is saved; saving refuses while one row has an error. A person
already a user (same email) is left as they are, so a re-run adds nobody twice. Each new user
gets a one-time set-password link for the admin to copy and send (no email to anyone until
EMAIL_ENABLED)."""

import io
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import openpyxl
from openpyxl.styles import Font, PatternFill
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, User
from app.timefmt import ist_today

COLUMNS = ["Name", "Email", "Phone", "Roles", "Manager (email)", "Sites (codes)", "Tracked (yes/no)", "Travel eligible (yes/no)", "Rate per km"]
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
YES = {"yes", "y", "true", "1"}
NO = {"no", "n", "false", "0", ""}


@dataclass
class Row:
    row: int
    name: str
    email: str
    phone: str | None
    roles: list[str]
    manager: str | None
    sites: list[str]
    tracked: bool
    travel: bool
    rate: Decimal | None
    errors: list[str] = field(default_factory=list)
    exists: bool = False

    def out(self) -> dict:
        return {"row": self.row, "name": self.name, "email": self.email, "roles": self.roles, "manager": self.manager, "sites": self.sites,
                "tracked": self.tracked, "travel": self.travel, "rate": self.rate, "errors": self.errors, "status": "error" if self.errors else "already a user" if self.exists else "new"}  # fmt: skip


def template(db: Session) -> bytes:
    """The template with a sheet of the roles and one of the active sites to copy from."""
    from app.sites.models import Site  # noqa: PLC0415

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Users"
    ws.append(COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E6F2EF")
    ws.append(["(example, delete this row) Sales Executive One", "sales.one@example.com", "+91 90000 00000", "sales", "manager@example.com", "S-2026-0001", "yes", "yes", "3.50"])
    for col, width in zip("ABCDEFGHI", (30, 30, 18, 24, 26, 24, 16, 22, 12), strict=True):
        ws.column_dimensions[col].width = width
    rs = wb.create_sheet("Roles")
    rs.append(["Code (use in Roles)", "Role"])
    for r in db.scalars(select(Role).where(Role.code != "client").order_by(Role.name)):
        rs.append([r.code, r.name])
    ss = wb.create_sheet("Sites")
    ss.append(["Code (use in Sites)", "Site", "Status"])
    for s in db.scalars(select(Site).where(Site.status.in_(("active", "planned", "on_hold")), Site.is_demo.is_(False)).order_by(Site.code)):
        ss.append([s.code, s.name, s.status])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _split(v) -> list[str]:
    return [x.strip() for x in re.split(r"[,;/\n]+", _text(v)) if x.strip()]


def read(db: Session, data: bytes) -> list[Row]:
    """Every row of the Users sheet, checked; nothing is saved."""
    from app.sites.models import Site  # noqa: PLC0415

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Not an Excel file made from the template") from exc
    ws = wb["Users"] if "Users" in wb.sheetnames else wb.active
    it = ws.iter_rows(values_only=True)
    header = [_text(h).lower() for h in next(it, [])]
    if not header or not header[0].startswith("name") or "email" not in header[1]:
        raise ValueError("The first row must be the template's headings (Name, Email, ...)")
    roles = {r.code.lower(): r.code for r in db.scalars(select(Role))} | {r.name.lower(): r.code for r in db.scalars(select(Role))}
    sites = {s.code.lower(): s.code for s in db.scalars(select(Site).where(Site.is_demo.is_(False)))}
    taken = {e.lower() for e in db.scalars(select(User.email).where(User.email.is_not(None)))}
    rows: list[Row] = []
    seen: set[str] = set()
    for n, values in enumerate(it, start=2):
        v = list(values) + [None] * (len(COLUMNS) - len(values))
        if not any(_text(x) for x in v[: len(COLUMNS)]) or _text(v[0]).lower().startswith("(example"):
            continue
        email = _text(v[1]).lower()
        r = Row(row=n, name=_text(v[0]), email=email, phone=_text(v[2]) or None, roles=[], manager=_text(v[4]).lower() or None, sites=[], tracked=False, travel=False, rate=None)
        if not r.name:
            r.errors.append("no name")
        if not EMAIL.match(email):
            r.errors.append("not an email address")
        elif email in seen:
            r.errors.append("this email is in the file twice")
        elif email in taken:
            r.exists = True
        seen.add(email)
        for code in _split(v[3]):
            known = roles.get(code.lower())
            if known is None or known == "client":
                r.errors.append(f"no role '{code}' (see the Roles sheet)")
            elif known not in r.roles:
                r.roles.append(known)
        if not _split(v[3]):
            r.errors.append("no role")
        if r.manager and r.manager not in taken and r.manager not in seen:
            r.errors.append(f"the manager {r.manager} is not a user nor a row above")
        for code in _split(v[5]):
            if code.lower() not in sites:
                r.errors.append(f"no site '{code}' (see the Sites sheet)")
            else:
                r.sites.append(sites[code.lower()])
        for i, attr in ((6, "tracked"), (7, "travel")):
            t = _text(v[i]).lower()
            if t in YES:
                setattr(r, attr, True)
            elif t not in NO:
                r.errors.append(f"{COLUMNS[i]}: write yes or no")
        if _text(v[8]):
            try:
                r.rate = Decimal(_text(v[8]))
                if r.rate < 0 or r.rate > 100:
                    r.errors.append("rate per km out of range")
            except InvalidOperation:
                r.errors.append("rate per km is not a number")
        if r.travel and r.rate is None:
            r.errors.append("travel eligible needs a rate per km")
        rows.append(r)
    if not rows:
        raise ValueError("No user rows in the file")
    return rows


def save(db: Session, rows: list[Row], by_user) -> list[dict]:
    """The new users (only when no row has an error): their roles, sites, tracking and rate, and a
    one-time set-password link each. People already users are left as they are."""
    from app.auth.account import make_link  # noqa: PLC0415
    from app.field.models import TrackingProfile, TravelRate  # noqa: PLC0415
    from app.sites.models import Site, SiteMember  # noqa: PLC0415

    bad = [r for r in rows if r.errors]
    if bad:
        raise ValueError(f"{len(bad)} row(s) have errors: nothing saved")
    roles = {r.code: r for r in db.scalars(select(Role))}
    out = []
    made: dict[str, User] = {}
    for r in rows:
        if r.exists:
            out.append({"row": r.row, "name": r.name, "email": r.email, "status": "already a user", "link": None})
            continue
        u = User(email=r.email, full_name=r.name, phone=r.phone, is_active=True, roles=[roles[c] for c in r.roles])
        db.add(u)
        db.flush()
        made[r.email] = u
        for code in r.sites:
            site = db.scalar(select(Site).where(Site.code == code))
            db.add(SiteMember(site_id=site.id, user_id=u.id, role_on_site=_member_role(r.roles)))
        if r.tracked or r.travel or r.manager:
            mgr = made.get(r.manager) or (db.scalar(select(User).where(func.lower(User.email) == r.manager)) if r.manager else None)
            db.add(TrackingProfile(user_id=u.id, tracked=r.tracked, reimbursable=r.travel, manager_id=mgr.id if mgr else None, created_by=by_user))
        if r.rate is not None:
            db.add(TravelRate(user_id=u.id, rate_per_km=r.rate, valid_from=ist_today(), created_by=by_user))
        out.append({"row": r.row, "name": r.name, "email": r.email, "status": "new", "link": make_link(db, u, by_user)})
    db.flush()
    return out


def _member_role(roles: list[str]) -> str:
    """The person's role on the site from their job."""
    if "site_engineer" in roles:
        return "incharge"
    if "site_supervisor" in roles:
        return "supervisor"
    if "sales" in roles:
        return "sales"
    if "site_receiver" in roles:
        return "receiver"
    return "office" if {"billing", "planning", "accounts", "office_admin"} & set(roles) else "viewer"
