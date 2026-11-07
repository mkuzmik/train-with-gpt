"""Planned turbo workouts on the intervals.icu calendar, black box over MCP.

Personal server: plan, read back and change a workout over the SDK's
in-memory transport. Hosted server: the tools aren't offered and a call
(e.g. from a client with a cached tool list) never reaches intervals.icu.
"""

import json

import pytest
from httpx import Response
from mcp.shared.memory import create_connected_server_and_client_session

from train_with_gpt.server import app as mcp_server
from train_with_gpt.tools import PLANNED_WORKOUT_TOOLS, PLANNED_WORKOUTS_HOSTED_MESSAGE

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


def test_hosted_users_are_not_offered_the_planning_tools(login):
    names = {tool["name"] for tool in login(9).list_tools()}
    assert not names & set(PLANNED_WORKOUT_TOOLS)


@pytest.mark.intervals_login_step
@pytest.mark.parametrize("tool, arguments", [
    ("plan_workout", PLAN),
    ("get_planned_workouts", {"start_date": "2030-03-05"}),
    ("update_planned_workout", {"workout_id": 501, "name": "x"}),
])
def test_hosted_calls_are_refused_without_touching_intervals(login, http_mock, tool, arguments):
    """Even with their own intervals.icu key connected: the hosted connect step
    only asked for read access to wellness and activities."""
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(200, json={"id": "i1", "name": "Test"}))
    events = http_mock.route(url__startswith=EVENTS)
    mcp = login(31, intervals_api_key="users-own-key")

    assert mcp.call_tool(tool, arguments) == PLANNED_WORKOUTS_HOSTED_MESSAGE
    assert not events.called
