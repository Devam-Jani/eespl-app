# ruff: noqa: E501
"""The role SOPs (docs/sop, app.ops.sop): every role has one, every page a role may open is in it (a
new page without SOP text fails here), each route is explained by one page section, and in the app a
person reads only their own role's SOP (the super admin and the director all of them)."""

import re

from sqlalchemy import select

from app.models import Permission, Role
from app.ops import sop


def _roles(db) -> list[str]:
    return list(db.scalars(select(Role.code)))


def test_every_role_has_an_sop_and_the_super_admin_an_index(db):
    docs = sop.role_docs()
    assert sorted(set(_roles(db)) - set(docs)) == []
    assert sop.INDEX in docs


def test_every_route_of_the_app_is_explained_by_one_page_section():
    owners: dict[str, list[str]] = {}
    for p in sop.pages().values():
        for r in p.routes:
            owners.setdefault(r, []).append(p.page)
    routes = [i["to"] for i in sop._menu()] + [r["path"] for r in sop._routes()["detail"]] + sop._routes()["public"]
    assert [r for r in routes if r not in owners] == []
    assert {r: o for r, o in owners.items() if len(o) > 1} == {}


def test_every_page_a_role_may_open_is_in_its_sop(db):
    owner = sop.route_pages()
    missing = {}
    for role in _roles(db):
        have = sop.perms_of(db, role)
        inc = sop.included(role)
        lost = sorted({owner[r] for r in sop.opens(have) if owner.get(r) not in inc})
        if lost:
            missing[role] = lost
    assert missing == {}, "add an @page line (and the page's text) to docs/sop/<role>.md"


def test_the_sops_name_only_real_pages_and_permissions(db):
    pages = sop.pages()
    known = set(db.scalars(select(Permission.code)))
    for role in sop.role_docs():
        assert sop.included(role) <= set(pages), role
    tags = {c.strip() for p in pages.values() for m in re.finditer(r"\{perm:\s*([^}]*)\}", p.body) for c in m.group(1).split(",")}
    assert sorted(tags - known) == []
    for p in pages.values():
        assert p.title and p.body.strip(), p.page


def test_lines_are_kept_only_for_the_roles_holding_their_permission():
    body = "- **Approve**: approves it. {perm: dpr.approve, closeout.billing}\n- **Open**: opens it."
    assert sop.keep(body, {"dpr.approve"}) == "- **Approve**: approves it.\n- **Open**: opens it."
    assert sop.keep(body, {"site.view"}) == "- **Open**: opens it."


def test_the_markdown_is_escaped_and_links_stay_in_the_app():
    out = sop.to_html("**Save** <script>x</script> [here](/sites) [away](javascript:alert(1))\n\n- one\n  - two")
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert '<a href="/sites">here</a>' in out and 'href="#"' in out
    assert "<b>Save</b>" in out and "<li>two</li>" in out


def test_a_site_engineer_reads_their_own_sop_at_the_page_asked_for(login_as, db):
    c, h = login_as("site_engineer")
    r = c.get("/api/sop", params={"page": "/daily-reports"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert [s["role"] for s in body["sops"]] == ["site_engineer"]
    assert body["open"] == {"role": "site_engineer", "id": "daily-reports"}
    # a detail page opens its menu page's section
    assert c.get("/api/sop", params={"page": "/my-site/:id/report"}, headers=h).json()["open"]["id"] == "daily-reports"
    doc = c.get("/api/sop/site_engineer", headers=h).json()
    ids = [s["id"] for s in doc["sections"]]
    assert "daily-reports" in ids and "access" in ids and "first-login" in ids and "quick-card" in ids
    assert all("html" in s and "markdown" not in s for s in doc["sections"])


def test_a_role_cannot_open_another_roles_sop(login_as):
    c, h = login_as("site_engineer")
    assert c.get("/api/sop/billing", headers=h).status_code == 403
    assert c.get("/api/sop/index", headers=h).status_code == 403
    assert c.get("/api/sop/nobody", headers=h).status_code == 404
    c2, h2 = login_as("client", email="sop-client@example.com")
    assert [s["role"] for s in c2.get("/api/sop", headers=h2).json()["sops"]] == ["client"]
    assert c2.get("/api/sop/site_engineer", headers=h2).status_code == 403
    assert c2.get("/api/sop/client", headers=h2).status_code == 200


def test_the_super_admin_and_the_director_read_every_sop(login_as):
    for role in ("super_admin", "director"):
        c, h = login_as(role)
        listed = {s["role"] for s in c.get("/api/sop", headers=h).json()["sops"]}
        assert listed == set(sop.role_docs())
        assert c.get("/api/sop/billing", headers=h).status_code == 200
        # their own section first when the page is in their own SOP
        assert c.get("/api/sop", params={"page": "/admin/users"}, headers=h).json()["open"]["role"] in (role, sop.INDEX)


def test_a_person_with_two_roles_reads_both(login_as):
    c, h = login_as("billing", "accounts")
    assert {s["role"] for s in c.get("/api/sop", headers=h).json()["sops"]} == {"billing", "accounts"}


def test_the_sop_prints_to_pdf_and_word(db):
    data, pages = sop.pdf(db, "site_receiver", None)
    assert data[:4] == b"%PDF" and pages >= 3
    assert sop.docx(db, "site_receiver", None)[:2] == b"PK"
