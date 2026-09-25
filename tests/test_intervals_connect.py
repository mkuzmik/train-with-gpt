"""Tests for the optional intervals.icu API-key step in the OAuth login flow."""

import re
from unittest.mock import patch

import pytest
import respx
from cryptography.fernet import Fernet
from httpx import Response
from starlette.applications import Starlette
from starlette.testclient import TestClient

from train_with_gpt import secret_box, store
from train_with_gpt.intervals_connect import intervals_connect_route
from train_with_gpt.strava_oauth import strava_oauth_route

ATHLETE_URL = "https://intervals.icu/api/v1/athlete/0"
CLAUDE_REDIRECT = "http://localhost:9999/callback"


@pytest.fixture
def db(tmp_path):
    with patch("train_with_gpt.store.DB_PATH", tmp_path / "store.db"):
        store.init_db()
        yield


@pytest.fixture
def encryption_key():
    with patch("train_with_gpt.config.config.token_encryption_key", Fernet.generate_key().decode()):
        yield


@pytest.fixture
def client(db, encryption_key):
    return TestClient(Starlette(routes=[strava_oauth_route, intervals_connect_route]))


def _login_via_strava(client) -> str:
    """Run the Strava callback for athlete 42 and return the connect-page token."""
    store.save_pending_authorization(
        state="s1", client_id="claude-client", redirect_uri=CLAUDE_REDIRECT,
        redirect_uri_provided_explicitly=True, code_challenge="c", scopes=[],
        resource=None, claude_state="claude-state",
    )
    with respx.mock:
        respx.post("https://www.strava.com/oauth/token").mock(return_value=Response(200, json={
            "access_token": "a", "refresh_token": "r", "expires_at": 9999999999,
            "athlete": {"id": 42, "firstname": "Jane", "lastname": "Doe"},
        }))
        response = client.get("/oauth/strava/callback?state=s1&code=x", follow_redirects=False)

    assert response.status_code == 200
    assert "intervals.icu API key" in response.text
    assert "full access" in response.text
    assert response.headers["cache-control"] == "no-store"
    return re.search(r'name="token" value="([^"]+)"', response.text).group(1)


def _assert_redirected_to_claude(response):
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(CLAUDE_REDIRECT) and "code=" in location and "state=claude-state" in location


def test_skip_finishes_login_without_connection(client):
    token = _login_via_strava(client)

    response = client.post("/oauth/intervals/connect", data={"token": token, "action": "skip"}, follow_redirects=False)

    _assert_redirected_to_claude(response)
    assert store.get_intervals_connection("42") is None


@respx.mock
def test_valid_key_is_stored_encrypted(client):
    token = _login_via_strava(client)
    route = respx.get(ATHLETE_URL).mock(return_value=Response(200, json={"id": "i777", "name": "Jane D"}))

    response = client.post(
        "/oauth/intervals/connect",
        data={"token": token, "action": "connect", "api_key": "  secret-key  "},
        follow_redirects=False,
    )

    _assert_redirected_to_claude(response)
    assert route.calls.last.request.headers["authorization"].startswith("Basic ")
    connection = store.get_intervals_connection("42")
    assert connection["athlete_id"] == "i777"
    assert connection["athlete_name"] == "Jane D"
    assert "secret-key" not in connection["encrypted_api_key"]
    assert secret_box.decrypt(connection["encrypted_api_key"]) == "secret-key"


