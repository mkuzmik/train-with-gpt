"""Unit tests for the multi-user OAuth SQLite store, against a real temp DB.

The `db` fixture (tests/conftest.py) initialises a fresh store.db in the
test's own tmp HOME.
"""

import sqlite3
import stat

from train_with_gpt import store


def _age_rows(db, table, seconds, where="1=1"):
    """Backdate created_at directly in the DB file (simulates time passing)."""
    with sqlite3.connect(db) as conn:
        conn.execute(f"UPDATE {table} SET created_at = created_at - ? WHERE {where}", (seconds,))


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
    assert stat.S_IMODE(db.stat().st_mode) == 0o600


def test_delete_user_access_tokens_only_hits_that_user(db):
    store.save_access_token("a1", '{"subject": "alice"}')
    store.save_access_token("a2", '{"subject": "alice"}')
    store.save_access_token("b1", '{"subject": "bob"}')

    assert store.delete_user_access_tokens("alice") == 2
    assert store.get_access_token_row("a1") is None
    assert store.get_access_token_row("b1") is not None


def test_init_db_is_idempotent_and_keeps_data(db):
    store.save_client("client-1", "{}")
    store.init_db()
    assert store.get_client("client-1") == "{}"


def test_init_db_at_explicit_path_creates_private_file(tmp_path):
    path = tmp_path / "nested" / "other.db"
    store.init_db(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pending_authorization_round_trips_resource_and_implicit_redirect(db):
    store.save_pending_authorization(
        state="s", client_id="c", redirect_uri="http://x/cb",
        redirect_uri_provided_explicitly=False, code_challenge="ch",
        scopes=[], resource="https://server/mcp", claude_state=None,
    )
    pending = store.pop_pending_authorization("s")
    assert pending["redirect_uri_provided_explicitly"] is False
    assert pending["resource"] == "https://server/mcp"
    assert pending["claude_state"] is None
    assert pending["scopes"] == []


def test_stale_pending_rows_are_pruned_and_rejected(db):
    stale = store.PENDING_TTL_SECONDS + 1
    store.save_pending_authorization("old", "c", "http://x", True, "ch", [], None, None)
    store.save_pending_connect_step("old-step", "42", {"k": "v"})
    _age_rows(db, "pending_authorizations", stale)
    _age_rows(db, "pending_connect_steps", stale)

    # A stale authorization is rejected even before pruning.
    assert store.pop_pending_authorization("old") is None

    store.save_pending_authorization("old2", "c", "http://x", True, "ch", [], None, None)
    _age_rows(db, "pending_authorizations", stale, where="state = 'old2'")
    store.save_pending_authorization("new", "c", "http://x", True, "ch", [], None, None)

    # Saving a new row pruned every stale one, in both tables.
    with sqlite3.connect(db) as conn:
        states = [row[0] for row in conn.execute("SELECT state FROM pending_authorizations")]
        steps = conn.execute("SELECT COUNT(*) FROM pending_connect_steps").fetchone()[0]
    assert states == ["new"]
    assert steps == 0


def test_intervals_connection_round_trip(db):
    assert store.get_intervals_connection("42") is None

    store.save_intervals_connection("42", "i777", "Jane D", "ciphertext-1")
    store.save_intervals_connection("42", "i777", "Jane D", "ciphertext-2")

    connection = store.get_intervals_connection("42")
    assert (connection["athlete_id"], connection["athlete_name"], connection["encrypted_api_key"]) == (
        "i777", "Jane D", "ciphertext-2",
    )

    store.delete_intervals_connection("42")
    assert store.get_intervals_connection("42") is None


def test_pending_connect_step_can_be_claimed_once(db):
    store.save_pending_connect_step("tok", "42", {"client_id": "claude"})

    assert store.claim_pending_connect_step("tok", 60) == {"user_id": "42", "pending": {"client_id": "claude"}}
    assert store.claim_pending_connect_step("tok", 60) is None


def test_expired_connect_step_is_rejected(db):
    store.save_pending_connect_step("tok", "42", {})
    _age_rows(db, "pending_connect_steps", 120)

    assert store.claim_pending_connect_step("tok", max_age_seconds=60) is None


