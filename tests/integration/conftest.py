"""Integration fixtures: the real app, driven only through its public interfaces.

Only external dependencies are stubbed:
- Strava's OAuth + REST API -> `FakeStrava`, a small stateful respx stub
- intervals.icu's REST API  -> respx routes on `http_mock`
- the training-context git remote -> a local bare repo (`git_remote`)

The app is configured the way it is in production - through environment
variables read by `config.load()` at startup - and served from a fresh
`create_app()` per test.
"""

import base64
import hashlib
import itertools
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from httpx import Response
from starlette.testclient import TestClient

from tests.support import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
from train_with_gpt.config import config
from train_with_gpt.http_server import create_app

PUBLIC_URL = "http://localhost:8123"  # the SDK only allows plain http for localhost
CLAUDE_REDIRECT_URI = "http://localhost:9999/oauth/callback"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
STRAVA_API = "https://www.strava.com/api/v3"
MCP_PROTOCOL_VERSION = "2025-06-18"

# The synthetic athletes the tests sign in as; the server's allowlist
# (ALLOWED_STRAVA_ATHLETE_IDS) admits exactly these unless a test overrides it
# with @pytest.mark.allowed_athletes("...").
ALLOWED_ATHLETES = (1, 3, 5, 9, 31, 32, 42, 43, 44, 77, 1001, 2002, 4242)


class FakeStrava:
    """Stateful stand-in for Strava's OAuth token endpoint and REST API.

    Issues rotating access/refresh tokens, rejects unknown/expired access
    tokens with 401 like Strava does, and serves per-athlete activities.
    """

    def __init__(self, router):
        self._counter = itertools.count(1)
        self._codes = {}  # Strava auth code -> athlete
        self._access = {}  # access token -> athlete id
        self._refresh = {}  # refresh token -> athlete id
        self.athletes = {}
        self.activities = {}  # athlete id -> list of activity dicts
        self.token_requests = []

        self.deauthorized = []  # access tokens Strava was asked to revoke

        self.token_route = router.post(STRAVA_TOKEN_URL).mock(side_effect=self._token)
        self.deauthorize_route = router.post(STRAVA_DEAUTHORIZE_URL).mock(side_effect=self._deauthorize)
        self.activities_route = router.get(f"{STRAVA_API}/athlete/activities").mock(side_effect=self._list_activities)

    def approve(self, athlete_id: int, firstname="Test", lastname="Athlete") -> str:
        """The user approved our app on Strava's consent screen; returns Strava's code."""
        code = f"strava-code-{next(self._counter)}"
        self.athletes[athlete_id] = {"id": athlete_id, "firstname": firstname, "lastname": lastname}
        self._codes[code] = athlete_id
        return code

    def expire_access_tokens(self, athlete_id: int) -> None:
        """Make Strava reject the athlete's current access token(s) (401)."""
        for token, owner in list(self._access.items()):
            if owner == athlete_id:
                del self._access[token]

    def _issue(self, athlete_id: int) -> dict:
        n = next(self._counter)
        access, refresh = f"strava-access-{athlete_id}-{n}", f"strava-refresh-{athlete_id}-{n}"
        self._access[access] = athlete_id
        self._refresh[refresh] = athlete_id
        return {"access_token": access, "refresh_token": refresh, "expires_at": int(time.time()) + 6 * 3600}

    def _token(self, request):
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.token_requests.append(form)
        if (form.get("client_id"), form.get("client_secret")) != (STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET):
            return Response(401, json={"message": "Bad client credentials"})
        if form.get("grant_type") == "authorization_code" and form.get("code") in self._codes:
            athlete_id = self._codes.pop(form["code"])
            return Response(200, json={**self._issue(athlete_id), "athlete": self.athletes[athlete_id]})
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") in self._refresh:
            athlete_id = self._refresh.pop(form["refresh_token"])  # Strava rotates refresh tokens
            return Response(200, json=self._issue(athlete_id))
        return Response(400, json={"message": "Bad Request"})

    def token_is_valid(self, access_token: str) -> bool:
        """Whether Strava would still accept this access token."""
        return access_token in self._access

    def _deauthorize(self, request):
        """Revoke the app's grant: every access/refresh token of that athlete dies."""
        token = parse_qs(request.content.decode()).get("access_token", [""])[0]
        athlete_id = self._access.get(token)
        if athlete_id is None:
            return Response(401, json={"message": "Authorization Error"})
        self.deauthorized.append(token)
        for tokens in (self._access, self._refresh):
            for key, owner in list(tokens.items()):
                if owner == athlete_id:
                    del tokens[key]
        return Response(200, json={"access_token": token})

    def _athlete_for(self, request):
        auth = request.headers.get("Authorization", "")
        return self._access.get(auth.removeprefix("Bearer "))

    def _list_activities(self, request):
        athlete_id = self._athlete_for(request)
        if athlete_id is None:
            return Response(401, json={"message": "Authorization Error"})
        return Response(200, json=self.activities.get(athlete_id, []))


