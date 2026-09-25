#!/usr/bin/env python3
"""HTTP entrypoint for the MCP server (Streamable HTTP transport, multi-user OAuth).

Runs the same `Server` instance as the stdio entrypoint (`server.py`), but
reachable over HTTP. Unlike the stdio path (still a single personal
intervals.icu API key, unchanged), this entrypoint is a full OAuth
Authorization Server for Claude: `/authorize` immediately redirects to
Strava's own OAuth consent screen (see `oauth_provider.py`/`strava_oauth.py`
for the nested-flow details), and every /mcp request must carry a valid
bearer token this server itself issued.
"""

import contextlib
import os
import sys
from typing import Optional

import uvicorn
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.routes import (
    build_resource_metadata_url,
    create_auth_routes,
    create_protected_resource_routes,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from . import store
from .oauth_provider import TrainWithGptOAuthProvider
from .server import app as mcp_app
from .strava_oauth import strava_oauth_route


def default_public_url() -> str:
    """The issuer/base URL from the environment (PUBLIC_URL, else localhost:PORT)."""
    return os.environ.get("PUBLIC_URL", f"http://localhost:{os.environ.get('PORT', '8000')}")


PUBLIC_URL = default_public_url()


async def health(request):
    return JSONResponse({"status": "ok"})


def create_app(public_url: Optional[str] = None) -> Starlette:
    """Build the HTTP app: OAuth AS routes, the Strava callback and the /mcp endpoint.

    Each call gets its own OAuth provider and MCP session manager (a session
    manager can only be run once), so tests can build a fresh app per test.
    The store is initialised on startup (lifespan), not at import time.
    """
    public_url = public_url or default_public_url()

    provider = TrainWithGptOAuthProvider(issuer_base_url=public_url)
    token_verifier = ProviderTokenVerifier(provider)

    session_manager = StreamableHTTPSessionManager(app=mcp_app, stateless=True)

    async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
        await session_manager.handle_request(scope, receive, send)

    # /mcp requires a valid bearer token this server issued: AuthenticationMiddleware
    # (Starlette's own) populates scope["user"]/scope["auth"] from the token via
    # BearerAuthBackend, AuthContextMiddleware makes it available to tool handlers
    # via get_access_token(), and RequireAuthMiddleware 401s if it's missing/invalid.
    mcp_resource_url = AnyHttpUrl(f"{public_url.rstrip('/')}/mcp")
    mcp_asgi_app = RequireAuthMiddleware(
        handle_mcp,
        required_scopes=[],
        resource_metadata_url=build_resource_metadata_url(mcp_resource_url),
    )
    mcp_asgi_app = AuthContextMiddleware(mcp_asgi_app)
    mcp_asgi_app = AuthenticationMiddleware(mcp_asgi_app, backend=BearerAuthBackend(token_verifier))

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        store.init_db()
        async with session_manager.run():
            print(f"[HTTP] MCP Streamable HTTP server ready at /mcp (issuer: {public_url})", file=sys.stderr)
            yield

    return Starlette(
        routes=[
            Route("/health", health),
            *create_auth_routes(
                provider,
                issuer_url=AnyHttpUrl(public_url),
                client_registration_options=ClientRegistrationOptions(enabled=True),
                revocation_options=RevocationOptions(enabled=True),
            ),
            *create_protected_resource_routes(
                mcp_resource_url, authorization_servers=[AnyHttpUrl(public_url)]
            ),
            strava_oauth_route,
            # Route, not Mount: a Mount redirects /mcp -> /mcp/, which behind a
            # TLS-terminating proxy risks a downgrade redirect strict clients reject.
            Route("/mcp", mcp_asgi_app),
        ],
        lifespan=lifespan,
    )


# The app uvicorn serves (main() below, or `uvicorn train_with_gpt.http_server:starlette_app`).
starlette_app = create_app(PUBLIC_URL)


def main():
    from .config import config

    if not config.client_id or not config.client_secret:
        # config.py already logs which of these are set; this is just an early,
        # loud warning specific to the OAuth path needing Strava credentials.
        print(
            "[HTTP] WARNING: no STRAVA_CLIENT_ID configured - the multi-user OAuth "
            "flow (/authorize) will fail until config.json has clientId/clientSecret "
            "or STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET are set.",
            file=sys.stderr,
        )
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        starlette_app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
