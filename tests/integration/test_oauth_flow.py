"""End-to-end OAuth + MCP over HTTP, black box.

Claude registers, logs a user in through our /authorize -> Strava -> our
callback -> /token dance, then calls tools over /mcp with the bearer token.
Only Strava (FakeStrava), intervals.icu and the git remote are stand-ins.
"""

from tests.support import remote_file, remote_files
from train_with_gpt.helpers import NO_WELLNESS_DATA_MESSAGE

from .conftest import (
    CLAUDE_REDIRECT_URI,
    PUBLIC_URL,
    McpHttpClient,
    oauth_login,
    pkce_pair,
    query_params,
    register_client,
)

ALL_TOOLS = {
    "start_consultation", "get_current_date", "get_activities", "get_sleep_data", "get_hrv_data",
    "get_resting_heart_rate", "analyze_activity", "analyze_lap", "setup_training_repo", "discuss_goals",
    "save_goals", "read_goals", "save_consultation_notes", "read_consultation_notes",
    "list_consultation_notes", "search_consultation_notes",
}


def test_full_round_trip_then_authenticated_tool_calls(http, strava, git_remote):
    strava.activities[4242] = [{
        "id": 987, "sport_type": "Run", "distance": 10000, "moving_time": 3000,
        "start_date": "2024-01-15T07:30:00Z", "average_heartrate": 150,
    }]

    bearer = oauth_login(http, strava, 4242, firstname="Jane", lastname="Doe")
    mcp = McpHttpClient(http, bearer)

    info = mcp.initialize()
    assert info["serverInfo"]["name"] == "train-with-gpt"

    assert {tool["name"] for tool in mcp.list_tools()} == ALL_TOOLS

    # get_activities goes to Strava with the user's own Strava token
    activities = mcp.call_tool("get_activities", {"start_date": "2024-01-14", "end_date": "2024-01-16"})
    assert "Found 1 activities for 2024-01-14 to 2024-01-16" in activities
    assert "10.00km | 50m00s | ⏱️ 5:00/km | ❤️ 150 bpm" in activities
    assert "🔗 ID: 987" in activities
    strava_request = strava.activities_route.calls.last.request
    assert strava_request.headers["Authorization"].startswith("Bearer strava-access-4242-")

    # Notes round trip, landing in the remote under notes/<user_id>/
    saved = mcp.call_tool("save_consultation_notes", {"notes": "Jane: build to 50km/week, watch the calf."})
    assert "saved, committed and pushed to remote" in saved

    notes_in_remote = [path for path in remote_files(git_remote) if path.startswith("notes/")]
    assert len(notes_in_remote) == 1
    assert notes_in_remote[0].startswith("notes/4242/")
    assert "watch the calf" in remote_file(git_remote, notes_in_remote[0])

    read = mcp.call_tool("read_consultation_notes", {"all": True})
    assert "Found 1 consultation note(s)" in read
    assert "watch the calf" in read


def test_strava_token_is_refreshed_and_the_rotated_token_persisted(http, strava):
    strava.activities[77] = []
    mcp = McpHttpClient(http, oauth_login(http, strava, 77))

    strava.expire_access_tokens(77)  # Strava now 401s the token we stored at login

    first = mcp.call_tool("get_activities", {"start_date": "2024-01-14", "end_date": "2024-01-16"})
    second = mcp.call_tool("get_activities", {"start_date": "2024-01-14", "end_date": "2024-01-16"})

    assert first == second == "No activities found for 2024-01-14 to 2024-01-16."
    # One code exchange at login, then exactly one refresh: the second request
    # reused the rotated token the first one persisted.
    assert [r["grant_type"] for r in strava.token_requests] == ["authorization_code", "refresh_token"]


def test_strava_consent_denied_is_sent_back_to_claude(http, strava):
    client = register_client(http)
    _, challenge = pkce_pair()
    authorize = http.get("/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": CLAUDE_REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "claude-state",
    }, follow_redirects=False)
    strava_state = query_params(authorize.headers["location"])["state"]

    callback = http.get("/oauth/strava/callback", params={"state": strava_state, "error": "access_denied"},
                        follow_redirects=False)

    assert callback.status_code in (302, 307)
    assert callback.headers["location"].startswith(CLAUDE_REDIRECT_URI)
    assert query_params(callback.headers["location"]) == {"error": "access_denied", "state": "claude-state"}
    assert not strava.token_route.called


