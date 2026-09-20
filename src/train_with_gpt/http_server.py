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

import uvicorn
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from . import store
from .oauth_provider import TrainWithGptOAuthProvider
from .server import app as mcp_app
from .strava_oauth import strava_oauth_route

PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{os.environ.get('PORT', '8000')}")

store.init_db()

provider = TrainWithGptOAuthProvider(issuer_base_url=PUBLIC_URL)
token_verifier = ProviderTokenVerifier(provider)

session_manager = StreamableHTTPSessionManager(app=mcp_app, stateless=True)


async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
    await session_manager.handle_request(scope, receive, send)


# /mcp requires a valid bearer token this server issued: AuthenticationMiddleware
# (Starlette's own) populates scope["user"]/scope["auth"] from the token via
# BearerAuthBackend, AuthContextMiddleware makes it available to tool handlers
# via get_access_token(), and RequireAuthMiddleware 401s if it's missing/invalid.
mcp_asgi_app = RequireAuthMiddleware(handle_mcp, required_scopes=[])
mcp_asgi_app = AuthContextMiddleware(mcp_asgi_app)
mcp_asgi_app = AuthenticationMiddleware(mcp_asgi_app, backend=BearerAuthBackend(token_verifier))


async def health(request):
    return JSONResponse({"status": "ok"})


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with session_manager.run():
        print(f"[HTTP] MCP Streamable HTTP server ready at /mcp (issuer: {PUBLIC_URL})", file=sys.stderr)
        yield


starlette_app = Starlette(
    routes=[
        Route("/health", health),
        *create_auth_routes(
            provider,
            issuer_url=AnyHttpUrl(PUBLIC_URL),
            client_registration_options=ClientRegistrationOptions(enabled=True),
        ),
        strava_oauth_route,
        Mount("/mcp", app=mcp_asgi_app),
    ],
    lifespan=lifespan,
)


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
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
