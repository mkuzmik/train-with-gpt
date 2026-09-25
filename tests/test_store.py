"""Tests for the multi-user OAuth SQLite store."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from train_with_gpt import store


@pytest.fixture
def db(tmp_path):
    """Point the store at an isolated temp DB file for each test."""
    db_path = tmp_path / "store.db"
    with patch("train_with_gpt.store.DB_PATH", db_path):
        store.init_db()
        yield db_path


def test_client_round_trip(db):
    store.save_client("client-1", '{"client_id": "client-1", "redirect_uris": ["http://x"]}')
    data = store.get_client("client-1")
    assert data is not None
    assert "client-1" in data

    assert store.get_client("missing") is None


def test_client_upsert_replaces(db):
    store.save_client("client-1", '{"v": 1}')
    store.save_client("client-1", '{"v": 2}')
    assert store.get_client("client-1") == '{"v": 2}'


def test_auth_code_round_trip_and_single_use(db):
    store.save_auth_code("code-1", '{"code": "code-1"}')
    assert store.get_auth_code("code-1") == '{"code": "code-1"}'

    store.mark_auth_code_used("code-1")
    # Used codes should no longer be returned (single-use)
    assert store.get_auth_code("code-1") is None


def test_access_token_round_trip(db):
    store.save_access_token("token-1", '{"token": "token-1"}')
    assert store.get_access_token_row("token-1") == '{"token": "token-1"}'
    assert store.get_access_token_row("missing") is None


def test_pending_authorization_is_single_use(db):
    store.save_pending_authorization(
        state="state-1",
        client_id="claude-client",
        redirect_uri="http://claude/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        scopes=["activity:read_all"],
        resource=None,
        claude_state="claude-state-value",
    )

    pending = store.pop_pending_authorization("state-1")
    assert pending["client_id"] == "claude-client"
    assert pending["redirect_uri"] == "http://claude/callback"
    assert pending["redirect_uri_provided_explicitly"] is True
    assert pending["code_challenge"] == "challenge"
    assert pending["scopes"] == ["activity:read_all"]
    assert pending["claude_state"] == "claude-state-value"

    # Popped once - gone now
    assert store.pop_pending_authorization("state-1") is None


def test_pending_authorization_unknown_state(db):
    assert store.pop_pending_authorization("nope") is None


def test_user_upsert_and_get(db):
    store.upsert_user(
        user_id="12345",
        provider="strava",
        name="Test Athlete",
        access_token="access-1",
        refresh_token="refresh-1",
        token_expires_at=1234567890,
    )

    user = store.get_user("12345")
    assert user["user_id"] == "12345"
    assert user["provider"] == "strava"
    assert user["name"] == "Test Athlete"
    assert user["access_token"] == "access-1"
    assert user["refresh_token"] == "refresh-1"
    assert user["token_expires_at"] == 1234567890
    assert user["created_at"] == user["updated_at"]


def test_user_upsert_preserves_created_at_on_update(db):
    store.upsert_user("12345", "strava", "Name", "access-1", "refresh-1", 100)
    first = store.get_user("12345")

    store.upsert_user("12345", "strava", "Name", "access-2", "refresh-2", 200)
    second = store.get_user("12345")

    assert second["created_at"] == first["created_at"]
    assert second["access_token"] == "access-2"


def test_update_user_tokens(db):
    store.upsert_user("12345", "strava", "Name", "access-1", "refresh-1", 100)
    store.update_user_tokens("12345", "access-2", "refresh-2", 200)

    user = store.get_user("12345")
    assert user["access_token"] == "access-2"
    assert user["refresh_token"] == "refresh-2"
    assert user["token_expires_at"] == 200


def test_get_user_missing(db):
    assert store.get_user("nonexistent") is None


def test_db_file_is_private(db):
    import stat

    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_delete_user_access_tokens_only_hits_that_user(db):
    store.save_access_token("a1", '{"subject": "alice"}')
    store.save_access_token("a2", '{"subject": "alice"}')
    store.save_access_token("b1", '{"subject": "bob"}')

    assert store.delete_user_access_tokens("alice") == 2
    assert store.get_access_token_row("a1") is None
    assert store.get_access_token_row("b1") is not None


def test_stale_pending_rows_are_pruned_and_rejected(db):
    import time as _time

    store.save_pending_authorization("old", "c", "http://x", True, "ch", [], None, None)
    store.save_pending_connect_step("old-step", "42", {"k": "v"})
    stale = _time.time() - store.PENDING_TTL_SECONDS - 1
    with store._connect() as conn:
        conn.execute("UPDATE pending_authorizations SET created_at = ?", (stale,))
        conn.execute("UPDATE pending_connect_steps SET created_at = ?", (stale,))

    # A stale authorization is rejected even before pruning.
    assert store.pop_pending_authorization("old") is None

    store.save_pending_authorization("old2", "c", "http://x", True, "ch", [], None, None)
    with store._connect() as conn:
        conn.execute("UPDATE pending_authorizations SET created_at = ? WHERE state = 'old2'", (stale,))
    store.save_pending_authorization("new", "c", "http://x", True, "ch", [], None, None)

    with store._connect() as conn:
        states = [r["state"] for r in conn.execute("SELECT state FROM pending_authorizations")]
        steps = conn.execute("SELECT COUNT(*) FROM pending_connect_steps").fetchone()[0]
    assert states == ["new"]
    assert steps == 0