class McpHttpClient:
    """Speaks MCP JSON-RPC over the Streamable HTTP transport at /mcp."""

    def __init__(self, http: TestClient, bearer: str | None):
        self.http = http
        self.bearer = bearer
        self._ids = itertools.count(1)

    def post(self, payload: dict):
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        }
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        return self.http.post("/mcp", json=payload, headers=headers, follow_redirects=False)

    def request(self, method: str, params: dict | None = None) -> dict:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            payload["params"] = params
        response = self.post(payload)
        assert response.status_code == 200, (response.status_code, response.text)
        message = _parse_jsonrpc(response)
        assert message["id"] == payload["id"]
        assert "error" not in message, message
        return message["result"]

    def notify(self, method: str) -> None:
        response = self.post({"jsonrpc": "2.0", "method": method})
        assert response.status_code == 202, (response.status_code, response.text)

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "integration-tests", "version": "0"},
        })
        self.notify("notifications/initialized")
        return result

    def list_tools(self) -> list[dict]:
        return self.request("tools/list")["tools"]

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        assert not result.get("isError"), result
        assert len(result["content"]) == 1, result
        return result["content"][0]["text"]


def _parse_jsonrpc(response) -> dict:
    """A JSON-RPC message from either a JSON body or an SSE stream."""
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    data = [line[len("data:"):].strip() for line in response.text.splitlines() if line.startswith("data:")]
    assert len(data) == 1, response.text
    return json.loads(data[0])


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def query_params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def register_client(http: TestClient) -> dict:
    """Dynamic client registration, as Claude does it."""
    response = http.post("/register", json={
        "client_name": "Claude",
        "redirect_uris": [CLAUDE_REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    })
    assert response.status_code == 201, response.text
    return response.json()


def through_interstitials(http: TestClient, response, intervals_api_key: str | None = None):
    """Act like the user's browser until we're redirected back to Claude.

    Follows redirects, and submits an HTML form page (the optional
    intervals.icu step) once, like a user would: with `intervals_api_key` if
    given, else by pressing "skip". If that lands on a form page again (e.g.
    the key was rejected), returns it so the caller can decide what's next.
    """
    submitted = False
    for _ in range(10):
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers["location"]
            if location.startswith(CLAUDE_REDIRECT_URI):
                break
            response = http.get(location, follow_redirects=False)
        elif "<form" in response.text and not submitted:
            submitted = True
            action = re.search(r'<form[^>]*action="([^"]+)"', response.text).group(1)
            fields = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', response.text))
            if intervals_api_key:
                fields.update(action="connect", api_key=intervals_api_key)
            else:
                fields.update(action="skip")
            response = http.post(action, data=fields, follow_redirects=False)
        else:
            break
    return response


def oauth_login(
    http: TestClient, strava: FakeStrava, athlete_id: int, firstname="Test", lastname="Athlete",
    intervals_api_key: str | None = None,
) -> str:
    """Full nested OAuth round trip for one athlete; returns our bearer token.

    Claude registers, sends the user to /authorize with PKCE, we bounce them to
    Strava, Strava redirects back to our callback with its code, the user goes
    through any interstitial page (the optional intervals.icu step, answered
    with `intervals_api_key` or skipped), we redirect to Claude with our own
    code, and Claude exchanges that at /token.
    """
    client = register_client(http)
    verifier, challenge = pkce_pair()

    authorize = http.get("/authorize", params={
        "response_type": "code",
        "client_id": client["client_id"],
        "redirect_uri": CLAUDE_REDIRECT_URI,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "claude-state",
        "resource": f"{PUBLIC_URL}/mcp",
    }, follow_redirects=False)
    assert authorize.status_code == 302, authorize.text
    strava_url = authorize.headers["location"]
    assert strava_url.startswith(f"{STRAVA_AUTHORIZE_URL}?")
    strava_params = query_params(strava_url)
    assert strava_params["client_id"] == STRAVA_CLIENT_ID
    assert strava_params["redirect_uri"] == f"{PUBLIC_URL}/oauth/strava/callback"

    # The user approves on Strava; Strava redirects the browser back to us.
    strava_code = strava.approve(athlete_id, firstname, lastname)
    callback = http.get(
        urlparse(strava_params["redirect_uri"]).path,
        params={"state": strava_params["state"], "code": strava_code, "scope": "read,activity:read_all"},
        follow_redirects=False,
    )
    callback = through_interstitials(http, callback, intervals_api_key)
    assert callback.status_code in (302, 303, 307), callback.text
    back_to_claude = callback.headers["location"]
    assert back_to_claude.startswith(CLAUDE_REDIRECT_URI)
    claude_params = query_params(back_to_claude)
    assert claude_params["state"] == "claude-state"

    token = http.post("/token", data={
        "grant_type": "authorization_code",
        "code": claude_params["code"],
        "redirect_uri": CLAUDE_REDIRECT_URI,
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "code_verifier": verifier,
    })
    assert token.status_code == 200, token.text
    body = token.json()
    assert body["token_type"].lower() == "bearer"
    return body["access_token"]


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "intervals_login_step: run the server with TOKEN_ENCRYPTION_KEY set, "
        "which adds the optional intervals.icu page to the OAuth login",
    )
    config.addinivalue_line(
        "markers", "allowed_athletes(value): run the server with ALLOWED_STRAVA_ATHLETE_IDS=value "
        "instead of the default ALLOWED_ATHLETES",
    )


