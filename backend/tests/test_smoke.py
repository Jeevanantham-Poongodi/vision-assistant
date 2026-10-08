"""main:app (what uvicorn imports) starts and serves. Exact shapes are tested in test_api.py."""
from fastapi.testclient import TestClient

from main import app


def test_app_starts_and_serves():
    with TestClient(app) as client:  # `with` runs the lifespan, which loads the models
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "degraded")  # degraded until YOLO is loaded (contract 7.2)
        assert client.get("/api/v1/config").status_code == 200
