"""Tests for TrainWithGptOAuthProvider (the Claude <-> this-server OAuth leg)."""

import time
from unittest.mock import patch

import pytest
from mcp.server.auth.provider import AuthorizationParams, OAuthClientInformationFull

from train_with_gpt import store
from train_with_gpt.oauth_provider import TrainWithGptOAuthProvider


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "store.db"
    with patch("train_with_gpt.store.DB_PATH", db_path):
        store.init_db()
        yield db_path


@pytest.fixture
def provider(db):
    return TrainWithGptOAuthProvider(issuer_base_url="http://localhost:8123")


@pytest.fixture
def claude_client():
    return OAuthClientInformationFull(
        client_id="claude-client",
        client_secret="claude-secret",
        redirect_uris=["http://localhost:9999/callback"],
    )


@pytest.mark.asyncio
async def test_register_and_get_client(provider, claude_client):
    await provider.register_client(claude_client)

    fetched = await provider.get_client("claude-client")
    assert fetched is not None
    assert fetched.client_id == "claude-client"
    assert str(fetched.redirect_uris[0]) == "http://localhost:9999/callback"


@pytest.mark.asyncio
async def test_get_client_unknown(provider):
    assert await provider.get_client("nope") is None


@pytest.mark.asyncio
async def test_authorize_redirects_to_strava_and_stores_pending(provider, claude_client):
    with patch("train_with_gpt.config.config.client_id", "strava-client-id"):
        params = AuthorizationParams(
            state="claude-state-xyz",
            scopes=["activity:read_all"],
            code_challenge="challenge-abc",
            redirect_uri="http://localhost:9999/callback",
            redirect_uri_provided_explicitly=True,
        )
        redirect_url = await provider.authorize(claude_client, params)

    assert redirect_url.startswith("https://www.strava.com/oauth/authorize?")
    assert "client_id=strava-client-id" in redirect_url
    assert "oauth%2Fstrava%2Fcallback" in redirect_url or "oauth/strava/callback" in redirect_url

    # A pending_authorizations row must exist, keyed by the state we generated
    # for the nested Strava leg (not Claude's own state) - extract it from the URL.
    import urllib.parse
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_url).query)
    our_state = qs["state"][0]

    pending = store.pop_pending_authorization(our_state)
    assert pending is not None
    assert pending["client_id"] == "claude-client"
    assert pending["redirect_uri"] == "http://localhost:9999/callback"
    assert pending["code_challenge"] == "challenge-abc"
    assert pending["claude_state"] == "claude-state-xyz"


@pytest.mark.asyncio
async def test_exchange_authorization_code_mints_access_token(provider, claude_client):
    from mcp.server.auth.provider import AuthorizationCode

    auth_code = AuthorizationCode(
        code="our-code-1",
        scopes=["activity:read_all"],
        expires_at=time.time() + 600,
        client_id="claude-client",
        code_challenge="challenge",
        redirect_uri="http://localhost:9999/callback",
        redirect_uri_provided_explicitly=True,
        subject="strava-user-42",
    )
    store.save_auth_code("our-code-1", auth_code.model_dump_json())

    token = await provider.exchange_authorization_code(claude_client, auth_code)

    assert token.token_type == "Bearer"
    assert token.refresh_token is None  # we never issue refresh tokens

    # The code should be marked used (single-use)
    assert store.get_auth_code("our-code-1") is None

    # The minted access token should resolve back to the right user
    access_token = await provider.load_access_token(token.access_token)
    assert access_token is not None
    assert access_token.subject == "strava-user-42"
    assert access_token.client_id == "claude-client"


@pytest.mark.asyncio
async def test_load_access_token_unknown(provider):
    assert await provider.load_access_token("no-such-token") is None


@pytest.mark.asyncio
async def test_load_access_token_expired(provider):
    from mcp.server.auth.provider import AccessToken

    expired = AccessToken(
        token="expired-token",
        client_id="claude-client",
        scopes=[],
        expires_at=int(time.time()) - 10,
        subject="user-1",
    )
    store.save_access_token("expired-token", expired.model_dump_json())

    assert await provider.load_access_token("expired-token") is None


@pytest.mark.asyncio
async def test_load_authorization_code_wrong_client_rejected(provider, claude_client):
    from mcp.server.auth.provider import AuthorizationCode

    auth_code = AuthorizationCode(
        code="code-for-other-client",
        scopes=[],
        expires_at=time.time() + 600,
        client_id="some-other-client",
        code_challenge="challenge",
        redirect_uri="http://localhost:9999/callback",
        redirect_uri_provided_explicitly=True,
        subject="user-1",
    )
    store.save_auth_code("code-for-other-client", auth_code.model_dump_json())

    loaded = await provider.load_authorization_code(claude_client, "code-for-other-client")
    assert loaded is None


@pytest.mark.asyncio
async def test_load_refresh_token_always_none(provider, claude_client):
    assert await provider.load_refresh_token(claude_client, "anything") is None
