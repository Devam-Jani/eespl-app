# ruff: noqa: E501
"""The new UI's server side: each person's look (dark or light) kept for them on every device,
search anywhere (Ctrl+K) returning only what the role may see, and the home page's numbers per
role, with no money for the roles that do not see money. Invented data only."""

from sqlalchemy import select

from app.models import User
from app.sites.models import Site, SiteMember
from tests.test_finance import boss  # noqa: F401  (fixture)


def _site(db, code: str, name: str) -> Site:
    s = Site(code=code, name=name, status="active")
    db.add(s)
    db.commit()
    return s


# --- the look, per person ----------------------------------------------------------------------------


def test_the_theme_is_remembered_for_the_person(login_as, db):
    c, h = login_as("site_engineer")
    assert c.get("/api/auth/me", headers=h).json()["user"]["ui_theme"] is None  # dark, the default
    r = c.put("/api/auth/theme", json={"theme": "light"}, headers=h)
    assert r.status_code == 200 and r.json() == {"theme": "light"}
    assert c.get("/api/auth/me", headers=h).json()["user"]["ui_theme"] == "light"
    # another person's look is their own
    c2, h2 = login_as("billing")
    assert c2.get("/api/auth/me", headers=h2).json()["user"]["ui_theme"] is None
    assert c.put("/api/auth/theme", json={"theme": "blue"}, headers=h).status_code == 422


def test_a_client_login_keeps_its_theme_too(login_as):
    c, h = login_as("client")
    assert c.put("/api/auth/theme", json={"theme": "light"}, headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).json()["user"]["ui_theme"] == "light"


# --- search anywhere -------------------------------------------------------------------------------------


def test_search_returns_only_what_the_role_may_see(login_as, make_user, db):
    mine = _site(db, "S-UI-9001", "Invented Search Mine")
    other = _site(db, "S-UI-9002", "Invented Search Other")
    c, h = login_as("site_engineer", email="engineer-search@example.com")
    eng = db.scalar(select(User).where(User.email == "engineer-search@example.com"))
    db.add(SiteMember(site_id=mine.id, user_id=eng.id, role_on_site="incharge"))
    db.commit()
    r = c.get("/api/search?q=Invented Search", headers=h).json()
    assert [s["id"] for s in r["sites"]] == [mine.id]  # assigned: their own site only
    assert r["bills"] == [] and r["quotations"] == [] and r["people"] == []  # no bills, quotations or users for them
    d, dh = login_as("director", email="director-search@example.com")
    r = d.get("/api/search?q=Invented Search", headers=dh).json()
    assert {s["id"] for s in r["sites"]} == {mine.id, other.id}
    assert r["sites"][0]["to"].startswith("/sites/")


def test_search_finds_people_by_role_only_for_those_who_manage_users(login_as):
    c, h = login_as("office_admin")
    r = c.get("/api/search?q=billing", headers=h).json()
    assert any(p["id"] == "billing" and ("people" in p["note"] or "person" in p["note"]) for p in r["people"])
    assert all(set(p) == {"id", "title", "note", "to"} for p in r["people"])  # roles and counts, never names
    for role in ("sales", "director"):  # the director does not manage users here: the office admin does
        s, sh = login_as(role)
        assert s.get("/api/search?q=billing", headers=sh).json()["people"] == []


def test_search_needs_two_letters_and_is_not_for_clients(login_as):
    c, h = login_as("director")
    assert c.get("/api/search?q=a", headers=h).status_code == 422
    cl, ch = login_as("client")
    assert cl.get("/api/search?q=DEMO", headers=ch).status_code == 403


# --- the home page ---------------------------------------------------------------------------------------


def test_the_home_page_numbers_per_role(login_as, db):
    _site(db, "S-UI-9003", "Invented Home Site")
    d, dh = login_as("director")
    r = d.get("/api/home", headers=dh).json()
    assert r["dashboard"] == "company"
    assert [k["key"] for k in r["kpis"]] == ["order_value", "billed_month", "overdue_60", "on_track"]
    assert all(len(k["series"]) == 6 for k in r["kpis"])  # the last six months behind each number
    assert r["kpis"][3]["unit"] == "of"
    e, eh = login_as("site_engineer")
    r = e.get("/api/home", headers=eh).json()
    assert r["dashboard"] == "site" and [k["key"] for k in r["kpis"]] == ["my_sites", "my_progress", "dpr_due", "open_snags"]
    assert all(s["billed"] is None and s["order"] is None for s in r["sites"])  # no money for a site role
    assert r["needs"] == []  # nothing waits on a site engineer here (labour claims are the director's)


def test_the_home_page_needs_and_actions_come_from_the_real_queues(boss, db):  # noqa: F811
    c, h = boss
    r = c.get("/api/home", headers=h).json()
    for n in r["needs"]:
        assert n["tone"] in ("done", "prog", "hold", "block", "idle")
        for a in n["actions"]:
            assert a.get("link") or a["path"].startswith("/api/")
