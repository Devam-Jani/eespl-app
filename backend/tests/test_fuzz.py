# ruff: noqa: E501
"""Every form the API takes, filled wrongly: nothing answers 5xx. From the OpenAPI schema, each
JSON endpoint gets an empty body, each field of the wrong type, edge values (empty, very long,
negative, huge) and a plausible body on records that exist or not; the answer is a 4xx with a
plain message (422s through app/issues/fields.py), never a crash. Invented data only."""

import re

from fastapi.testclient import TestClient

from app.main import app

# never fuzzed: they end the session, run outside work, or need a file upload
SKIP = re.compile(r"logout|/auth/refresh|password|backup|restore|training|kylas|/import|upload|/files$|/photos$|/logo|/nightly|/test-boom")
PLAUSIBLE = {"string": "Fuzz text", "integer": 1, "number": 1.5, "boolean": True, "array": [], "object": {}}
WRONG = {"string": 12345, "integer": "abc", "number": "abc", "boolean": "maybe", "array": "x", "object": "x"}


def _resolve(spec: dict, s: dict | None) -> dict:
    s = s or {}
    while "$ref" in s:
        s = spec["components"]["schemas"][s["$ref"].split("/")[-1]]
    if "anyOf" in s:
        s = next((_resolve(spec, x) for x in s["anyOf"] if x.get("type") != "null"), {})
    if "allOf" in s:
        s = _resolve(spec, s["allOf"][0])
    return s


def _type(spec: dict, s: dict) -> str:
    s = _resolve(spec, s)
    if s.get("format") in ("date", "date-time"):
        return s["format"]
    return s.get("type", "string")


def _plausible(spec: dict, s: dict, depth: int = 0):
    s = _resolve(spec, s)
    t = _type(spec, s)
    if "enum" in s:
        return s["enum"][0]
    if t == "date":
        return "2026-10-22"
    if t == "date-time":
        return "2026-10-22T10:00:00Z"
    if t == "object" and depth < 3:
        return {k: _plausible(spec, v, depth + 1) for k, v in (s.get("properties") or {}).items() if k in (s.get("required") or [])}
    if t == "array" and depth < 3 and s.get("items"):
        return [_plausible(spec, s["items"], depth + 1)]
    if t == "string" and s.get("pattern"):
        return None  # a pattern we cannot guess: left out (its own 422)
    return PLAUSIBLE.get(t, "Fuzz")


def _bodies(spec: dict, schema: dict) -> list:
    s = _resolve(spec, schema)
    props = s.get("properties") or {}
    if _type(spec, s) == "array":
        return [[], "x", [_plausible(spec, s.get("items") or {})]]
    base = {k: v for k, v in ((k, _plausible(spec, p)) for k, p in props.items()) if v is not None}
    out: list = [{}, base, "not an object"]
    for k, p in list(props.items())[:25]:
        t = _type(spec, p)
        out.append({**base, k: WRONG.get(t, 12345)})
        if t == "string":
            out.append({**base, k: "x" * 10000})
            out.append({**base, k: ""})
        elif t in ("integer", "number"):
            out.append({**base, k: -1})
            out.append({**base, k: 10**20})
        elif t in ("date", "date-time"):
            out.append({**base, k: "31/02/2026"})
    return out


def _cases() -> list[tuple[str, str, object]]:
    spec = app.openapi()
    cases = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/") or SKIP.search(path):
            continue
        for method, op in ops.items():
            if method not in ("post", "put", "patch"):
                continue
            content = (op.get("requestBody") or {}).get("content") or {}
            if "application/json" not in content:
                continue
            for pid in ("1", "999999"):
                url = re.sub(r"\{[^}]+\}", pid, path)
                for body in _bodies(spec, content["application/json"]["schema"]):
                    cases.append((method.upper(), url, body))
                if "{" not in path:
                    break
    return cases


def test_no_form_filled_wrongly_crashes_the_api(make_user, db):
    from tests.conftest import login

    make_user("fuzz-director@example.com", "director", "super_admin")
    c = TestClient(app, raise_server_exceptions=False)
    h = login(c, "fuzz-director@example.com")
    crashes = {}
    cases = _cases()
    assert len(cases) > 1000
    for method, url, body in cases:
        r = c.request(method, url, json=body, headers=h)
        if r.status_code == 401:  # a case changed the session: sign in again
            h = login(c, "fuzz-director@example.com")
            r = c.request(method, url, json=body, headers=h)
        if r.status_code >= 500:
            key = f"{method} {re.sub(r'/(1|999999)(?=/|$)', '/{id}', url)}"
            crashes.setdefault(key, (r.status_code, str(body)[:200], r.text[:200]))
        if r.status_code == 422 and isinstance(r.json().get("detail"), list):
            for d in r.json()["detail"]:
                assert d.get("plain") and d.get("fix"), (method, url, d)  # every wrong entry said plainly
    assert not crashes, "\n".join(f"{k}: {v}" for k, v in sorted(crashes.items()))