@pytest.fixture
def server_env(request, monkeypatch, training_repo):
    """Production-style configuration: env vars, loaded by config.load()."""
    monkeypatch.setenv("PUBLIC_URL", PUBLIC_URL)
    monkeypatch.setenv("STRAVA_CLIENT_ID", STRAVA_CLIENT_ID)
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", STRAVA_CLIENT_SECRET)
    monkeypatch.setenv("TRAINING_REPO_PATH", str(training_repo))
    allowed = request.node.get_closest_marker("allowed_athletes")
    monkeypatch.setenv(
        "ALLOWED_STRAVA_ATHLETE_IDS",
        allowed.args[0] if allowed else ",".join(str(athlete) for athlete in ALLOWED_ATHLETES),
    )
    if request.node.get_closest_marker("intervals_login_step"):
        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    config.load()
    return training_repo


@pytest.fixture
def http(server_env):
    """The HTTP server (fresh app, lifespan running) behind a TestClient."""
    with TestClient(create_app(), base_url=PUBLIC_URL) as client:
        yield client


@pytest.fixture
def strava(http_mock):
    return FakeStrava(http_mock)


@pytest.fixture
def login(http, strava):
    """login(athlete_id, ...) -> an initialized McpHttpClient for that athlete."""
    def _login(athlete_id: int, **kwargs) -> McpHttpClient:
        mcp = McpHttpClient(http, oauth_login(http, strava, athlete_id, **kwargs))
        mcp.initialize()
        return mcp
    return _login
