from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from app.db import get_engine
from app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_db_unreachable():
    bad_engine = create_engine("postgresql+psycopg://nobody:nopass@127.0.0.1:1/none")
    app.dependency_overrides[get_engine] = lambda: bad_engine
    try:
        response = client.get("/api/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["db"] == "error"
    assert body["detail"]


def test_cors_allows_frontend_origin():
    response = client.get("/api/health", headers={"Origin": "http://localhost:5174"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"
