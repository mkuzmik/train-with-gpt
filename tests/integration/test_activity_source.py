"""Hosted users choose where activities come from: Strava (default) or intervals.icu.

Black box over HTTP with real OAuth logins; Strava (FakeStrava) and
intervals.icu (respx) are the only stand-ins.
"""

import base64

import pytest
from httpx import Response
from mcp.shared.memory import create_connected_server_and_client_session

from train_with_gpt.activity_source import INTERVALS_NOT_CONNECTED_MESSAGE, INTERVALS_NOT_OFFERED_MESSAGE
from train_with_gpt.server import app as mcp_server

INTERVALS = "https://intervals.icu/api/v1"
DAY = {"start_date": "2024-01-15", "end_date": "2024-01-15"}
ACTIVITY_TOOLS = {"get_activities", "analyze_activity", "analyze_lap"}

INTERVALS_RUN = {
    "id": "i555", "type": "Run", "distance": 8000, "moving_time": 2400,
    "start_date": "2024-01-15T07:30:00Z", "average_heartrate": 140,
}


def _basic_auth_key(request) -> str:
    return base64.b64decode(request.headers["authorization"].split()[1]).decode().split(":", 1)[1]


def _connect_intervals(http_mock):
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(200, json={"id": "i1", "name": "Test"}))


def test_hosted_activity_tools_offer_a_source_argument_defaulting_to_strava(login):
    tools = {tool["name"]: tool for tool in login(9).list_tools()}

    for name in ACTIVITY_TOOLS:
        source = tools[name]["inputSchema"]["properties"]["source"]
        assert source["enum"] == ["strava", "intervals_icu"]
        assert source["default"] == "strava"
    assert "source" not in tools["get_sleep_data"]["inputSchema"]["properties"]


async def test_personal_path_offers_no_source_argument():
    async with create_connected_server_and_client_session(mcp_server) as personal:
        tools = {tool.name: tool for tool in (await personal.list_tools()).tools}

    for name in ACTIVITY_TOOLS:
        assert "source" not in tools[name].inputSchema["properties"]


@pytest.mark.intervals_login_step
def test_source_intervals_icu_reads_the_users_own_intervals_account(login, strava, http_mock):
    _connect_intervals(http_mock)
    listed = http_mock.get(f"{INTERVALS}/athlete/0/activities").mock(
        return_value=Response(200, json=[INTERVALS_RUN])
    )
    mcp = login(31, intervals_api_key="users-own-key")
    strava_calls_before = strava.activities_route.call_count

    output = mcp.call_tool("get_activities", {**DAY, "source": "intervals_icu"})

    assert "Found 1 activities for 2024-01-15" in output
    assert "🔗 ID: i555" in output
    assert _basic_auth_key(listed.calls.last.request) == "users-own-key"
    assert strava.activities_route.call_count == strava_calls_before


@pytest.mark.intervals_login_step
def test_analysis_with_source_intervals_icu_uses_its_own_laps(login, http_mock):
    """intervals.icu keeps the athlete's own lap edits (icu_intervals)."""
    _connect_intervals(http_mock)
    detail = http_mock.get(f"{INTERVALS}/activity/i555").mock(return_value=Response(200, json={
        **INTERVALS_RUN,
        "icu_intervals": [
            {"distance": 4000, "elapsed_time": 1200, "moving_time": 1200, "average_heartrate": 135,
             "start_time": 0, "end_time": 1200},
            {"distance": 4000, "elapsed_time": 1200, "moving_time": 1200, "average_heartrate": 145,
             "start_time": 1200, "end_time": 2400},
        ],
    }))
    http_mock.get(f"{INTERVALS}/activity/i555/streams").mock(return_value=Response(200, json=[
        {"type": "time", "data": list(range(2400))},
        {"type": "distance", "data": [i * 3.33 for i in range(2400)]},
    ]))
    mcp = login(32, intervals_api_key="users-own-key")

    analysis = mcp.call_tool("analyze_activity", {"activity_id": "i555", "source": "intervals_icu"})
    lap = mcp.call_tool("analyze_lap", {
        "activity_id": "i555", "lap_number": 2, "num_splits": 2, "source": "intervals_icu",
    })

    assert "Detailed Analysis for Activity i555" in analysis
    assert "Lap 2 Analysis — Activity i555" in lap
    assert {_basic_auth_key(call.request) for call in detail.calls} == {"users-own-key"}


def test_default_source_is_strava(login, strava):
    strava.activities[42] = []
    mcp = login(42)

    assert mcp.call_tool("get_activities", DAY) == "No activities found for 2024-01-15."
    assert mcp.call_tool("get_activities", {**DAY, "source": "strava"}) == "No activities found for 2024-01-15."
    assert strava.activities_route.call_count == 2


@pytest.mark.intervals_login_step
def test_source_intervals_icu_without_a_connection_explains_how_to_add_it(login, http_mock):
    activities = http_mock.get(f"{INTERVALS}/athlete/0/activities")
    mcp = login(43)  # skipped the intervals.icu step

    for name, args in (
        ("get_activities", DAY),
        ("analyze_activity", {"activity_id": "i555"}),
        ("analyze_lap", {"activity_id": "i555", "lap_number": 1, "num_splits": 2}),
    ):
        assert mcp.call_tool(name, {**args, "source": "intervals_icu"}) == INTERVALS_NOT_CONNECTED_MESSAGE
    assert not activities.called


def test_source_intervals_icu_when_the_server_does_not_offer_it(login):
    assert login(44).call_tool("get_activities", {**DAY, "source": "intervals_icu"}) == INTERVALS_NOT_OFFERED_MESSAGE


def test_unknown_source_is_rejected(login, strava):
    output = login(77).call_tool("get_activities", {**DAY, "source": "garmin"})

    assert output.startswith("❌ Error: unknown source 'garmin'")
    assert not strava.activities_route.called
