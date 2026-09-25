"""SQLite-backed store for multi-user OAuth.

Holds everything the MCP-facing OAuth Authorization Server needs: clients
Claude dynamically registers, authorization codes and access tokens we issue,
in-flight Strava authorizations (bridging our /authorize redirect to Strava's
callback), each authenticated user's Strava credentials, and optional
intervals.icu connections (API key encrypted by the caller, see secret_box.py).

SDK models (OAuthClientInformationFull, AuthorizationCode, AccessToken) are
stored as their own JSON serialization rather than column-mapped, so this
module stays free of any dependency on `mcp.server.auth` and just deals in
plain values.
"""

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".config" / "train-with-gpt" / "store.db"

# Upper bound on how long a half-finished login (Strava consent, intervals.icu
# page) stays usable. Older rows are rejected and pruned whenever a new one is
# saved, so logins abandoned mid-way don't accumulate.
PENDING_TTL_SECONDS = 60 * 60


def _open_private(db_path: Path) -> sqlite3.Connection:
    """Open the DB, making sure only the owner can read it.

    It holds bearer tokens, Strava refresh tokens and client secrets, and
    sqlite3 would otherwise create it with the process umask (usually 0644).
    SQLite gives its journal files the same mode as the DB file.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.close(os.open(db_path, os.O_CREAT | os.O_WRONLY, 0o600))
    os.chmod(db_path, 0o600)
    return sqlite3.connect(db_path)


def _connect() -> sqlite3.Connection:
    conn = _open_private(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() if db_path is None else _open_private(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS auth_codes (
                code TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS access_tokens (
                token TEXT PRIMARY KEY,
                data TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_authorizations (
                state TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                redirect_uri_provided_explicitly INTEGER NOT NULL,
                code_challenge TEXT NOT NULL,
                scopes TEXT NOT NULL,
                resource TEXT,
                claude_state TEXT,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                name TEXT,
                access_token TEXT NOT NULL,
                refresh_token TEXT,
                token_expires_at INTEGER,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS intervals_connections (
                user_id TEXT PRIMARY KEY,
                athlete_id TEXT NOT NULL,
                athlete_name TEXT,
                encrypted_api_key TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pending_connect_steps (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                pending TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            """
        )


# --- oauth_clients ---------------------------------------------------------

def save_client(client_id: str, data_json: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO oauth_clients (client_id, data, created_at) VALUES (?, ?, ?)",
            (client_id, data_json, time.time()),
        )


