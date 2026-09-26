"""Unit tests for the guidance tools: start_consultation, discuss_goals and get_current_date."""

from datetime import datetime

import pytest

from tests.support import referenced_tool_names, text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.server import list_tools
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import discuss_goals_handler, get_current_date_handler, start_consultation_handler


def _strava():
    return StravaClient(access_token="a", refresh_token="r", expires_at=0)


def _intervals():
    return IntervalsClient(api_key="synthetic-key")


# The (data, wellness) client pairs server.py resolves, per transport.
STDIO = pytest.param(_intervals, _intervals, id="stdio")
HOSTED = pytest.param(_strava, _strava, id="hosted")
HOSTED_WITH_INTERVALS = pytest.param(_strava, _intervals, id="hosted+intervals")


async def _registered_tool_names() -> set[str]:
    return {tool.name for tool in await list_tools()}


async def test_start_consultation_points_at_the_context_tools():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))

    assert output.startswith("🏃 Starting Training Consultation Session")
    for tool in ("get_current_date", "read_goals", "list_consultation_notes", "read_consultation_notes",
                 "search_consultation_notes", "get_activities"):
        assert tool in output
    assert "coach" in output.lower()
    assert "{data_sources}" not in output


async def test_start_consultation_on_stdio_names_intervals_for_everything():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))

    assert "**Training Activities (intervals.icu):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "**get_hrv_data**" in output
    assert "Strava" not in output


async def test_start_consultation_for_a_hosted_user_names_strava_and_no_wellness():
    output = text_of(await start_consultation_handler({}, _strava(), _strava()))

    assert "**Training Activities (Strava):**" in output
    assert "Training Activities (intervals.icu)" not in output
    assert "intervals.icu wellness data" not in output
    assert "**Recovery Metrics: not connected.**" in output
    assert "**get_hrv_data**" not in output
    assert "Consider recovery metrics alongside training data" not in output


async def test_start_consultation_for_a_hosted_user_with_intervals_connected():
    output = text_of(await start_consultation_handler({}, _strava(), _intervals()))

    assert "**Training Activities (Strava):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "not connected" not in output


@pytest.mark.parametrize("data, wellness", [STDIO, HOSTED, HOSTED_WITH_INTERVALS])
async def test_start_consultation_only_references_registered_tools(data, wellness):
    output = text_of(await start_consultation_handler({}, data(), wellness()))

    referenced = referenced_tool_names(output)
    assert {"get_activities", "read_goals"} <= referenced
    assert referenced <= await _registered_tool_names()


async def test_discuss_goals_only_references_registered_tools():
    output = text_of(await discuss_goals_handler({}))

    referenced = referenced_tool_names(output)
    assert {"get_activities", "save_goals"} <= referenced
    assert "get_last_week_activities" not in output
    assert referenced <= await _registered_tool_names()


def _formatted(moment: datetime) -> str:
    return moment.strftime(f"%A, %B {moment.day}, %Y (%Y-%m-%d)")


async def test_get_current_date_is_today():
    before = datetime.now()
    output = text_of(await get_current_date_handler({}))
    after = datetime.now()

    # (either side of the call, in case it straddled midnight)
    assert any(f"📅 Current date: {_formatted(moment)}\n" in output for moment in (before, after))
