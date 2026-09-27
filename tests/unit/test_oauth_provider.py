"""Unit tests for TrainWithGptOAuthProvider (the Claude <-> this-server OAuth leg).

Runs against a real temp SQLite store; no mocks.
"""

import time
import urllib.parse

import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthClientInformationFull,
)

from tests.support import STRAVA_CLIENT_ID
from train_with_gpt import store
from train_with_gpt.oauth_provider import ACCESS_TOKEN_TTL_SECONDS, TrainWithGptOAuthProvider


@pytest.fixture
def provider(db):
    return TrainWithGptOAuthProvider(
        issuer_base_url="http://localhost:8123",
        allowed_athlete_ids=frozenset({"user-1", "strava-user-42", "u"}),
    )


@pytest.fixture
def claude_client():
    return OAuthClientInformationFull(
        client_id="claude-client",
        client_secret="claude-secret",
        redirect_uris=["http://localhost:9999/callback"],
    )


def _auth_code(code, client_id="claude-client", expires_at=None, subject="user-1", scopes=()):
    return AuthorizationCode(
        code=code,
        scopes=list(scopes),
        expires_at=time.time() + 600 if expires_at is None else expires_at,
        client_id=client_id,
        code_challenge="challenge",
        redirect_uri="http://localhost:9999/callback",
        redirect_uri_provided_explicitly=True,
        subject=subject,
    )


async def test_register_and_get_client(provider, claude_client):
    await provider.register_client(claude_client)

    fetched = await provider.get_client("claude-client")
    assert fetched is not None
    assert fetched.client_id == "claude-client"
    assert str(fetched.redirect_uris[0]) == "http://localhost:9999/callback"


async def test_get_client_unknown(provider):
    assert await provider.get_client("nope") is None


async def test_authorize_redirects_to_strava_and_stores_pending(provider, claude_client, strava_app_credentials):
    params = AuthorizationParams(
        state="claude-state-xyz",
        scopes=["activity:read_all"],
        code_challenge="challenge-abc",
        redirect_uri="http://localhost:9999/callback",
        redirect_uri_provided_explicitly=True,
    )
    redirect_url = await provider.authorize(claude_client, params)

    assert redirect_url.startswith("https://www.strava.com/oauth/authorize?")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query)
    assert qs["client_id"] == [STRAVA_CLIENT_ID]
    assert qs["redirect_uri"] == ["http://localhost:8123/oauth/strava/callback"]

    # A pending_authorizations row must exist, keyed by the state we generated
    # for the nested Strava leg (not Claude's own state).
    our_state = qs["state"][0]
    assert our_state != "claude-state-xyz"

    pending = store.pop_pending_authorization(our_state)
    assert pending is not None
    assert pending["client_id"] == "claude-client"
    assert pending["redirect_uri"] == "http://localhost:9999/callback"
    assert pending["code_challenge"] == "challenge-abc"
    assert pending["claude_state"] == "claude-state-xyz"
    assert pending["scopes"] == ["activity:read_all"]


async def test_exchange_authorization_code_mints_access_token(provider, claude_client):
    auth_code = _auth_code("our-code-1", subject="strava-user-42", scopes=["activity:read_all"])
    store.save_auth_code("our-code-1", auth_code.model_dump_json())

    token = await provider.exchange_authorization_code(claude_client, auth_code)

    assert token.token_type == "Bearer"
    assert token.refresh_token is None  # we never issue refresh tokens
    assert token.expires_in == ACCESS_TOKEN_TTL_SECONDS
    assert token.scope == "activity:read_all"

    # The code is single-use
    assert store.get_auth_code("our-code-1") is None
    assert await provider.load_authorization_code(claude_client, "our-code-1") is None

    # The minted access token resolves back to the right user
    access_token = await provider.load_access_token(token.access_token)
    assert access_token is not None
    assert access_token.subject == "strava-user-42"
    assert access_token.client_id == "claude-client"


async def test_each_exchange_mints_a_distinct_token(provider, claude_client):
    first = _auth_code("code-a", subject="u")
    second = _auth_code("code-b", subject="u")
    store.save_auth_code("code-a", first.model_dump_json())
    store.save_auth_code("code-b", second.model_dump_json())

    token_a = await provider.exchange_authorization_code(claude_client, first)
    token_b = await provider.exchange_authorization_code(claude_client, second)

    assert token_a.access_token != token_b.access_token