def _authorize_and_get_code(http, strava, verifier_challenge, athlete_id=1):
    client = register_client(http)
    _, challenge = verifier_challenge
    authorize = http.get("/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": CLAUDE_REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    }, follow_redirects=False)
    strava_state = query_params(authorize.headers["location"])["state"]
    callback = http.get("/oauth/strava/callback", params={"state": strava_state, "code": strava.approve(athlete_id)},
                        follow_redirects=False)
    return client, query_params(callback.headers["location"])["code"]


def _exchange(http, client, code, verifier):
    return http.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": CLAUDE_REDIRECT_URI,
        "client_id": client["client_id"], "client_secret": client["client_secret"], "code_verifier": verifier,
    })


def test_token_exchange_enforces_pkce(http, strava):
    pair = pkce_pair()
    client, code = _authorize_and_get_code(http, strava, pair)

    wrong = _exchange(http, client, code, "not-the-verifier-" + "x" * 40)

    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"


def test_authorization_code_is_single_use(http, strava):
    pair = pkce_pair()
    client, code = _authorize_and_get_code(http, strava, pair)

    assert _exchange(http, client, code, pair[0]).status_code == 200
    replay = _exchange(http, client, code, pair[0])

    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"


def test_revoked_token_no_longer_works(http, strava):
    client = register_client(http)
    pair = pkce_pair()
    _, challenge = pair
    authorize = http.get("/authorize", params={
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": CLAUDE_REDIRECT_URI,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }, follow_redirects=False)
    strava_state = query_params(authorize.headers["location"])["state"]
    callback = http.get("/oauth/strava/callback", params={"state": strava_state, "code": strava.approve(5)},
                        follow_redirects=False)
    bearer = _exchange(http, client, query_params(callback.headers["location"])["code"], pair[0]).json()["access_token"]
    mcp = McpHttpClient(http, bearer)
    mcp.initialize()

    revoke = http.post("/revoke", data={
        "token": bearer, "client_id": client["client_id"], "client_secret": client["client_secret"],
    })

    assert revoke.status_code == 200
    assert mcp.post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).status_code == 401


def test_each_login_gets_its_own_token(http, strava):
    laptop = oauth_login(http, strava, 9)
    phone = oauth_login(http, strava, 9)

    assert laptop != phone
    for bearer in (laptop, phone):
        McpHttpClient(http, bearer).initialize()


def test_authorization_server_metadata(http):
    metadata = http.get("/.well-known/oauth-authorization-server").json()

    assert metadata["issuer"].rstrip("/") == PUBLIC_URL
    assert metadata["authorization_endpoint"] == f"{PUBLIC_URL}/authorize"
    assert metadata["token_endpoint"] == f"{PUBLIC_URL}/token"
    assert metadata["registration_endpoint"] == f"{PUBLIC_URL}/register"
    assert metadata["revocation_endpoint"] == f"{PUBLIC_URL}/revoke"
    assert "S256" in metadata["code_challenge_methods_supported"]


def test_wellness_tools_explain_strava_has_no_wellness_data(login):
    mcp = login(31)

    for tool in ("get_sleep_data", "get_hrv_data", "get_resting_heart_rate"):
        assert mcp.call_tool(tool, {"start_date": "2024-01-15", "end_date": "2024-01-16"}) == NO_WELLNESS_DATA_MESSAGE


def test_oauth_sessions_cannot_reconfigure_the_training_repo(login, tmp_path, git_remote):
    mcp = login(32)

    output = mcp.call_tool("setup_training_repo", {"repo_path": str(tmp_path)})

    assert "can't be changed from an OAuth'd session" in output
    # Still pointing at the original repo: saving goals lands in its remote.
    assert "pushed to remote" in mcp.call_tool("save_goals", {"goals_text": "Still here"})
    assert "Still here" in remote_file(git_remote, "goals/32.md")
