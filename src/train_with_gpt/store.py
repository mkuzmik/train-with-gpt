"""SQLite-backed store for multi-user OAuth.

Holds everything the MCP-facing OAuth Authorization Server needs: clients
Claude dynamically registers, authorization codes and access tokens we issue,
in-flight Strava authorizations (bridging our /authorize redirect to Strava's
callback), and each authenticated user's Strava credentials.

SDK models (OAuthClientInformationFull, AuthorizationCode, AccessToken) are
stored as their own JSON serialization rather than column-mapped, so this
module stays free of any dependency on `mcp.server.auth` and just deals in
plain values.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path.home() / ".config" / "train-with-gpt" / "store.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _connect() if db_path is None else sqlite3.connect(db_path) as conn:
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


# --- pending_authorizations --------------------------------------------------

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
    """Fetch and delete a pending authorization (single-use)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM pending_authorizations WHERE state = ?", (state,)).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM pending_authorizations WHERE state = ?", (state,))
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
