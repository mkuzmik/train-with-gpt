"""Strava-side OAuth glue for the multi-user flow.

This is the second leg of the nested OAuth flow (Claude -> our server ->
Strava). `build_strava_authorize_url` is called from `oauth_provider.py`'s
`authorize()` to send the browser to Strava's consent screen; the Starlette
route here handles Strava's redirect back once the user approves, then shows
the optional intervals.icu step (intervals_connect.py) or goes straight to
minting our own authorization code for Claude (authorization.py).

Only athletes on the allowlist (allowlist.py) get past the callback. Anyone
else is refused right after the token exchange, before anything about them
is stored: their Strava grant is revoked and no code is issued.
"""

import sys
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from . import secret_box, store
from .authorization import complete_authorization
from .config import config
from .intervals_connect import start_connect_step
from .strava_client import AUTHORIZE_URL, SCOPES, TOKEN_URL, StravaClient, deauthorize

STRAVA_CALLBACK_PATH = "/oauth/strava/callback"


def strava_redirect_uri(issuer_base_url: str) -> str:
    """The callback URL we register with Strava for this leg of the flow."""
    return f"{issuer_base_url.rstrip('/')}{STRAVA_CALLBACK_PATH}"


def build_strava_authorize_url(issuer_base_url: str, state: str) -> str:
    """Build the URL to redirect the browser to for the Strava consent screen."""
    params = {
        "client_id": config.client_id,
        "redirect_uri": strava_redirect_uri(issuer_base_url),
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPES,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


NOT_ALLOWED_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Train with GPT - not available</title>
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem;">
<h1>This server is private</h1>
<p>This Train with GPT server isn't available for your Strava account.
Nothing from your Strava account was stored, and the server has asked Strava
to remove its access to your account.</p>
<p>You can close this window.</p>
</body>
</html>
"""


def not_allowed_response() -> HTMLResponse:
    return HTMLResponse(NOT_ALLOWED_PAGE, status_code=403)


def create_strava_oauth_route(allowed_athlete_ids: frozenset[str]) -> Route:
    """The Strava callback route, admitting only `allowed_athlete_ids` (see allowlist.py)."""

    async def endpoint(request: Request):
        return await handle_strava_callback(request, allowed_athlete_ids)

    return Route(STRAVA_CALLBACK_PATH, endpoint, methods=["GET"])


async def handle_strava_callback(request: Request, allowed_athlete_ids: frozenset[str]):
    """Handle Strava's redirect back after the user approves/denies our app."""
    params = request.query_params
    error = params.get("error")
    state = params.get("state")
    code = params.get("code")

    if not state:
        return PlainTextResponse("Missing state parameter", status_code=400)

    pending = store.pop_pending_authorization(state)
    if not pending:
        return PlainTextResponse("Unknown or expired authorization request", status_code=400)

    if error:
        redirect = construct_redirect_uri(pending["redirect_uri"], error=error, state=pending["claude_state"])
        return RedirectResponse(redirect)

    if not code:
        return PlainTextResponse("Missing code from Strava", status_code=400)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
        response.raise_for_status()
        token_data = response.json()

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token")
    expires_at = token_data.get("expires_at")
    athlete = token_data.get("athlete") or {}

    user_id = str(athlete["id"]) if athlete.get("id") else None
    name = f"{athlete.get('firstname', '')} {athlete.get('lastname', '')}".strip() or None

    if not user_id:
        # Strava usually embeds the athlete summary in the token response; fall
        # back to an explicit profile call if it's ever missing.
        strava = StravaClient(access_token)
        profile = await strava.get_athlete()
        user_id = str(profile["id"])
        name = f"{profile.get('firstname', '')} {profile.get('lastname', '')}".strip() or None

    if user_id not in allowed_athlete_ids:
        # Refuse before storing anything: no user row, tokens or name, no code
        # for Claude. Revoke the grant Strava just gave us, so we hold nothing.
        # The pending authorization was already consumed above. Deliberately
        # no id or name in the log.
        revoked = await deauthorize(access_token)
        print(
            "[Strava OAuth] Refused sign-in: athlete not on the allowlist "
            f"(Strava grant {'revoked' if revoked else 'NOT revoked - deauthorize failed'})",
            file=sys.stderr,
        )
        return not_allowed_response()

    print(f"[Strava OAuth] Authenticated user {user_id}", file=sys.stderr)

    store.upsert_user(
        user_id=user_id,
        provider="strava",
        name=name,
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=expires_at,
    )

    if secret_box.is_configured():
        return start_connect_step(pending, user_id)
    return complete_authorization(pending, user_id)
