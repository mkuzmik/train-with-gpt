"""Unit tests for the Strava-side OAuth callback (second leg of the nested flow).

Mounts just the callback route on a bare Starlette app, over a real temp
store; Strava's token/profile endpoints are stubbed with respx. The full
round trip through the real app lives in tests/integration/test_oauth_flow.py.
"""

import sqlite3
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from httpx import Response
from mcp.server.auth.provider import AuthorizationCode
from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.support import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
from train_with_gpt import store
from train_with_gpt.strava_oauth import build_strava_authorize_url, create_strava_oauth_route

TOKEN_URL = "https://www.strava.com/oauth/token"
DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
ALLOWED = frozenset({"42", "7"})


@pytest.fixture
def client(db, strava_app_credentials):
    return TestClient(Starlette(routes=[create_strava_oauth_route(ALLOWED)]))


def _seed_pending(state="nested-state-1", claude_redirect="http://localhost:9999/callback"):
    store.save_pending_authorization(
        state=state,
        client_id="claude-client",
        redirect_uri=claude_redirect,
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge-abc",
        scopes=["activity:read_all"],
        resource="http://testserver/mcp",
        claude_state="claude-state-xyz",
    )


def _query(location):
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


def test_build_strava_authorize_url(strava_app_credentials):
    url = build_strava_authorize_url("http://localhost:8123/", "some-state")

    assert url.startswith("https://www.strava.com/oauth/authorize?")
    assert _query(url) == {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": "http://localhost:8123/oauth/strava/callback",
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "activity:read_all,activity:read,profile:read_all",
        "state": "some-state",
    }


def test_callback_missing_state(client):
    response = client.get("/oauth/strava/callback", follow_redirects=False)
    assert response.status_code == 400


def test_callback_unknown_state(client):
    response = client.get("/oauth/strava/callback?state=nope&code=abc", follow_redirects=False)
    assert response.status_code == 400


def test_callback_missing_code(client):
    _seed_pending()
    response = client.get("/oauth/strava/callback?state=nested-state-1", follow_redirects=False)
    assert response.status_code == 400


def test_callback_strava_error_redirects_with_error(client):
    _seed_pending(state="nested-state-1")

    response = client.get(
        "/oauth/strava/callback?state=nested-state-1&error=access_denied",
        follow_redirects=False,
    )

    assert response.status_code in (302, 303, 307)
    location = response.headers["location"]
    assert location.startswith("http://localhost:9999/callback")
    assert _query(location) == {"error": "access_denied", "state": "claude-state-xyz"}


def test_callback_success_mints_code_and_redirects(client, http_mock):
    _seed_pending(state="nested-state-1")
    token_route = http_mock.post(TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "strava-access",
            "refresh_token": "strava-refresh",
            "expires_at": 9999999999,
            "athlete": {"id": 42, "firstname": "Jane", "lastname": "Doe"},
        })
    )

    response = client.get(
        "/oauth/strava/callback?state=nested-state-1&code=strava-code",
        follow_redirects=False,
    )

    # Exchanged Strava's code with our app credentials
    assert parse_qs(token_route.calls.last.request.content.decode()) == {
        "client_id": [STRAVA_CLIENT_ID],
        "client_secret": [STRAVA_CLIENT_SECRET],
        "code": ["strava-code"],
        "grant_type": ["authorization_code"],
    }

    assert response.status_code in (302, 303, 307)
    location = response.headers["location"]
    assert location.startswith("http://localhost:9999/callback")
    params = _query(location)
    assert params["state"] == "claude-state-xyz"

    # Our own code is stored, bound to the Strava athlete and Claude's PKCE challenge
    code = AuthorizationCode.model_validate_json(store.get_auth_code(params["code"]))
    assert code.subject == "42"
    assert code.client_id == "claude-client"
    assert code.code_challenge == "challenge-abc"
    assert code.scopes == ["activity:read_all"]
    assert str(code.resource) == "http://testserver/mcp"

    user = store.get_user("42")
    assert user["provider"] == "strava"
    assert user["name"] == "Jane Doe"
    assert user["access_token"] == "strava-access"
    assert user["refresh_token"] == "strava-refresh"
    assert user["token_expires_at"] == 9999999999


def test_callback_falls_back_to_profile_when_token_has_no_athlete(client, http_mock):
    _seed_pending()
    http_mock.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "strava-access", "expires_at": 9999999999})
    )
    profile_route = http_mock.get("https://www.strava.com/api/v3/athlete").mock(
        return_value=Response(200, json={"id": 7, "firstname": "Sam", "lastname": ""})
    )

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=c", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert profile_route.calls.last.request.headers["Authorization"] == "Bearer strava-access"
    assert store.get_user("7")["name"] == "Sam"


