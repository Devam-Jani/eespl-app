# ruff: noqa: E501, S608
"""The load test: a copy of the database filled past go-live size (150 sites with their towers,
floors, flats and areas, 50 users, 200,000 daily-report lines and measurements, 20,000 small
photos), then every main list and dashboard timed through the API as the director would open it.
Invented rows only, named LOAD and marked demo; run on a copy, never on the real database.

    python -m app.ops.loadtest fill            # DATABASE_URL = the copy (eespl_load), MEDIA_DIR = a scratch folder
    python -m app.ops.loadtest time [--json]   # the pages, slowest first
"""

import json
import random
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.config import settings

SITES, USERS, DPR_LINES, MEASUREMENTS, PHOTOS = 150, 50, 100_000, 100_000, 20_000
ROLES = [
    "site_engineer",
    "site_supervisor",
    "sales",
    "billing",
    "planning",
    "accounts",
    "store_purchase",
    "estimator",
]
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 300 + b"\xff\xd9"  # a small invented file


def _copy(conn, table: str, cols: list[str], rows) -> int:
    raw = conn.connection.dbapi_connection
    n = 0
    with raw.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row(r)
            n += 1
    return n


def fill() -> dict:
    from app.db import engine  # noqa: PLC0415

    if settings.database_url.endswith("/eespl") or "eespl_load" not in settings.database_url:
        raise SystemExit("Run on the copy only: DATABASE_URL must point at eespl_load")
    rnd = random.Random(2026)
    out: dict = {}
    media = Path(settings.media_dir)
    with engine.begin() as conn:
        role_ids = dict(conn.execute(text("SELECT code, id FROM roles")).all())
        users = [uuid.uuid4() for _ in range(USERS)]
        out["users"] = _copy(conn, "users", ["id", "email", "full_name", "is_active", "is_demo"],
                             ((u, f"load-user-{i + 1}@example.com", f"LOAD User {i + 1}", True, True) for i, u in enumerate(users)))  # fmt: skip
        _copy(
            conn,
            "user_roles",
            ["user_id", "role_id"],
            ((u, role_ids[ROLES[i % len(ROLES)]]) for i, u in enumerate(users)),
        )
        start = conn.execute(text("SELECT coalesce(max(id), 0) FROM sites")).scalar() + 1
        out["sites"] = _copy(conn, "sites", ["id", "code", "name", "status", "is_demo", "state", "city", "start_date", "progress_percent"],
                             ((start + i, f"L-{i + 1:04d}", f"LOAD Site {i + 1}", "active", True, "Gujarat", "Ahmedabad", date(2026, 1, 1) + timedelta(days=i), rnd.randint(0, 100))
                              for i in range(SITES)))  # fmt: skip
        conn.execute(text(f"ALTER TABLE sites ALTER COLUMN id RESTART WITH {start + SITES}"))
        site_ids = list(range(start, start + SITES))
        _copy(
            conn,
            "site_members",
            ["site_id", "user_id", "role_on_site"],
            (
                (s, users[(s + k) % USERS], "incharge" if k == 0 else "viewer")
                for s in site_ids
                for k in range(3)
            ),
        )
        # places: 2 towers x 10 floors x 4 flats x 3 areas per site
        nid = conn.execute(text("SELECT coalesce(max(id), 0) FROM site_nodes")).scalar() + 1
        nodes, areas = [], {}
        for s in site_ids:
            for t in range(2):
                tid = nid
                nodes.append((tid, s, None, "tower", f"Tower {chr(65 + t)}", t))
                nid += 1
                for f in range(10):
                    fid = nid
                    nodes.append((fid, s, tid, "floor", f"Floor {f + 1}", f))
                    nid += 1
                    for fl in range(4):
                        flid = nid
                        nodes.append((flid, s, fid, "flat", f"Flat {f + 1}0{fl + 1}", fl))
                        nid += 1
                        for k, kind in enumerate(("toilet", "balcony", "kitchen")):
                            nodes.append((nid, s, flid, kind, kind.title(), k))
                            areas.setdefault(s, []).append(nid)
                            nid += 1
        out["site_nodes"] = _copy(
            conn, "site_nodes", ["id", "site_id", "parent_id", "kind", "name", "sort_order"], nodes
        )
        conn.execute(text(f"ALTER TABLE site_nodes ALTER COLUMN id RESTART WITH {nid}"))
        # daily reports: 200 days a site, about 3 lines each
        did = conn.execute(text("SELECT coalesce(max(id), 0) FROM dprs")).scalar() + 1
        dprs = [
            (did + i, s, date(2026, 3, 1) + timedelta(days=d), "acknowledged")
            for i, (s, d) in enumerate((s, d) for s in site_ids for d in range(200))
        ]
        out["dprs"] = _copy(conn, "dprs", ["id", "site_id", "on_date", "status"], dprs)
        conn.execute(text(f"ALTER TABLE dprs ALTER COLUMN id RESTART WITH {did + len(dprs)}"))
        out["dpr_lines"] = _copy(
            conn,
            "dpr_lines",
            ["dpr_id", "description"],
            ((rnd.choice(dprs)[0], f"LOAD work line {i}") for i in range(DPR_LINES)),
        )
        out["measurements"] = _copy(conn, "measurements", ["site_id", "node_id", "description", "qty", "unit", "source", "measured_on", "status"],
                                    ((s := rnd.choice(site_ids), rnd.choice(areas[s]), f"LOAD measurement {i}", round(rnd.uniform(1, 30), 3), "sqm", "manual",
                                      date(2026, 3, 1) + timedelta(days=rnd.randint(0, 199)), rnd.choice(("approved", "approved", "draft", "sent")))
                                     for i in range(MEASUREMENTS)))  # fmt: skip
        folder = media / "load"
        folder.mkdir(parents=True, exist_ok=True)
        photos = []
        for i in range(PHOTOS):
            name = f"load-{i:05d}.jpg"
            (folder / name).write_bytes(JPEG)
            photos.append((rnd.choice(dprs)[0], f"load/{name}", name))
        out["dpr_photos"] = _copy(conn, "dpr_photos", ["dpr_id", "stored_path", "filename"], photos)
        conn.execute(text("ANALYZE"))
        out["director"] = users[0]
        conn.execute(
            text("UPDATE user_roles SET role_id = :r WHERE user_id = :u"),
            {"r": role_ids["director"], "u": users[0]},
        )
        conn.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
            {"r": role_ids["office_admin"], "u": users[0]},
        )  # the Users page too
    return {k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in out.items()}


