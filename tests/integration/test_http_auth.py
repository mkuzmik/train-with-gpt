"""The HTTP server's auth boundary on /mcp, black box.

Drives the real Starlette app (middleware stack + routes) so a change in
middleware ordering or routing can't silently expose /mcp or lock out
authenticated users.
"""

import time

from mcp.server.auth.provider import AccessToken

from train_with_gpt import store

from .conftest import PUBLIC_URL, McpHttpClient, oauth_login

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


def test_health_is_public(http):
    assert http.get("/health").json() == {"status": "ok"}


def test_mcp_rejects_missing_token(http):
    response = McpHttpClient(http, None).post(INITIALIZE)

    assert response.status_code == 401
    assert f'resource_metadata="{PUBLIC_URL}/.well-known/oauth-protected-resource/mcp"' in response.headers["www-authenticate"]


def test_mcp_rejects_unknown_token(http):
    assert McpHttpClient(http, "not-a-real-token").post(INITIALIZE).status_code == 401


def test_mcp_rejects_expired_token(http):
    # Our tokens live for a year, so expiry can't be reached through the public
    # interface in a test; seed an already-expired one straight into the store.
    store.save_access_token("expired-token", AccessToken(
        token="expired-token", client_id="claude", scopes=[], expires_at=int(time.time()) - 10, subject="1",
    ).model_dump_json())

    assert McpHttpClient(http, "expired-token").post(INITIALIZE).status_code == 401


def test_mcp_accepts_token_from_oauth_login(http, strava):
    response = McpHttpClient(http, oauth_login(http, strava, 424242)).post(INITIALIZE)

    assert response.status_code == 200
    assert "train-with-gpt" in response.text


def test_mcp_does_not_redirect(http):
    """/mcp must answer directly: a /mcp -> /mcp/ redirect breaks behind TLS proxies."""
    assert McpHttpClient(http, None).post(INITIALIZE).status_code == 401


def test_protected_resource_metadata(http):
    response = http.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json()["resource"] == f"{PUBLIC_URL}/mcp"
    assert [url.rstrip("/") for url in response.json()["authorization_servers"]] == [PUBLIC_URL]


def test_app_creates_its_store_on_startup(http):
    # The http fixture started the app; its lifespan initialised the DB in HOME.
    assert store.DB_PATH.exists()
