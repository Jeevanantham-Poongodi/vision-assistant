"""Every non-2xx REST response uses the contract 11.1 body (BE-02)."""
import logging

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from errors import AppError
from main import create_app
from schemas import ErrorResponse, SessionCreate
from tests.conftest import make_settings

ORIGIN = "http://localhost:5173"

fake_routes = APIRouter(prefix="/api/v1/test")


@fake_routes.get("/session-missing")
def session_missing():
    raise AppError("SESSION_NOT_FOUND", "Session 5d0e does not exist or has ended.")


@fake_routes.get("/model-not-ready")
def model_not_ready():
    raise AppError("MODEL_NOT_READY", "YOLO is still loading.")


@fake_routes.get("/custom")
def custom():
    raise AppError("INVALID_FRAME", "Frame too large.", status=413, details={"max_bytes": 5242880})


@fake_routes.post("/sessions")
def create_session(body: SessionCreate):
    return {"ok": True}


@fake_routes.get("/crash")
def crash():
    raise RuntimeError("secret-db-password")


@pytest.fixture
def client():
    app = create_app(make_settings(allowed_origins=ORIGIN))
    app.include_router(fake_routes)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def assert_error(r, status: int, code: str) -> dict:
    assert r.status_code == status
    body = r.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    ErrorResponse.model_validate(body)
    return body["error"]


# --- AppError ---

def test_app_error_default_status_from_contract(client):
    err = assert_error(client.get("/api/v1/test/session-missing"), 404, "SESSION_NOT_FOUND")
    assert err == {"code": "SESSION_NOT_FOUND", "message": "Session 5d0e does not exist or has ended.", "details": {}}
    assert_error(client.get("/api/v1/test/model-not-ready"), 503, "MODEL_NOT_READY")


def test_app_error_custom_status_and_details(client):
    err = assert_error(client.get("/api/v1/test/custom"), 413, "INVALID_FRAME")
    assert err["details"] == {"max_bytes": 5242880}


def test_ws_only_code_falls_back_to_500():
    assert AppError("UNSUPPORTED_MESSAGE", "x").status == 500


# --- Validation ---

def test_invalid_body_is_validation_error(client):
    err = assert_error(client.post("/api/v1/test/sessions", json={"user_id": "not-a-uuid"}), 422, "VALIDATION_ERROR")
    (field,) = err["details"]["errors"]
    assert field["loc"] == ["body", "user_id"]
    assert set(field) == {"loc", "msg", "type"}  # no "input": it could echo images or secrets
    assert "not-a-uuid" not in str(err)


def test_malformed_json_is_validation_error(client):
    r = client.post("/api/v1/test/sessions", content="{oops", headers={"Content-Type": "application/json"})
    assert_error(r, 422, "VALIDATION_ERROR")


# --- Unhandled exceptions ---

def test_crash_is_internal_without_leaking(client, caplog):
    with caplog.at_level(logging.ERROR, logger="vision_assistant"):
        r = client.get("/api/v1/test/crash")
    err = assert_error(r, 500, "INTERNAL")
    assert err["message"] == "Internal server error."
    assert "secret-db-password" not in r.text and "Traceback" not in r.text
    # ...but the full traceback is in the logs.
    assert any(rec.exc_info and "secret-db-password" in str(rec.exc_info[1]) for rec in caplog.records)


# --- Framework errors ---

def test_unknown_path_is_not_found(client):
    assert_error(client.get("/api/v1/nope"), 404, "NOT_FOUND")


def test_wrong_method_is_method_not_allowed(client):
    assert_error(client.post("/api/v1/health"), 405, "METHOD_NOT_ALLOWED")


# --- CORS on error responses ---

@pytest.mark.parametrize("path", ["/api/v1/test/crash", "/api/v1/nope", "/api/v1/test/session-missing"])
def test_errors_carry_cors_headers(client, path):
    r = client.get(path, headers={"Origin": ORIGIN})
    assert r.status_code >= 400
    assert r.headers["access-control-allow-origin"] == ORIGIN


# --- Docs ---

def test_openapi_documents_our_error_body(client):
    spec = client.get("/openapi.json").json()
    assert "HTTPValidationError" not in str(spec)
    responses = spec["paths"]["/api/v1/test/sessions"]["post"]["responses"]
    assert responses["422"]["content"]["application/json"]["schema"]["$ref"].endswith("/ErrorResponse")
