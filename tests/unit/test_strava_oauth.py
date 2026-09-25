"""Unit tests for the Strava-side OAuth callback (second leg of the nested flow).

Mounts just the callback route on a bare Starlette app, over a real temp
store; Strava's token/profile endpoints are stubbed with respx. The full
round trip through the real app lives in tests/integration/test_oauth_flow.py.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import Response
from mcp.server.auth.provider import AuthorizationCode
from starlette.applications import Starlette
from starlette.testclient import TestClient

from tests.support import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
from train_with_gpt import store
from train_with_gpt.strava_oauth import build_strava_authorize_url, strava_oauth_route

TOKEN_URL = "https://www.strava.com/oauth/token"


@pytest.fixture
def client(db, strava_app_credentials):
    return TestClient(Starlette(routes=[strava_oauth_route]))


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
