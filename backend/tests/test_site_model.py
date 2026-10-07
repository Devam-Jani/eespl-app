"""The 3D site model: every node with its status, ETag polling, and access."""

from datetime import date, timedelta

from sqlalchemy import select

from app.models import User
from tests.conftest import login
from tests.test_sites import TOWER, _assign, boss, media, new_site, won_site  # noqa: F401


def _model(client, headers, sid, etag=None):
    extra = {"If-None-Match": etag} if etag else {}
    return client.get(f"/api/sites/{sid}/model", headers={**headers, **extra})


def test_model_has_every_node_and_polls_by_etag(boss):  # noqa: F811
    client, headers = boss
    site = new_site(client, headers)
    nodes = client.post(
        f"/api/sites/{site['id']}/builder/tower", json=TOWER.model_dump(), headers=headers
    ).json()
    r = _model(client, headers, site["id"])
    assert r.status_code == 200
    data = r.json()
    assert {n["id"] for n in data["nodes"]} == {n["id"] for n in nodes} and len(nodes) == 323
    t1 = next(n for n in data["nodes"] if n["kind"] == "tower")
    assert t1["parent_id"] is None and t1["status"]["has_scope"] is False
    etag = r.headers["etag"]
    assert etag == f'"{data["version"]}"'
    unchanged = _model(client, headers, site["id"], etag)
    assert unchanged.status_code == 304 and unchanged.content == b""
    client.post(
        f"/api/sites/{site['id']}/nodes", json={"kind": "other", "name": "Gate"}, headers=headers
    )
    assert _model(client, headers, site["id"], etag).status_code == 200  # changed: full payload


def test_model_status_per_node(won_site):  # noqa: F811
    client, headers, sid, lines, toilets, kitchen, t1 = won_site
    r = client.post(
        "/api/stage-templates",
        json={
            "name": "Model test",
            "steps": [
                {"name": "Prep", "weight_percent": "40", "needs_photo": False},
                {
                    "name": "Ponding",
                    "weight_percent": "30",
                    "needs_photo": False,
                    "hold_point": True,
                },
                {"name": "Screed", "weight_percent": "30", "needs_photo": False},
            ],
        },
        headers=headers,
    )
    template = r.json()["id"]
    _assign(
        client,
        headers,
        sid,
        lines["Crystalline coating "]["boq_line_id"],
        [*toilets, kitchen],
        template,
    )
    client.post(f"/api/sites/{sid}/tasks/generate", headers=headers)
    tasks = client.get(f"/api/sites/{sid}/tasks", headers=headers).json()
    by_node = {}
    for t in tasks:
        by_node.setdefault(t["node_id"], []).append(t)

    def patch(task, **body):
        r = client.patch(f"/api/sites/{sid}/tasks/{task['id']}", json=body, headers=headers)
        assert r.status_code == 200, r.text

    a, b = toilets
    patch(by_node[a][0], status="done")
    patch(by_node[a][1], status="done")  # hold point done, not certified
    patch(by_node[b][0], status="in_progress")
    patch(by_node[kitchen][0], status="blocked")
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    patch(by_node[kitchen][2], planned_end=yesterday)
    status = {n["id"]: n["status"] for n in _model(client, headers, sid).json()["nodes"]}
    sa, sb, sk = status[a], status[b], status[kitchen]
    assert sa["counts"]["done"] == 2 and sa["waiting_certification"] is True
    assert (sa["percent"], sa["next_step"]) == (40.0, "Screed")  # the hold point is not counted
    assert (sb["current_step"], sb["counts"]["in_progress"]) == ("Prep", 1)
    assert sk["counts"]["blocked"] == 1 and sk["current_step"] == "Prep" and sk["is_late"] is True
    assert sa["is_late"] is False and sa["template_ids"] == [template]
    assert status[t1]["has_scope"] is False and status[t1]["tasks"] == 0
    assert 0 < status[t1]["percent"] < 100  # the tower's rolled-up progress


def test_model_respects_site_scopes(won_site, make_user, db, login_as):  # noqa: F811
    client, headers, sid, *_ = won_site
    other = new_site(client, headers, name="Other site")
    make_user("sup@example.com", "site_supervisor")
    db.expire_all()
    sup_id = db.scalar(select(User.id).where(User.email == "sup@example.com"))
    client.put(
        f"/api/sites/{sid}/members",
        json={"members": [{"user_id": str(sup_id), "role_on_site": "supervisor"}]},
        headers=headers,
    )
    sup = login(client, "sup@example.com")
    assert _model(client, sup, sid).status_code == 200
    assert _model(client, sup, other["id"]).status_code == 404
    customer, customer_headers = login_as("client", email="customer@example.com")
    assert customer.get(f"/api/sites/{sid}/model", headers=customer_headers).status_code == 403
