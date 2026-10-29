# ruff: noqa: E501
"""Prompt 39, Part 2: no site leaks. A site engineer and a site supervisor (site.view: assigned)
put on one site call every GET route that takes a site id with another site's id: each answers 403
or 404 (or a 200 that is the same for every site, listed in SAME_FOR_ALL with why)."""

import re

from fastapi.testclient import TestClient

from app.main import app
from app.sites.models import Site, SiteMember
from tests.conftest import login

# a 200 with another site's id that leaks nothing (checked by hand; the reason beside each)
SAME_FOR_ALL: dict[str, str] = {}
SITE_PARAM = re.compile(r"\{(site_id|sid)\}|^/api/sites/\{(id|site_id)\}")


def _site_routes() -> list[str]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        if "get" not in ops or not SITE_PARAM.search(path):
            continue
        params = re.findall(r"\{(\w+)\}", path)
        if len(params) != 1:  # only routes whose one id is the site's
            continue
        out.append(path)
    return sorted(out)


def test_an_assigned_role_gets_nothing_from_another_site(db, make_user):
    mine = Site(code="S-SWEEP-A", name="Invented site A", status="active")
    other = Site(code="S-SWEEP-B", name="Invented site B", status="active")
    db.add_all([mine, other])
    db.flush()
    assert len(_site_routes()) >= 60  # the sweep covers the site routes (73 on 29.10.2026)
    leaks: dict[str, list[str]] = {}
    for role in ("site_engineer", "site_supervisor"):
        u = make_user(f"{role.replace('_', '-')}-sweep@example.com", role)
        db.add(SiteMember(site_id=mine.id, user_id=u.id, role_on_site="incharge" if role == "site_engineer" else "supervisor"))
        db.commit()
        c = TestClient(app)
        h = login(c, u.email)
        for path in _site_routes():
            if path in SAME_FOR_ALL:
                continue
            url = re.sub(r"\{\w+\}", str(other.id), path)
            r = c.get(url, headers=h)
            if r.status_code == 200:
                leaks.setdefault(path, []).append(role)
            assert r.status_code < 500, (path, r.status_code, r.text[:200])
    assert leaks == {}
