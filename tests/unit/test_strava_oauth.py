"""Tests for the Strava-side OAuth callback (second leg of the nested flow)."""

from unittest.mock import patch

import pytest
import respx
from httpx import Response
from starlette.applications import Starlette
from starlette.testclient import TestClient

from train_with_gpt import store
from train_with_gpt.strava_oauth import build_strava_authorize_url, strava_oauth_route


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "store.db"
    with patch("train_with_gpt.store.DB_PATH", db_path):
        store.init_db()
        yield db_path


@pytest.fixture
def client(db):
    app = Starlette(routes=[strava_oauth_route])
    return TestClient(app)


def _seed_pending(state="nested-state-1", claude_redirect="http://localhost:9999/callback"):
    store.save_pending_authorization(
        state=state,
        client_id="claude-client",
        redirect_uri=claude_redirect,
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge-abc",
        scopes=["activity:read_all"],
        resource=None,
        claude_state="claude-state-xyz",
    )


def test_build_strava_authorize_url():
    with patch("train_with_gpt.strava_oauth.config.client_id", "strava-app-id"):
        url = build_strava_authorize_url("http://localhost:8123", "some-state")

    assert url.startswith("https://www.strava.com/oauth/authorize?")
    assert "client_id=strava-app-id" in url
    assert "state=some-state" in url
    assert "localhost%3A8123%2Foauth%2Fstrava%2Fcallback" in url or "localhost:8123/oauth/strava/callback" in url


def test_callback_missing_state(client, db):
    response = client.get("/oauth/strava/callback", follow_redirects=False)
    assert response.status_code == 400


def test_callback_unknown_state(client, db):
    response = client.get("/oauth/strava/callback?state=nope&code=abc", follow_redirects=False)
    assert response.status_code == 400


def test_callback_strava_error_redirects_with_error(client, db):
    _seed_pending(state="nested-state-1")

    response = client.get(
        "/oauth/strava/callback?state=nested-state-1&error=access_denied",
        follow_redirects=False,
    )

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("http://localhost:9999/callback")
    assert "error=access_denied" in location
    assert "state=claude-state-xyz" in location


@respx.mock
def test_callback_success_mints_code_and_redirects(client, db):
    _seed_pending(state="nested-state-1")

    respx.post("https://www.strava.com/oauth/token").mock(
        return_value=Response(200, json={
            "access_token": "strava-access",
            "refresh_token": "strava-refresh",
            "expires_at": 9999999999,
            "athlete": {"id": 42, "firstname": "Jane", "lastname": "Doe"},
        })
    )

    with patch("train_with_gpt.strava_oauth.config.client_id", "app-id"), \
         patch("train_with_gpt.strava_oauth.config.client_secret", "app-secret"):
        response = client.get(
            "/oauth/strava/callback?state=nested-state-1&code=strava-code",
            follow_redirects=False,
        )

    assert response.status_code in (302, 307)
    location = response.headers["location"]
    assert location.startswith("http://localhost:9999/callback")
    assert "code=" in location
    assert "state=claude-state-xyz" in location

    user = store.get_user("42")
    assert user is not None
    assert user["provider"] == "strava"
    assert user["name"] == "Jane Doe"
    assert user["access_token"] == "strava-access"
    assert user["refresh_token"] == "strava-refresh"


def test_pending_authorization_is_single_use_via_callback(client, db):
    _seed_pending(state="nested-state-1")

    client.get("/oauth/strava/callback?state=nested-state-1&error=denied", follow_redirects=False)
    # Second attempt with the same state should now be unknown/expired
    response = client.get(
        "/oauth/strava/callback?state=nested-state-1&error=denied",
        follow_redirects=False,
    )
    assert response.status_code == 400
