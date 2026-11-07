"""Planned turbo workouts on the intervals.icu calendar, black box over MCP.

Personal server: plan, read back and change a workout over the SDK's
in-memory transport. Hosted server (real OAuth logins over HTTP): each user
plans with their own connected intervals.icu key, and users without one are
told how to connect it.
"""

import base64
import json

import pytest
from httpx import Response
from mcp.shared.memory import create_connected_server_and_client_session

from train_with_gpt.server import app as mcp_server
from train_with_gpt.tools import (
    PLANNED_WORKOUT_TOOLS,
    PLANNING_NOT_CONNECTED_MESSAGE,
    PLANNING_NOT_OFFERED_MESSAGE,
)

INTERVALS = "https://intervals.icu/api/v1"
EVENTS = f"{INTERVALS}/athlete/0/events"
PLAN = {
    "date": "2030-03-05",
    "name": "Over-unders",
    "notes": "Smooth pedalling.",
    "steps": [
        {"duration_seconds": 600, "watts_low": 120, "watts_high": 190, "ramp": True, "label": "Warmup"},
        {"repeat": 4, "steps": [{"duration_seconds": 120, "watts": 270, "cadence_low": 95, "cadence_high": 100},
                                {"duration_seconds": 120, "watts": 230}]},
        {"duration_seconds": 300, "watts": 130, "cadence": 85},
    ],
}


def _text(result) -> str:
    assert not result.isError, result
    return result.content[0].text


def _event(**fields):
    return {"id": 501, "category": "WORKOUT", "type": "Ride", "indoor": True, "name": "Over-unders",
            "start_date_local": "2030-03-05T00:00:00", "moving_time": 2820, "icu_training_load": 55,
            "workout_doc": {"steps": [{"duration": 600, "ramp": True, "power": {"start": 120, "end": 190, "units": "w"}}]},
            **fields}


async def test_personal_server_plans_reads_back_and_updates_a_workout(http_mock, intervals_api_key):
    calendar: list[dict] = []
    http_mock.get(EVENTS).mock(side_effect=lambda request: Response(200, json=calendar))

    def create(request):
        body = json.loads(request.content)
        calendar.append(_event(name=body["name"], description=body["description"]))
        return Response(200, json=calendar[-1])

    def update(request):
        calendar[0].update(json.loads(request.content))
        return Response(200, json=calendar[0])

    created = http_mock.post(EVENTS).mock(side_effect=create)
    http_mock.get(f"{EVENTS}/501").mock(side_effect=lambda request: Response(200, json=calendar[0]))
    updated = http_mock.put(f"{EVENTS}/501").mock(side_effect=update)

    async with create_connected_server_and_client_session(mcp_server) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}
        planned = _text(await session.call_tool("plan_workout", PLAN))
        again = _text(await session.call_tool("plan_workout", PLAN))
        read = _text(await session.call_tool("get_planned_workouts", {"start_date": "2030-03-05"}))
        changed = _text(await session.call_tool("update_planned_workout", {
            "workout_id": 501, "date": "2030-03-06", "name": "Easy spin",
            "steps": [{"duration_seconds": 2400, "watts": 160, "cadence": 90}],
        }))

    assert tools["get_planned_workouts"].annotations.readOnlyHint is True
    assert tools["plan_workout"].annotations.readOnlyHint is False
    assert tools["update_planned_workout"].annotations.idempotentHint is True

    assert "✅ Planned on intervals.icu" in planned and "🆔 501" in planned
    assert json.loads(created.calls[0].request.content)["description"] == (
        "Smooth pedalling.\n\n"
        "- Warmup 10m ramp 120-190w\n\n"
        "4x\n- 2m 270w 95-100rpm\n- 2m 230w\n\n"
        "- 5m 130w 85rpm"
    )
    # A repeated request doesn't create a duplicate.
    assert created.call_count == 1
    assert "nothing was created" in again
    assert "Planned workouts for 2030-03-05 (1):" in read and "Over-unders (Ride, indoor)" in read

    body = json.loads(updated.calls.last.request.content)
    assert body["start_date_local"] == "2030-03-06T00:00:00"
    assert body["description"] == "- 40m 160w 90rpm"
    assert "✅ Updated on intervals.icu" in changed and "Easy spin" in changed


async def test_personal_server_validates_steps_against_the_schema(http_mock, intervals_api_key):
    created = http_mock.post(EVENTS)
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("plan_workout", {**PLAN, "steps": [{"duration_seconds": "ten", "watts": 200}]})

    assert result.isError
    assert not created.called


def test_hosted_users_are_offered_the_planning_tools(login):
    names = {tool["name"] for tool in login(9).list_tools()}
    assert set(PLANNED_WORKOUT_TOOLS) <= names


def _basic_auth_key(request) -> str:
    return base64.b64decode(request.headers["authorization"].split()[1]).decode().split(":", 1)[1]


@pytest.mark.intervals_login_step
def test_hosted_users_plan_on_their_own_calendar_with_their_own_key(login, http_mock, intervals_api_key):
    """Each hosted user's calls carry their own connected key: never another
    user's, and never the server's personal INTERVALS_API_KEY."""
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(200, json={"id": "i1", "name": "Test"}))
    listed = http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))
    created = http_mock.post(EVENTS).mock(return_value=Response(200, json=_event()))
    first = login(31, intervals_api_key="first-users-key")
    second = login(32, intervals_api_key="second-users-key")

    planned = first.call_tool("plan_workout", PLAN)
    read = second.call_tool("get_planned_workouts", {"start_date": "2030-03-05"})

    assert "✅ Planned on intervals.icu" in planned
    assert read == "No planned workouts for 2030-03-05."
    assert _basic_auth_key(created.calls.last.request) == "first-users-key"
    assert [_basic_auth_key(call.request) for call in listed.calls] == ["first-users-key", "second-users-key"]


@pytest.mark.intervals_login_step
@pytest.mark.parametrize("tool, arguments", [
    ("plan_workout", PLAN),
    ("get_planned_workouts", {"start_date": "2030-03-05"}),
    ("update_planned_workout", {"workout_id": 501, "name": "x"}),
])
def test_hosted_users_without_intervals_are_told_how_to_connect(login, http_mock, intervals_api_key, tool, arguments):
    events = http_mock.route(url__startswith=EVENTS)
    mcp = login(43)  # skipped the intervals.icu step

    assert mcp.call_tool(tool, arguments) == PLANNING_NOT_CONNECTED_MESSAGE
    assert not events.called  # in particular, not with the server's personal key


def test_hosted_planning_when_the_server_does_not_offer_intervals(login, http_mock):
    events = http_mock.route(url__startswith=EVENTS)
    assert login(44).call_tool("get_planned_workouts", {"start_date": "2030-03-05"}) == PLANNING_NOT_OFFERED_MESSAGE
    assert not events.called
