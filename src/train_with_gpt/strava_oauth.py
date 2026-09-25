"""Strava-side OAuth glue for the multi-user flow.

This is the second leg of the nested OAuth flow (Claude -> our server ->
Strava). `build_strava_authorize_url` is called from `oauth_provider.py`'s
`authorize()` to send the browser to Strava's consent screen; the Starlette
route here handles Strava's redirect back once the user approves, then shows
the optional intervals.icu step (intervals_connect.py) or goes straight to
minting our own authorization code for Claude (authorization.py).
"""

import sys
from urllib.parse import urlencode

import httpx
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from starlette.routing import Route

from . import secret_box, store
from .authorization import complete_authorization
from .config import config
from .intervals_connect import start_connect_step
from .strava_client import AUTHORIZE_URL, SCOPES, TOKEN_URL, StravaClient

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


async def handle_strava_callback(request: Request):
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

    print(f"[Strava OAuth] Authenticated user {user_id} ({name})", file=sys.stderr)

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


strava_oauth_route = Route(STRAVA_CALLBACK_PATH, handle_strava_callback, methods=["GET"])
