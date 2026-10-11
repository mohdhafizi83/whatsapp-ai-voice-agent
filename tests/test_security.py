"""Offline security tests: auth, headers, body cap, validation, error hygiene."""
import pytest
from starlette.websockets import WebSocketDisconnect

import app as app_module

SEC_HEADERS = {
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cache-control": "no-store",
}


# ─── Admin auth: accept / reject / fail-closed ────────────────────
def test_leads_accept(client, key):
    r = client.get("/api/leads", headers={"X-API-Key": key})
    assert r.status_code == 200


def test_leads_reject_missing_key(client):
    assert client.get("/api/leads").status_code == 401


def test_leads_reject_wrong_key(client):
    r = client.get("/api/leads", headers={"X-API-Key": "wrong"})
    assert r.status_code == 401


def test_leads_fail_closed_when_unset(client, no_admin_key):
    r = client.get("/api/leads", headers={"X-API-Key": "anything"})
    assert r.status_code == 501


def test_leads_reject_nonascii_key(client):
    # uvicorn decodes header bytes latin-1, so non-ASCII str can reach the
    # compare; _key_matches must return False, not raise TypeError.
    assert app_module._key_matches("ünïcødé-key", "test-admin-key") is False
    assert app_module._key_matches("test-admin-key", "test-admin-key") is True
    r = client.get("/api/leads", headers={"X-API-Key": b"caf\xe9-key"})
    assert r.status_code == 401


def test_mode_accept(client, key):
    r = client.post("/api/mode?mode=interview", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json() == {"mode": "interview"}


def test_mode_reject_unauth(client):
    assert client.post("/api/mode?mode=sales").status_code == 401


def test_mode_reject_invalid_value(client, key):
    r = client.post("/api/mode?mode=evil", headers={"X-API-Key": key})
    assert r.status_code == 400


def test_mode_fail_closed_when_unset(client, no_admin_key):
    r = client.post("/api/mode?mode=sales", headers={"X-API-Key": "x"})
    assert r.status_code == 501


# ─── Security headers ─────────────────────────────────────────────
def test_security_headers_on_success(client):
    r = client.get("/")
    assert r.status_code == 200
    for h, v in SEC_HEADERS.items():
        assert r.headers[h] == v


def test_security_headers_on_error(client):
    r = client.get("/api/leads")  # 401
    assert r.status_code == 401
    for h, v in SEC_HEADERS.items():
        assert r.headers[h] == v


# ─── Body cap ─────────────────────────────────────────────────────
def test_body_cap_rejects_oversized(client, key):
    big = {"name": "A" * (2 * 1024 * 1024), "phone": "123"}
    r = client.post("/api/leads", json=big, headers={"X-API-Key": key})
    assert r.status_code == 413
    assert r.json() == {"error": "request body too large"}


def test_body_cap_allows_normal(client, key):
    r = client.post(
        "/api/leads", json={"name": "Ali", "phone": "+60123456789"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 201


# ─── Lead capture validation reject paths ─────────────────────────
def test_lead_missing_fields(client, key):
    r = client.post("/api/leads", json={"name": "Ali"}, headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_empty_name(client, key):
    r = client.post("/api/leads", json={"name": "   ", "phone": "123"},
                    headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_name_too_long(client, key):
    r = client.post("/api/leads", json={"name": "A" * 121, "phone": "123"},
                    headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_phone_bad_charset(client, key):
    r = client.post("/api/leads", json={"name": "Ali", "phone": "<script>"},
                    headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_notes_too_long(client, key):
    r = client.post("/api/leads",
                    json={"name": "Ali", "phone": "123", "notes": "x" * 2001},
                    headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_control_chars_stripped(client, key):
    r = client.post("/api/leads",
                    json={"name": "A\x00l\x1bi\x7f", "phone": "6012\n"},
                    headers={"X-API-Key": key})
    assert r.status_code == 201
    saved = app_module._engine.call_logger.saved[-1]
    assert saved["name"] == "Ali"
    assert saved["phone"] == "6012"


def test_lead_invalid_json(client, key):
    r = client.post("/api/leads", content=b"{not json",
                    headers={"X-API-Key": key, "Content-Type": "application/json"})
    assert r.status_code == 400


def test_lead_non_dict_json(client, key):
    r = client.post("/api/leads", json=[1, 2], headers={"X-API-Key": key})
    assert r.status_code == 422


def test_lead_auth_before_body(client):
    # unauthenticated must be 401 even with a garbage body
    r = client.post("/api/leads", content=b"{garbage")
    assert r.status_code == 401


# ─── Generic error handler (no exception leakage) ─────────────────
def test_generic_500_no_exception_text(client):
    @app_module.fastapi_app.get("/_boom")
    async def _boom():
        raise ValueError("SECRET_INTERNAL_DETAIL")

    r = client.get("/_boom")
    assert r.status_code == 500
    assert r.json() == {"error": "internal server error"}
    assert "SECRET_INTERNAL_DETAIL" not in r.text
    for h in SEC_HEADERS:
        assert h in r.headers


# ─── WebSocket auth guard ─────────────────────────────────────────
def _register_ws_route():
    if "/ws" not in [getattr(r, "path", None) for r in app_module.fastapi_app.routes]:
        from fastapi import WebSocket

        @app_module.fastapi_app.websocket("/ws")
        async def _ws(websocket: WebSocket):
            await websocket.accept()
            await websocket.send_text("ok")
            await websocket.close()


def test_ws_reject_missing_key(client):
    _register_ws_route()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_ws_reject_wrong_key(client):
    _register_ws_route()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?api_key=***"):
            pass
    assert exc.value.code == 1008


def test_ws_fail_closed_when_unset(client, no_admin_key):
    _register_ws_route()
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws?api_key=***"):
            pass
    assert exc.value.code == 1011


def test_ws_accept_valid_key(client, key):
    _register_ws_route()
    with client.websocket_connect(f"/ws?api_key={key}") as ws:
        assert ws.receive_text() == "ok"
