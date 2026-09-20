#!/usr/bin/env python3
"""HTTP entrypoint for the MCP server (Streamable HTTP transport).

Runs the same `Server` instance as the stdio entrypoint (`server.py`), but
reachable over HTTP so it can be used remotely (e.g. as a Claude Custom
Connector) or from anywhere other than a locally-spawned stdio subprocess.

Auth is a single shared secret (`MCP_SHARED_SECRET`), checked as a bearer
token on every request to /mcp. This is deliberately not a full OAuth
Authorization Server - sufficient for single-user personal access, per the
"just me, multi-device" scope decided in docs/plans/intervals-icu-migration.md.
"""

import contextlib
import hmac
import os
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from .server import app as mcp_app

SHARED_SECRET = os.environ.get("MCP_SHARED_SECRET")

session_manager = StreamableHTTPSessionManager(app=mcp_app, stateless=True)


class BearerAuthMiddleware:
    """ASGI middleware enforcing a shared-secret bearer token on /mcp requests."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/mcp"):
            await self.asgi_app(scope, receive, send)
            return

        if not SHARED_SECRET:
            response = JSONResponse(
                {"error": "server misconfigured: MCP_SHARED_SECRET not set"},
                status_code=500,
            )
            await response(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        token = auth_header[len("Bearer "):] if auth_header.startswith("Bearer ") else ""

        if not token or not hmac.compare_digest(token, SHARED_SECRET):
            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.asgi_app(scope, receive, send)


async def handle_mcp(scope: Scope, receive: Receive, send: Send) -> None:
    await session_manager.handle_request(scope, receive, send)


async def health(request):
    return JSONResponse({"status": "ok"})


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with session_manager.run():
        print("[HTTP] MCP Streamable HTTP server ready at /mcp", file=sys.stderr)
        yield


starlette_app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/mcp", app=handle_mcp),
    ],
    middleware=[Middleware(BearerAuthMiddleware)],
    lifespan=lifespan,
)


def main():
    if not SHARED_SECRET:
        print(
            "[HTTP] WARNING: MCP_SHARED_SECRET is not set - all /mcp requests will be rejected.\n"
            "        Generate one with: openssl rand -hex 32",
            file=sys.stderr,
        )
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(starlette_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