def get_client(client_id: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT data FROM oauth_clients WHERE client_id = ?", (client_id,)).fetchone()
        return row["data"] if row else None


# --- auth_codes --------------------------------------------------------------

def save_auth_code(code: str, data_json: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auth_codes (code, data, used) VALUES (?, ?, 0)",
            (code, data_json),
        )


def get_auth_code(code: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT data FROM auth_codes WHERE code = ? AND used = 0", (code,)).fetchone()
        return row["data"] if row else None


def mark_auth_code_used(code: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE auth_codes SET used = 1 WHERE code = ?", (code,))


# --- access_tokens -----------------------------------------------------------

def save_access_token(token: str, data_json: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO access_tokens (token, data) VALUES (?, ?)",
            (token, data_json),
        )


def get_access_token_row(token: str) -> Optional[str]:
    with _connect() as conn:
        row = conn.execute("SELECT data FROM access_tokens WHERE token = ?", (token,)).fetchone()
        return row["data"] if row else None


def delete_access_token(token: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM access_tokens WHERE token = ?", (token,))


def delete_user_access_tokens(user_id: str) -> int:
    """Revoke every token issued to one user (all their devices). Returns the count."""
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM access_tokens WHERE json_extract(data, '$.subject') = ?",
            (user_id,),
        )
        return cursor.rowcount


# --- pending_authorizations --------------------------------------------------

def _prune_pending(conn: sqlite3.Connection) -> None:
    cutoff = time.time() - PENDING_TTL_SECONDS
    conn.execute("DELETE FROM pending_authorizations WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM pending_connect_steps WHERE created_at < ?", (cutoff,))


def save_pending_authorization(
    state: str,
    client_id: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    code_challenge: str,
    scopes: list[str],
    resource: Optional[str],
    claude_state: Optional[str],
) -> None:
    with _connect() as conn:
        _prune_pending(conn)
        conn.execute(
            """INSERT OR REPLACE INTO pending_authorizations
               (state, client_id, redirect_uri, redirect_uri_provided_explicitly,
                code_challenge, scopes, resource, claude_state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                state,
                client_id,
                redirect_uri,
                1 if redirect_uri_provided_explicitly else 0,
                code_challenge,
                json.dumps(scopes),
                resource,
                claude_state,
                time.time(),
            ),
        )


def pop_pending_authorization(state: str) -> Optional[dict]:
    """Fetch and delete a pending authorization (single-use, expires after PENDING_TTL_SECONDS)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending_authorizations WHERE state = ?", (state,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM pending_authorizations WHERE state = ?", (state,))
        if row["created_at"] < time.time() - PENDING_TTL_SECONDS:
            return None
        return {
            "client_id": row["client_id"],
            "redirect_uri": row["redirect_uri"],
            "redirect_uri_provided_explicitly": bool(row["redirect_uri_provided_explicitly"]),
            "code_challenge": row["code_challenge"],
            "scopes": json.loads(row["scopes"]),
            "resource": row["resource"],
            "claude_state": row["claude_state"],
        }


# --- users ---------------------------------------------------------------

def upsert_user(
    user_id: str,
    provider: str,
    name: Optional[str],
    access_token: str,
    refresh_token: Optional[str],
    token_expires_at: Optional[int],
) -> None:
    now = time.time()
    with _connect() as conn:
        existing = conn.execute("SELECT created_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO users
               (user_id, provider, name, access_token, refresh_token, token_expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, provider, name, access_token, refresh_token, token_expires_at, created_at, now),
        )


def get_user(user_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def update_user_tokens(user_id: str, access_token: str, refresh_token: Optional[str], token_expires_at: Optional[int]) -> None:
    with _connect() as conn:
        conn.execute(
            """UPDATE users SET access_token = ?, refresh_token = ?, token_expires_at = ?, updated_at = ?
               WHERE user_id = ?""",
            (access_token, refresh_token, token_expires_at, time.time(), user_id),
        )


# --- intervals_connections ---------------------------------------------------

def save_intervals_connection(user_id: str, athlete_id: str, athlete_name: Optional[str], encrypted_api_key: str) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO intervals_connections
               (user_id, athlete_id, athlete_name, encrypted_api_key, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, athlete_id, athlete_name, encrypted_api_key, time.time()),
        )


def get_intervals_connection(user_id: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM intervals_connections WHERE user_id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def delete_intervals_connection(user_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM intervals_connections WHERE user_id = ?", (user_id,))


# --- pending_connect_steps -----------------------------------------------------
# The optional "add intervals.icu" page shown between Strava's callback and the
# redirect back to Claude. Holds the original Claude authorization request
# until the user submits or skips.

def save_pending_connect_step(token: str, user_id: str, pending: dict) -> None:
    with _connect() as conn:
        _prune_pending(conn)
        conn.execute(
            "INSERT OR REPLACE INTO pending_connect_steps (token, user_id, pending, created_at) VALUES (?, ?, ?, ?)",
            (token, user_id, json.dumps(pending), time.time()),
        )


def claim_pending_connect_step(token: str, max_age_seconds: float) -> Optional[dict]:
    """Atomically take a pending step: of concurrent claims, exactly one wins.

    The caller puts it back (save_pending_connect_step) if it wants the user
    to retry, e.g. after a rejected API key.
    """
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending_connect_steps WHERE token = ?", (token,)).fetchone()
        if not row:
            return None
        deleted = conn.execute("DELETE FROM pending_connect_steps WHERE token = ?", (token,)).rowcount
        if deleted != 1 or row["created_at"] < time.time() - max_age_seconds:
            return None
        return {"user_id": row["user_id"], "pending": json.loads(row["pending"])}