# the pages: what each main list and dashboard calls when it opens ({site} = a LOAD site)
PAGES = [
    ("My work", "/api/team/my-work"), ("Notifications", "/api/notifications"), ("Dashboard", "/api/dashboard"), ("Alerts", "/api/analytics/alerts"),
    ("Sites", "/api/sites?limit=50"), ("A site", "/api/sites/{site}"), ("A site's tasks", "/api/sites/{site}/tasks"), ("A site's handover", "/api/schedule/sites/{site}/handover"),
    ("Site status board", "/api/team/board"), ("Daily reports", "/api/execution/dprs?days=14"), ("Missing daily reports", "/api/execution/dprs/missing"),
    ("Measurement book", "/api/team/measurements?site_id={site}"), ("Measure (site)", "/api/closeout/sites/{site}/measurements"),
    ("Billing checklist", "/api/closeout/sites/{site}/billing-checklist"), ("Bills", "/api/closeout/bills"), ("Payment follow-up", "/api/closeout/bills?overdue=true"),
    ("Issue log", "/api/closeout/issues"), ("Guarantees", "/api/closeout/guarantees"), ("Work orders", "/api/closeout/work-orders"), ("Client bill tracking", "/api/team/bill-tracking"),
    ("Leads", "/api/leads?limit=50"), ("Tenders", "/api/tenders?limit=50"), ("Quotations", "/api/quotations?limit=50"), ("Clients", "/api/clients"), ("Vendors", "/api/vendors"),
    ("Products", "/api/products?limit=50"), ("Indents", "/api/material/indents"), ("Purchase orders", "/api/material/pos"), ("GRNs", "/api/material/grns"),
    ("Stores", "/api/material/stores"), ("Transfers", "/api/material/transfers?limit=200"), ("Invoices", "/api/finance/invoices"), ("Receipts", "/api/finance/receipts"),
    ("Vendor bills", "/api/finance/vendor-bills"), ("Payroll", "/api/finance/payroll"), ("Ageing", "/api/finance/ageing"), ("Site profit", "/api/finance/profit"),
    ("Labour", "/api/execution/labour"), ("Inspections", "/api/execution/inspections"), ("Team map", "/api/field/team"), ("Users", "/api/users"),
    ("Audit log", "/api/audit"), ("Backups and storage", "/api/ops/backups"), ("Roles report", "/api/ops/roles-report"),
]  # fmt: skip


def time_pages(repeat: int = 3) -> list[dict]:
    from fastapi.testclient import TestClient  # noqa: PLC0415

    import app.main as main  # noqa: PLC0415
    from app.auth.security import create_access_token  # noqa: PLC0415
    from app.db import engine  # noqa: PLC0415

    with engine.connect() as conn:
        director = conn.execute(
            text(
                "SELECT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles r ON r.id = ur.role_id WHERE r.code = 'director' AND u.email LIKE 'load-user-%' LIMIT 1"
            )
        ).scalar()
        site = conn.execute(text("SELECT id FROM sites WHERE code = 'L-0075'")).scalar()
    c = TestClient(main.app)
    h = {"Authorization": f"Bearer {create_access_token(director)}"}
    rows = []
    for name, path in PAGES:
        url = path.format(site=site)
        c.get(url, headers=h)  # warm
        times = []
        status = None
        for _ in range(repeat):
            t0 = time.perf_counter()
            r = c.get(url, headers=h)
            times.append(time.perf_counter() - t0)
            status = r.status_code
        rows.append(
            {
                "page": name,
                "api": url,
                "seconds": round(min(times), 3),
                "status": status,
                "bytes": len(r.content),
            }
        )
    return sorted(rows, key=lambda r: -r["seconds"])


def main(argv: list[str]) -> int:
    if argv[:1] == ["fill"]:
        print(json.dumps(fill(), indent=1))
    elif argv[:1] == ["time"]:
        rows = time_pages()
        if "--json" in argv:
            print(json.dumps(rows, indent=1))
        else:
            for r in rows:
                print(f"{r['seconds']:7.3f} s  {r['status']}  {r['page']:24} {r['api']}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