async def test_load_authorization_code_valid(provider, claude_client):
    store.save_auth_code("good-code", _auth_code("good-code").model_dump_json())

    loaded = await provider.load_authorization_code(claude_client, "good-code")

    assert loaded is not None
    assert loaded.subject == "user-1"


async def test_load_authorization_code_wrong_client_rejected(provider, claude_client):
    code = _auth_code("code-for-other-client", client_id="some-other-client")
    store.save_auth_code("code-for-other-client", code.model_dump_json())

    assert await provider.load_authorization_code(claude_client, "code-for-other-client") is None


async def test_load_authorization_code_expired_rejected(provider, claude_client):
    store.save_auth_code("old-code", _auth_code("old-code", expires_at=time.time() - 1).model_dump_json())

    assert await provider.load_authorization_code(claude_client, "old-code") is None


async def test_load_access_token_unknown(provider):
    assert await provider.load_access_token("no-such-token") is None


async def test_load_access_token_expired(provider):
    expired = AccessToken(
        token="expired-token",
        client_id="claude-client",
        scopes=[],
        expires_at=int(time.time()) - 10,
        subject="user-1",
    )
    store.save_access_token("expired-token", expired.model_dump_json())

    assert await provider.load_access_token("expired-token") is None


async def test_load_refresh_token_always_none(provider, claude_client):
    assert await provider.load_refresh_token(claude_client, "anything") is None


async def test_exchange_refresh_token_not_supported(provider, claude_client):
    with pytest.raises(NotImplementedError):
        await provider.exchange_refresh_token(claude_client, None, [])


async def test_revoke_token_invalidates_only_that_token(provider):
    def issue(token):
        access_token = AccessToken(
            token=token, client_id="claude-client", scopes=[],
            expires_at=int(time.time()) + 3600, subject="strava-user-42",
        )
        store.save_access_token(token, access_token.model_dump_json())
        return access_token

    laptop, phone = issue("laptop-token"), issue("phone-token")

    await provider.revoke_token(laptop)

    assert await provider.load_access_token("laptop-token") is None
    assert await provider.load_access_token("phone-token") == phone


# --- allowlist ---------------------------------------------------------------

def _issue_token(token, subject):
    access_token = AccessToken(
        token=token, client_id="claude-client", scopes=[], expires_at=int(time.time()) + 3600, subject=subject,
    )
    store.save_access_token(token, access_token.model_dump_json())
    return access_token


async def test_load_access_token_rejects_a_user_not_on_the_allowlist(provider):
    _issue_token("outsider-token", "someone-else")

    assert await provider.load_access_token("outsider-token") is None


async def test_load_access_token_rejects_a_token_without_subject(provider):
    _issue_token("anonymous-token", None)

    assert await provider.load_access_token("anonymous-token") is None


async def test_taking_a_user_off_the_allowlist_rejects_their_existing_token(db):
    issued = _issue_token("user-token", "user-1")
    before = TrainWithGptOAuthProvider("http://localhost:8123", allowed_athlete_ids=frozenset({"user-1"}))
    after = TrainWithGptOAuthProvider("http://localhost:8123", allowed_athlete_ids=frozenset({"user-2"}))

    assert await before.load_access_token("user-token") == issued
    assert await after.load_access_token("user-token") is None
    # Not deleted: putting the user back on the list restores access.
    assert await before.load_access_token("user-token") == issued


async def test_empty_allowlist_rejects_every_token_and_code(db, claude_client):
    provider = TrainWithGptOAuthProvider("http://localhost:8123", allowed_athlete_ids=frozenset())
    _issue_token("user-token", "user-1")
    store.save_auth_code("code-1", _auth_code("code-1").model_dump_json())

    assert await provider.load_access_token("user-token") is None
    assert await provider.load_authorization_code(claude_client, "code-1") is None


async def test_load_authorization_code_rejects_a_user_not_on_the_allowlist(provider, claude_client):
    store.save_auth_code("outsider-code", _auth_code("outsider-code", subject="someone-else").model_dump_json())

    assert await provider.load_authorization_code(claude_client, "outsider-code") is None
