"""Final step of the nested OAuth flow: hand Claude our own authorization code."""

import secrets
import time

from mcp.server.auth.provider import AuthorizationCode, construct_redirect_uri
from starlette.responses import RedirectResponse

from . import store

AUTH_CODE_TTL_SECONDS = 600  # 10 minutes, standard for OAuth authorization codes


def complete_authorization(pending: dict, user_id: str) -> RedirectResponse:
    """Mint our code for `user_id` and redirect back to Claude's original redirect_uri.

    `pending` is the Claude /authorize request stashed by oauth_provider.authorize().
    """
    our_code = secrets.token_urlsafe(32)
    auth_code = AuthorizationCode(
        code=our_code,
        scopes=pending["scopes"],
        expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
        client_id=pending["client_id"],
        code_challenge=pending["code_challenge"],
        redirect_uri=pending["redirect_uri"],
        redirect_uri_provided_explicitly=pending["redirect_uri_provided_explicitly"],
        resource=pending["resource"],
        subject=user_id,
    )
    store.save_auth_code(our_code, auth_code.model_dump_json())

    redirect = construct_redirect_uri(pending["redirect_uri"], code=our_code, state=pending["claude_state"])
    # 303 so the browser follows with a GET even when coming from a form POST.
    return RedirectResponse(redirect, status_code=303)
