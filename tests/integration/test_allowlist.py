"""The Strava athlete allowlist (ALLOWED_STRAVA_ATHLETE_IDS), black box.

Drives the real app through /authorize -> Strava (FakeStrava) -> our
callback -> /token -> /mcp. The server's allowlist comes from the env var,
as in production; the default test allowlist is conftest.ALLOWED_ATHLETES,
and every id here is synthetic.
"""

import os
import sqlite3
import subprocess
import sys

import pytest
from starlette.testclient import TestClient

from train_with_gpt import store
from train_with_gpt.allowlist import AllowlistError
from train_with_gpt.http_server import create_app

from .conftest import (
    ALLOWED_ATHLETES,
    CLAUDE_REDIRECT_URI,
    PUBLIC_URL,
    McpHttpClient,
    oauth_login,
    pkce_pair,
    query_params,
    register_client,
)

OUTSIDER = 666  # not in ALLOWED_ATHLETES
ALLOWED = 1001  # in ALLOWED_ATHLETES


def _stored_rows() -> dict:
    tables = ("users", "auth_codes", "access_tokens", "pending_authorizations",
              "pending_connect_steps", "intervals_connections")
    with sqlite3.connect(store.DB_PATH) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


def _sign_in_until_callback(http, strava, athlete_id):
    """Claude's /authorize, then the athlete approves on Strava; returns our callback's response."""
    client = register_client(http)
    _, challenge = pkce_pair()
    authorize = http.get("/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": CLAUDE_REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "claude-state",
        "resource": f"{PUBLIC_URL}/mcp",
    }, follow_redirects=False)
    strava_state = query_params(authorize.headers["location"])["state"]
    return http.get("/oauth/strava/callback", params={"state": strava_state, "code": strava.approve(athlete_id)},
                    follow_redirects=False)


@pytest.mark.parametrize("intervals_step", [
    pytest.param(False, id="no-intervals-step"),
    pytest.param(True, id="intervals-step", marks=pytest.mark.intervals_login_step),
])
def test_athlete_not_on_the_list_is_refused_and_nothing_is_kept(http, strava, intervals_step, capsys):
    response = _sign_in_until_callback(http, strava, OUTSIDER)

    # A plain "this server is private" page, not a redirect with a code for Claude.
    assert response.status_code == 403
    assert "location" not in response.headers
    assert "This server is private" in response.text
    # Nothing about the athlete is stored; the pending authorization is gone.
    assert set(_stored_rows().values()) == {0}
    # The Strava grant was revoked right away: the token Strava issued is dead.
    assert len(strava.deauthorized) == 1
    assert not strava.token_is_valid(strava.deauthorized[0])
    # Logged without the athlete's id or name.
    err = capsys.readouterr().err
    assert "Refused sign-in" in err
    assert str(OUTSIDER) not in err


def test_athlete_on_the_list_signs_in_and_uses_tools(http, strava):
    strava.activities[ALLOWED] = []

    mcp = McpHttpClient(http, oauth_login(http, strava, ALLOWED))
    mcp.initialize()

    assert mcp.call_tool("get_activities", {"start_date": "2024-01-15", "end_date": "2024-01-15"}) == \
        "No activities found for 2024-01-15."
    assert strava.deauthorized == []
    assert store.get_user(str(ALLOWED)) is not None


@pytest.mark.allowed_athletes("")
def test_unset_allowlist_lets_nobody_in(http, strava):
    response = _sign_in_until_callback(http, strava, ALLOWED)

    assert response.status_code == 403
    assert store.get_user(str(ALLOWED)) is None


def test_taking_an_athlete_off_the_list_rejects_their_existing_token(server_env, strava, monkeypatch):
    with TestClient(create_app(), base_url=PUBLIC_URL) as http:
        bearer = oauth_login(http, strava, ALLOWED)
        assert McpHttpClient(http, bearer).post(_initialize()).status_code == 200

    # The operator removes the athlete (`fly secrets set` restarts the server).
    monkeypatch.setenv("ALLOWED_STRAVA_ATHLETE_IDS", "1,3")
    with TestClient(create_app(), base_url=PUBLIC_URL) as http:
        assert McpHttpClient(http, bearer).post(_initialize()).status_code == 401

    # Nothing was deleted, so adding them back restores the same token.
    monkeypatch.setenv("ALLOWED_STRAVA_ATHLETE_IDS", f"1,3,{ALLOWED}")
    with TestClient(create_app(), base_url=PUBLIC_URL) as http:
        assert McpHttpClient(http, bearer).post(_initialize()).status_code == 200


@pytest.mark.parametrize("value", ["1001,abc", "*", "1001;2002"])
def test_malformed_allowlist_stops_the_server_from_starting(server_env, monkeypatch, value):
    monkeypatch.setenv("ALLOWED_STRAVA_ATHLETE_IDS", value)

    with pytest.raises(AllowlistError):
        create_app()


def test_http_entrypoint_exits_on_a_malformed_allowlist(hermetic):
    """The real startup path (module import in `python -m ...http_server`) fails loudly."""
    env = {"HOME": str(hermetic), "PATH": os.environ["PATH"], "ALLOWED_STRAVA_ATHLETE_IDS": "1001,oops-9"}

    result = subprocess.run(
        [sys.executable, "-m", "train_with_gpt.http_server"],
        env=env, capture_output=True, text=True, timeout=60,
    )

    assert result.returncode != 0
    assert "AllowlistError" in result.stderr and "ALLOWED_STRAVA_ATHLETE_IDS" in result.stderr
    assert "oops-9" not in result.stderr


def test_startup_logs_the_count_not_the_ids(server_env, capsys):
    create_app()

    err = capsys.readouterr().err
    assert f"{len(ALLOWED_ATHLETES)} Strava athlete(s) allowed" in err
    assert "4242" not in err


def _initialize() -> dict:
    return {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
    }
