# ruff: noqa: E501
"""What works without signing in: only the routes in OPEN, each for a reason; every other /api
route answers 401 to a request with no token (all of them, read from the app's own route list, so
a new route is covered the day it is added)."""

import re

from fastapi.testclient import TestClient

from app.main import app

# (method, path): why it is open, and what guards it instead of a login
OPEN = {
    ("GET", "/api/health"): "the container health check and uptime monitors: 'ok' only",
    ("GET", "/api/health/full"): "/health for monitors: states of the db, worker, osrm and backup, never a setting or a secret",
    ("GET", "/api/ops/mode"): "the login page shows the training banner (training on/off and the two public URLs) and the product name and tag (app.branding)",
    ("GET", "/api/manifest.webmanifest"): "the phone reads it to add the app to the home screen: the product name and tag only",
    ("GET", "/api/app-icon.svg"): "the home-screen icon named in the manifest: a plain letter, nothing else",
    ("POST", "/api/auth/login"): "signing in (rate limited, lockout after failed attempts)",
    ("POST", "/api/auth/login/two-step"): "the second step of signing in: needs the first step's short-lived ticket",
    ("POST", "/api/auth/refresh"): "a new access token: needs the httpOnly refresh cookie",
    ("POST", "/api/auth/logout"): "signing out: ends the refresh cookie's session, if any",
    ("POST", "/api/auth/forgot-password"): "Forgot password on the login page: the same answer for every email, at most one email per person in 5 minutes",
    ("POST", "/api/auth/password-check"): "the password rules for the form, before a password is set: nothing is stored or read",
    ("GET", "/api/auth/password-link/{token}"): "a set-password link from the office admin: the random single-use token is the key",
    ("POST", "/api/auth/password-link/{token}"): "setting the password from that link: the same token, then it is spent",
    ("GET", "/api/portal/invite/{token}"): "a client's portal invitation: the random single-use token is the key",
    ("POST", "/api/portal/invite/{token}"): "accepting the invitation (choosing a password): the same token",
    ("GET", "/api/receipt/{token}"): "the delivery receipt a site receiver opens from the QR code on the challan: the token is the key",
    ("POST", "/api/receipt/{token}"): "confirming that delivery: the same token, once",
    ("POST", "/api/issues/nightly"): "the nightly crawler's findings: needs the X-Crawler-Token header (CRAWLER_TOKEN)",
    ("GET", "/api/issues/nightly/open.md"): "the open bugs for the GitHub workflow: needs the X-Crawler-Token header",
}


def _routes() -> list[tuple[str, str]]:
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            if method in ("get", "post", "put", "patch", "delete"):
                out.append((method.upper(), path))
    return sorted(out)


def test_the_open_routes_are_exactly_the_listed_ones_and_every_other_api_route_needs_a_login():
    routes = _routes()
    assert len(routes) > 900  # the whole app, not a part of it
    missing = sorted(set(OPEN) - set(routes))
    assert not missing, f"listed as open but not in the app: {missing}"
    client = TestClient(app, raise_server_exceptions=False)
    wrong = []
    for method, path in routes:
        if (method, path) in OPEN:
            continue
        assert path.startswith("/api/"), path
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = client.request(method, url)
        if r.status_code != 401:
            wrong.append(f"{method} {path} -> {r.status_code}")
    assert not wrong, "these answer without a login:\n" + "\n".join(wrong)


def test_an_open_route_with_a_token_of_its_own_still_refuses_a_request_without_it():
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/issues/nightly/open.md").status_code in (401, 403)
    assert client.post("/api/issues/nightly", json={"findings": []}).status_code in (401, 403, 422)
    assert client.get("/api/portal/invite/not-a-real-token").status_code in (400, 404, 410)
    assert client.get("/api/receipt/not-a-real-token").status_code in (400, 404, 410)
