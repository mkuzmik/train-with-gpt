"""Unit tests for the get_wellness tool handler (real IntervalsClient, stubbed HTTP)."""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.helpers import NO_WELLNESS_DATA_MESSAGE
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_wellness_handler, get_wellness_tool

WELLNESS_URL = "https://intervals.icu/api/v1/athlete/0/wellness"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


@pytest.fixture
def wellness(http_mock):
    return http_mock.get(WELLNESS_URL)


def _day(date, ctl, atl, ramp=None, load=None):
    return {"id": date, "ctl": ctl, "atl": atl, "rampRate": ramp, "ctlLoad": load}


async def test_short_range_lists_every_day_oldest_first(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        _day("2024-01-16", 51.0, 70.0, ramp=4.0, load=120),
        _day("2024-01-15", 50.0, 60.0, ramp=3.5, load=90),
    ]))

    output = text_of(await get_wellness_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-16", "metrics": "load"}, intervals,
    ))

    assert "📅 2024-01-15: fitness 50 | fatigue 60 | form -10 (-20%) | ramp +3.5 | load 90" in output
    assert "📅 2024-01-16: fitness 51 | fatigue 70 | form -19 (-37%) | ramp +4.0 | load 120" in output
    assert output.index("2024-01-15:") < output.index("2024-01-16:")
    assert dict(wellness.calls.last.request.url.params) == {
        "oldest": "2024-01-15", "newest": "2024-01-16", "fields": "id,ctl,atl,rampRate,ctlLoad",
    }


async def test_summary(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        _day("2024-01-15", 40.0, 30.0, load=50),
        _day("2024-01-16", 45.0, 65.0, load=150),
        _day("2024-01-17", 44.0, 50.0, ramp=2.0, load=None),
    ]))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-15", "end_date": "2024-01-17"}, intervals))

    assert "Latest (2024-01-17): fitness 44, fatigue 50, form -6 (-14%), ramp rate +2.0" in output
    assert "Fitness over the period: 40 → 44 (+4)" in output
    assert "Peak fitness: 45 on 2024-01-16" in output
    assert "Lowest form: -20 (-44%) on 2024-01-16" in output
    assert "Highest form: +10 (+25%) on 2024-01-15" in output
    assert "Total load: 200" in output
    # A day without ramp or load shows no placeholder for them.
    assert "📅 2024-01-17: fitness 44 | fatigue 50 | form -6 (-14%) | ramp +2.0\n" in output + "\n"
    assert "📅 2024-01-15: fitness 40 | fatigue 30 | form +10 (+25%) | load 50" in output


async def test_long_range_is_grouped_by_iso_week(intervals, wellness):
    # 2024-01-03 (Wed) .. 2024-01-21 (Sun): W01 partial, W02 and W03 full.
    records = [
        _day(f"2024-01-{d:02d}", 30.0 + d, 35.0 + d, ramp=float(d), load=10 * d) for d in range(3, 22)
    ]
    wellness.mock(return_value=Response(200, json=records))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-03", "end_date": "2024-01-21"}, intervals))

    assert "One row per ISO week" in output
    assert "📅 2024-W01 (2024-01-03 → 2024-01-07, partial week): fitness 37 | fatigue 42 | form -5 (-14%) | ramp +7.0 | week load 250" in output
    assert "📅 2024-W02 (2024-01-08 → 2024-01-14): fitness 44 | fatigue 49 | form -5 (-11%) | ramp +14.0 | week load 770" in output
    assert "📅 2024-W03 (2024-01-15 → 2024-01-21): fitness 51" in output
    assert "📅 2024-01-10:" not in output


async def test_daily_true_lists_every_day_of_a_long_range(intervals, wellness):
    records = [_day(f"2024-01-{d:02d}", 30.0, 30.0) for d in range(1, 22)]
    wellness.mock(return_value=Response(200, json=records))

    output = text_of(await get_wellness_handler(
        {"start_date": "2024-01-01", "end_date": "2024-01-21", "daily": True}, intervals,
    ))

    assert "📅 2024-01-10: fitness 30 | fatigue 30 | form +0 (+0%)" in output
    assert "ISO week" not in output


async def test_zero_fitness_has_no_form_percentage(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[_day("2024-01-15", 0.0, 0.0)]))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert "📅 2024-01-15: fitness 0 | fatigue 0 | form +0\n" in output + "\n"


async def test_days_without_fitness_data_are_skipped(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        {"id": "2024-01-14", "restingHR": 50},
        _day("2024-01-15", 50.0, 60.0),
    ]))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-14", "end_date": "2024-01-15"}, intervals))

    assert "2024-01-14" not in output.split("\n", 2)[2]
    assert "📅 2024-01-15:" in output


async def test_no_data_found(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "restingHR": 50}]))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output == "No fitness/fatigue data found for the period 2024-01-15 to 2024-01-15"


async def test_long_range_up_to_366_days_is_allowed(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[_day("2024-03-01", 50.0, 60.0)]))

    # Both ends are inclusive: 2024 is a leap year, so this is exactly 366 days.
    output = text_of(await get_wellness_handler({"start_date": "2024-01-01", "end_date": "2024-12-31"}, intervals))

    assert "2024-W09" in output
    assert wellness.called


async def test_api_error(intervals, wellness):
    wellness.mock(return_value=Response(500))

    output = text_of(await get_wellness_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output.startswith("❌ Error:")


@pytest.mark.parametrize("args, message", [
    ({"start_date": "2024-01-15"}, "Both start_date and end_date are required"),
    ({"start_date": "2024-01-15", "end_date": "yesterday"}, "Invalid date format"),
    ({"start_date": "2024-01-20", "end_date": "2024-01-15"}, "cannot be after end_date"),
    ({"start_date": "2024-01-01", "end_date": "2025-01-01"}, "Date range too large (367 days)"),
    ({"start_date": "2024-01-15", "end_date": "2024-01-15", "metrics": "sleep"}, "Unknown metrics 'sleep'"),
])
async def test_invalid_arguments_make_no_request(intervals, wellness, args, message):
    output = text_of(await get_wellness_handler(args, intervals))

    assert output.startswith("❌")
    assert message in output
    assert not wellness.called


async def test_strava_accounts_have_no_wellness_data(wellness):
    output = text_of(await get_wellness_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, StravaClient(access_token="t"),
    ))

    assert output == NO_WELLNESS_DATA_MESSAGE
    assert not wellness.called


def test_schema():
    tool = get_wellness_tool()
    properties = tool.inputSchema["properties"]

    assert tool.inputSchema["required"] == ["start_date", "end_date"]
    assert properties["metrics"]["enum"] == ["load"]
    assert properties["daily"]["type"] == "boolean"
    assert "up to 366 days" in tool.description
    assert "fitness" in tool.description and "fatigue" in tool.description and "form" in tool.description
