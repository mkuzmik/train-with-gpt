"""Unit tests for the optional intervals.icu API-key step in the OAuth login flow,
and for secret_box (the encryption at rest behind it).

Mounts the Strava callback and connect routes on a bare Starlette app over a
real temp store; Strava and intervals.icu are stubbed with respx. The whole
login (including this page) through the real app is covered in
tests/integration/test_oauth_flow.py.
"""

import base64
import re

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import Response
from starlette.applications import Starlette
from starlette.testclient import TestClient

from train_with_gpt import secret_box, store
from train_with_gpt.config import config
from train_with_gpt.intervals_connect import intervals_connect_route
from train_with_gpt.strava_oauth import create_strava_oauth_route

ATHLETE_URL = "https://intervals.icu/api/v1/athlete/0"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
CLAUDE_REDIRECT = "http://localhost:9999/callback"


@pytest.fixture
def client(db, strava_app_credentials, token_encryption_key, http_mock):
    http_mock.post(STRAVA_TOKEN_URL).mock(return_value=Response(200, json={
        "access_token": "a", "refresh_token": "r", "expires_at": 9999999999,
        "athlete": {"id": 42, "firstname": "Jane", "lastname": "Doe"},
    }))
    return TestClient(Starlette(routes=[create_strava_oauth_route(frozenset({"42"})), intervals_connect_route]))


def _seed_pending():
    store.save_pending_authorization(
        state="s1", client_id="claude-client", redirect_uri=CLAUDE_REDIRECT,
        redirect_uri_provided_explicitly=True, code_challenge="c", scopes=[],
        resource=None, claude_state="claude-state",
    )


def _login_via_strava(client) -> str:
    """Run the Strava callback for athlete 42 and return the connect page's token."""
    _seed_pending()
    response = client.get("/oauth/strava/callback?state=s1&code=x", follow_redirects=False)

    assert response.status_code == 200
    assert "intervals.icu API key" in response.text
    assert "full access" in response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    return re.search(r'name="token" value="([^"]+)"', response.text).group(1)


def _submit(client, **form):
    return client.post("/oauth/intervals/connect", data=form, follow_redirects=False)


def _assert_redirected_to_claude(response):
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith(CLAUDE_REDIRECT) and "code=" in location and "state=claude-state" in location


def test_skip_finishes_login_without_connection(client):
    token = _login_via_strava(client)

    _assert_redirected_to_claude(_submit(client, token=token, action="skip"))
    assert store.get_intervals_connection("42") is None


def test_valid_key_is_validated_and_stored_encrypted(client, http_mock):
    token = _login_via_strava(client)
    route = http_mock.get(ATHLETE_URL).mock(return_value=Response(200, json={"id": "i777", "name": "Jane D"}))

    response = _submit(client, token=token, action="connect", api_key="  secret-key  ")

    _assert_redirected_to_claude(response)
    auth = route.calls.last.request.headers["authorization"]
    assert base64.b64decode(auth.split()[1]) == b"API_KEY:secret-key"
    connection = store.get_intervals_connection("42")
    assert connection["athlete_id"] == "i777"
    assert connection["athlete_name"] == "Jane D"
    assert "secret-key" not in connection["encrypted_api_key"]
    assert secret_box.decrypt(connection["encrypted_api_key"]) == "secret-key"


@pytest.mark.parametrize("status, message, code", [
    (401, "rejected that key", 400),
    (403, "rejected that key", 400),
    (500, "returned an error", 400),
])
def test_rejected_key_rerenders_page_and_keeps_step(client, http_mock, status, message, code):
    token = _login_via_strava(client)
    http_mock.get(ATHLETE_URL).mock(return_value=Response(status))

    response = _submit(client, token=token, action="connect", api_key="bad")

    assert response.status_code == code
    assert message in response.text
    assert store.get_intervals_connection("42") is None
    # The user can still skip afterwards.
    _assert_redirected_to_claude(_submit(client, token=token, action="skip"))


def test_unreachable_intervals_rerenders_page(client, http_mock):
    token = _login_via_strava(client)
    http_mock.get(ATHLETE_URL).mock(side_effect=httpx.ConnectError("down"))

    response = _submit(client, token=token, action="connect", api_key="k")

    assert response.status_code == 502
    assert "reach intervals.icu" in response.text  # (the apostrophe is HTML-escaped)


def test_empty_key_asks_for_one(client):
    token = _login_via_strava(client)

    response = _submit(client, token=token, action="connect", api_key="   ")

    assert response.status_code == 400
    assert "Paste your API key first" in response.text


def test_token_is_single_use(client):
    token = _login_via_strava(client)
    _submit(client, token=token, action="skip")

    assert _submit(client, token=token, action="skip").status_code == 400


def test_unknown_token_rejected(client):
    assert _submit(client, token="forged", action="skip").status_code == 400


def test_existing_connection_shown_and_can_disconnect(client):
    store.save_intervals_connection("42", "i777", "Jane D", secret_box.encrypt("k"))
    _seed_pending()
    page = client.get("/oauth/strava/callback?state=s1&code=x", follow_redirects=False)
    assert "Connected as <b>Jane D</b>" in page.text
    assert "Keep current and continue" in page.text
    token = re.search(r'name="token" value="([^"]+)"', page.text).group(1)

    _assert_redirected_to_claude(_submit(client, token=token, action="disconnect"))
    assert store.get_intervals_connection("42") is None


def test_step_skipped_when_encryption_not_configured(client, monkeypatch):
    monkeypatch.setattr(config, "token_encryption_key", None)
    _seed_pending()

    response = client.get("/oauth/strava/callback?state=s1&code=x", follow_redirects=False)

    _assert_redirected_to_claude(response)


# --- secret_box --------------------------------------------------------------------

def test_secret_box_round_trip(token_encryption_key):
    ciphertext = secret_box.encrypt("my-api-key")

    assert "my-api-key" not in ciphertext
    assert secret_box.decrypt(ciphertext) == "my-api-key"


def test_secret_box_cannot_decrypt_after_key_rotation(token_encryption_key, monkeypatch):
    ciphertext = secret_box.encrypt("my-api-key")
    monkeypatch.setattr(config, "token_encryption_key", Fernet.generate_key().decode())

    assert secret_box.decrypt(ciphertext) is None


def test_secret_box_not_configured_without_key():
    assert secret_box.is_configured() is False


def test_malformed_encryption_key_disables_step(monkeypatch):
    monkeypatch.setattr(config, "token_encryption_key", "not-a-fernet-key")
    assert secret_box.is_configured() is False
