"""OAuth Authorization Server provider for Claude <-> this MCP server.

Implements the shape `mcp.server.auth.provider.OAuthAuthorizationServerProvider`
expects (a Protocol, so no base class needed). `authorize()` doesn't show its
own consent screen - it immediately redirects to Strava's OAuth
(`strava_oauth.py`), the second leg of the nested flow. Once Strava's
callback resolves who the user is, `exchange_authorization_code()` mints our
own token, bound to that user id (`AuthorizationCode.subject`).

Codes and tokens are only honoured while their user is on the allowlist
(allowlist.py), so taking someone off the list locks them out on their next
request, without waiting for a year-long token to expire.
"""

import secrets
import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthClientInformationFull,
    OAuthToken,
)

from . import store
from .strava_oauth import build_strava_authorize_url

# Long-lived: Strava has no refresh-token concept on our side of the flow
# either (we refresh Strava's own token internally, see strava_client.py).
# If this token is ever lost/revoked, the user simply re-authorizes. Each
# device/client gets its own token, so revoking one (revoke_token, or
# store.delete_user_access_tokens for all of a user's) leaves others alone.
ACCESS_TOKEN_TTL_SECONDS = 365 * 24 * 3600


class TrainWithGptOAuthProvider:
    """OAuth AS provider backing the Claude <-> this-server leg of the flow."""

    def __init__(self, issuer_base_url: str, allowed_athlete_ids: frozenset[str]):
        self.issuer_base_url = issuer_base_url
        self.allowed_athlete_ids = allowed_athlete_ids

    def _is_allowed(self, user_id: str | None) -> bool:
        return user_id is not None and user_id in self.allowed_athlete_ids

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = store.get_client(client_id)
        return OAuthClientInformationFull.model_validate_json(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        store.save_client(client_info.client_id, client_info.model_dump_json())

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        state = secrets.token_urlsafe(24)
        store.save_pending_authorization(
            state=state,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            code_challenge=params.code_challenge,
            scopes=params.scopes or [],
            resource=params.resource,
            claude_state=params.state,
        )
        return build_strava_authorize_url(self.issuer_base_url, state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        data = store.get_auth_code(authorization_code)
        if not data:
            return None
        code = AuthorizationCode.model_validate_json(data)
        if code.client_id != client.client_id or code.expires_at < time.time():
            return None
        if not self._is_allowed(code.subject):
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        store.mark_auth_code_used(authorization_code.code)

        token = secrets.token_urlsafe(32)
        access_token = AccessToken(
            token=token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=int(time.time()) + ACCESS_TOKEN_TTL_SECONDS,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )
        store.save_access_token(token, access_token.model_dump_json())

        return OAuthToken(
            access_token=token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(authorization_code.scopes) if authorization_code.scopes else None,
        )

    async def load_refresh_token(self, client, refresh_token: str):
        return None  # we never issue refresh tokens to Claude

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        raise NotImplementedError("train-with-gpt does not issue refresh tokens")

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = store.get_access_token_row(token)
        if not data:
            return None
        access_token = AccessToken.model_validate_json(data)
        if access_token.expires_at and access_token.expires_at < time.time():
            return None
        if not self._is_allowed(access_token.subject):
            return None  # -> 401; the row is kept, so re-adding the user restores access
        return access_token

    async def revoke_token(self, token) -> None:
        # We only ever issue access tokens (no refresh tokens), so this is
        # always one of ours; deleting the row makes load_access_token reject it.
        store.delete_access_token(token.token)