def test_pending_authorization_is_single_use_via_callback(client):
    _seed_pending(state="nested-state-1")

    client.get("/oauth/strava/callback?state=nested-state-1&error=denied", follow_redirects=False)
    # Second attempt with the same state is now unknown
    response = client.get(
        "/oauth/strava/callback?state=nested-state-1&error=denied",
        follow_redirects=False,
    )
    assert response.status_code == 400


# --- allowlist ---------------------------------------------------------------

def _stub_token_exchange(http_mock, athlete_id):
    return http_mock.post(TOKEN_URL).mock(
        return_value=Response(200, json={
            "access_token": "strava-access",
            "refresh_token": "strava-refresh",
            "expires_at": 9999999999,
            "athlete": {"id": athlete_id, "firstname": "Eve", "lastname": "Outsider"},
        })
    )


def _stored_rows():
    tables = ("users", "auth_codes", "access_tokens", "pending_authorizations", "pending_connect_steps")
    with sqlite3.connect(store.DB_PATH) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


@pytest.mark.parametrize("intervals_step", [False, True], ids=["no-intervals-step", "intervals-step"])
def test_callback_refuses_an_athlete_not_on_the_allowlist(client, http_mock, request, intervals_step, capsys):
    if intervals_step:
        request.getfixturevalue("token_encryption_key")
    _seed_pending(state="nested-state-1")
    _stub_token_exchange(http_mock, 666)
    deauthorize = http_mock.post(DEAUTHORIZE_URL).mock(return_value=Response(200, json={}))

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=strava-code", follow_redirects=False)

    assert response.status_code == 403
    assert "location" not in response.headers  # no code for Claude
    assert "This server is private" in response.text
    # Nothing stored about the athlete, and the pending request is used up.
    assert set(_stored_rows().values()) == {0}
    # The grant Strava just gave us is revoked.
    assert parse_qs(deauthorize.calls.last.request.content.decode()) == {"access_token": ["strava-access"]}
    # The log says what happened without naming the athlete.
    err = capsys.readouterr().err
    assert "Refused sign-in" in err
    assert "666" not in err and "Eve" not in err and "Outsider" not in err


@pytest.mark.parametrize("failure", [
    Response(500, json={}),
    httpx.ConnectError("strava down"),
], ids=["strava-500", "network-error"])
def test_callback_still_refuses_when_deauthorize_fails(client, http_mock, failure, capsys):
    _seed_pending(state="nested-state-1")
    _stub_token_exchange(http_mock, 666)
    if isinstance(failure, Exception):
        http_mock.post(DEAUTHORIZE_URL).mock(side_effect=failure)
    else:
        http_mock.post(DEAUTHORIZE_URL).mock(return_value=failure)

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=strava-code", follow_redirects=False)

    assert response.status_code == 403
    assert set(_stored_rows().values()) == {0}
    assert "NOT revoked" in capsys.readouterr().err


def test_callback_refuses_via_the_profile_fallback_too(client, http_mock):
    _seed_pending()
    http_mock.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "strava-access", "expires_at": 9999999999})
    )
    http_mock.get("https://www.strava.com/api/v3/athlete").mock(
        return_value=Response(200, json={"id": 666, "firstname": "Eve", "lastname": ""})
    )
    deauthorize = http_mock.post(DEAUTHORIZE_URL).mock(return_value=Response(200, json={}))

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=c", follow_redirects=False)

    assert response.status_code == 403
    assert store.get_user("666") is None
    assert deauthorize.called


def test_callback_with_empty_allowlist_refuses_everyone(db, strava_app_credentials, http_mock):
    client = TestClient(Starlette(routes=[create_strava_oauth_route(frozenset())]))
    _seed_pending()
    _stub_token_exchange(http_mock, 42)
    http_mock.post(DEAUTHORIZE_URL).mock(return_value=Response(200, json={}))

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=c", follow_redirects=False)

    assert response.status_code == 403
    assert store.get_user("42") is None


def test_callback_allowed_athlete_is_not_deauthorized(client, http_mock):
    _seed_pending()
    _stub_token_exchange(http_mock, 42)
    deauthorize = http_mock.post(DEAUTHORIZE_URL)

    response = client.get("/oauth/strava/callback?state=nested-state-1&code=c", follow_redirects=False)

    assert response.status_code in (302, 303, 307)
    assert store.get_user("42") is not None
    assert not deauthorize.called