@respx.mock
def test_rejected_key_rerenders_page_and_keeps_step(client):
    token = _login_via_strava(client)
    respx.get(ATHLETE_URL).mock(return_value=Response(401))

    response = client.post(
        "/oauth/intervals/connect", data={"token": token, "action": "connect", "api_key": "bad"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "rejected that key" in response.text
    assert store.get_intervals_connection("42") is None
    # The user can still skip afterwards.
    response = client.post("/oauth/intervals/connect", data={"token": token, "action": "skip"}, follow_redirects=False)
    _assert_redirected_to_claude(response)


def test_token_is_single_use(client):
    token = _login_via_strava(client)
    client.post("/oauth/intervals/connect", data={"token": token, "action": "skip"}, follow_redirects=False)

    response = client.post("/oauth/intervals/connect", data={"token": token, "action": "skip"}, follow_redirects=False)

    assert response.status_code == 400


def test_unknown_token_rejected(client):
    response = client.post("/oauth/intervals/connect", data={"token": "forged", "action": "skip"}, follow_redirects=False)
    assert response.status_code == 400


def test_existing_connection_shown_and_can_disconnect(client):
    store.save_intervals_connection("42", "i777", "Jane D", secret_box.encrypt("k"))
    token = _login_via_strava(client)

    response = client.post("/oauth/intervals/connect", data={"token": token, "action": "disconnect"}, follow_redirects=False)

    _assert_redirected_to_claude(response)
    assert store.get_intervals_connection("42") is None


def test_step_skipped_when_encryption_not_configured(db):
    client = TestClient(Starlette(routes=[strava_oauth_route]))
    store.save_pending_authorization(
        state="s1", client_id="claude-client", redirect_uri=CLAUDE_REDIRECT,
        redirect_uri_provided_explicitly=True, code_challenge="c", scopes=[],
        resource=None, claude_state="claude-state",
    )
    with respx.mock, patch("train_with_gpt.config.config.token_encryption_key", None):
        respx.post("https://www.strava.com/oauth/token").mock(return_value=Response(200, json={
            "access_token": "a", "athlete": {"id": 42},
        }))
        response = client.get("/oauth/strava/callback?state=s1&code=x", follow_redirects=False)

    _assert_redirected_to_claude(response)


@pytest.mark.asyncio
async def test_wellness_tools_use_the_users_own_key(db, encryption_key):
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    from train_with_gpt.server import call_tool

    store.upsert_user("42", "strava", "Jane", "a", "r", 9999999999)
    store.save_intervals_connection("42", "i777", "Jane D", secret_box.encrypt("users-own-key"))
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id="c", scopes=[], subject="42")))
    try:
        with respx.mock:
            route = respx.get("https://intervals.icu/api/v1/athlete/0/wellness").mock(
                return_value=Response(200, json=[{"id": "2026-09-20", "restingHR": 48}])
            )
            result = await call_tool("get_resting_heart_rate", {"start_date": "2026-09-20", "end_date": "2026-09-20"})
    finally:
        auth_context_var.reset(reset)

    assert "48" in result[0].text
    import base64
    assert base64.b64decode(route.calls.last.request.headers["authorization"].split()[1]) == b"API_KEY:users-own-key"


@pytest.mark.asyncio
async def test_wellness_without_connection_explains_how_to_connect(db, encryption_key):
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    from train_with_gpt.server import call_tool

    store.upsert_user("42", "strava", "Jane", "a", "r", 9999999999)
    reset = auth_context_var.set(AuthenticatedUser(AccessToken(token="t", client_id="c", scopes=[], subject="42")))
    try:
        result = await call_tool("get_sleep_data", {"start_date": "2026-09-20", "end_date": "2026-09-20"})
    finally:
        auth_context_var.reset(reset)

    assert "connect intervals.icu" in result[0].text


def test_concurrent_claims_only_one_wins(client):
    token = _login_via_strava(client)

    assert store.claim_pending_connect_step(token, 60) is not None
    assert store.claim_pending_connect_step(token, 60) is None


def test_expired_step_rejected(client):
    token = _login_via_strava(client)

    assert store.claim_pending_connect_step(token, max_age_seconds=-1) is None


def test_malformed_encryption_key_disables_step(db):
    with patch("train_with_gpt.config.config.token_encryption_key", "not-a-fernet-key"):
        assert secret_box.is_configured() is False
