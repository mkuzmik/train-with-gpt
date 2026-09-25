"""ASGI-level tests for the remote entrypoint's auth boundary on /mcp.

Drives the real Starlette app (middleware stack + routes) so a change in
middleware ordering or routing can't silently expose /mcp or lock out
authenticated users.
"""

import importlib
import time
from unittest.mock import patch

import pytest
from mcp.server.auth.provider import AccessToken
from starlette.testclient import TestClient

from train_with_gpt import store

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("store") / "store.db"
    with patch("train_with_gpt.store.DB_PATH", db_path), \
         patch.dict("os.environ", {"PUBLIC_URL": "http://localhost"}):
        from train_with_gpt import http_server

        http_server = importlib.reload(http_server)  # fresh session manager + PUBLIC_URL
        with TestClient(http_server.starlette_app, base_url="http://localhost") as test_client:
            yield test_client


def _issue_token(token, expires_at):
    store.save_access_token(
        token,
        AccessToken(
            token=token, client_id="claude", scopes=[], expires_at=expires_at, subject="2706822"
        ).model_dump_json(),
    )


def test_health_is_public(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_mcp_rejects_missing_token(client):
    response = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]


def test_mcp_rejects_unknown_token(client):
    response = client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


def test_mcp_rejects_expired_token(client):
    _issue_token("expired-token", int(time.time()) - 10)
    response = client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": "Bearer expired-token"}
    )
    assert response.status_code == 401


def test_mcp_accepts_valid_token(client):
    _issue_token("valid-token", int(time.time()) + 3600)
    response = client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": "Bearer valid-token"}
    )
    assert response.status_code == 200
    assert "train-with-gpt" in response.text


def test_mcp_does_not_redirect(client):
    """/mcp must answer directly: a /mcp -> /mcp/ redirect breaks behind TLS proxies."""
    response = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS, follow_redirects=False)
    assert response.status_code == 401


def test_revoked_token_is_rejected(client):
    _issue_token("to-revoke", int(time.time()) + 3600)
    store.delete_access_token("to-revoke")
    response = client.post(
        "/mcp", json=INITIALIZE, headers={**MCP_HEADERS, "Authorization": "Bearer to-revoke"}
    )
    assert response.status_code == 401


def test_protected_resource_metadata(client):
    response = client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json()["resource"] == "http://localhost/mcp"
