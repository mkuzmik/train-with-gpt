"""Unit tests for the get_weight_data tool handler (real IntervalsClient, stubbed HTTP)."""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.helpers import NO_WELLNESS_DATA_MESSAGE
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_weight_data_handler, get_weight_data_tool

WELLNESS_URL = "https://intervals.icu/api/v1/athlete/0/wellness"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


@pytest.fixture
def wellness(http_mock):
    return http_mock.get(WELLNESS_URL)


async def test_single_day(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "weight": 70.2}]))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals,
    ))

    assert "2024-01-15: ⚖️  70.2 kg" in output
    assert dict(wellness.calls.last.request.url.params) == {"oldest": "2024-01-15", "newest": "2024-01-15"}


async def test_datapoints_with_summary(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        {"id": "2024-01-15", "weight": 71.0},
        {"id": "2024-01-16", "restingHR": 50},  # no weigh-in that day: skipped
        {"id": "2024-01-17", "weight": 70.0},
        {"id": "2024-01-18", "weight": 70.5},
    ]))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-18"}, intervals,
    ))

    assert "Found 3 day(s) with weight data" in output
    assert "2024-01-15: ⚖️  71.0 kg" in output and "2024-01-18: ⚖️  70.5 kg" in output
    assert "2024-01-16" not in output
    assert "Average weight: 70.5 kg" in output
    assert "Range: 70.0 kg - 71.0 kg" in output
    assert "Change: -0.5 kg (71.0 kg on 2024-01-15 → 70.5 kg on 2024-01-18)" in output


async def test_summary_mode_omits_datapoints(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        {"id": "2024-01-01", "weight": 72.0},
        {"id": "2024-06-30", "weight": 74.0},
    ]))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-01", "end_date": "2024-06-30", "mode": "summary"}, intervals,
    ))

    assert "⚖️" not in output
    assert "Found 2 day(s) with weight data" in output
    assert "Average weight: 73.0 kg" in output
    assert "Change: +2.0 kg" in output


async def test_long_range_up_to_366_days_is_allowed(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-03-01", "weight": 70.0}]))

    # Both ends are inclusive: 2024 is a leap year, so this is exactly 366 days.
    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-01", "end_date": "2024-12-31"}, intervals,
    ))

    assert "70.0 kg" in output
    assert wellness.called


def test_schema_accepts_null_mode_but_only_known_strings():
    mode = get_weight_data_tool().inputSchema["properties"]["mode"]

    assert mode["type"] == ["string", "null"]
    assert mode["enum"] == ["datapoints", "summary", None]


async def test_null_mode_means_the_default(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "weight": 70.2}]))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15", "mode": None}, intervals,
    ))

    assert "2024-01-15: ⚖️  70.2 kg" in output


async def test_no_data_found(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "restingHR": 50}]))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals,
    ))

    assert output == "No weight data found for the period 2024-01-15 to 2024-01-15"


async def test_api_error(intervals, wellness):
    wellness.mock(return_value=Response(403))

    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals,
    ))

    assert output.startswith("❌ Error:")


@pytest.mark.parametrize("args, message", [
    ({"start_date": "2024-01-15"}, "Both start_date and end_date are required"),
    ({"start_date": "2024-13-01", "end_date": "2024-01-15"}, "Invalid date format"),
    ({"start_date": "2024-01-20", "end_date": "2024-01-15"}, "cannot be after end_date"),
    ({"start_date": "2023-01-01", "end_date": "2024-02-15"}, "Date range too large (411 days)"),
    ({"start_date": "2024-01-01", "end_date": "2025-01-01"}, "Date range too large (367 days)"),
    ({"start_date": "2024-01-15", "end_date": "2024-01-15", "mode": "weekly"}, "Invalid mode 'weekly'"),
    ({"start_date": "2024-01-15", "end_date": "2024-01-15", "mode": ""}, "Invalid mode ''"),
    ({"start_date": "2024-01-15", "end_date": "2024-01-15", "mode": False}, "Invalid mode 'False'"),
])
async def test_invalid_arguments_make_no_request(intervals, wellness, args, message):
    output = text_of(await get_weight_data_handler(args, intervals))

    assert output.startswith("❌")
    assert message in output
    assert not wellness.called


async def test_strava_accounts_have_no_wellness_data(wellness):
    output = text_of(await get_weight_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, StravaClient(access_token="t"),
    ))

    assert output == NO_WELLNESS_DATA_MESSAGE
    assert "body weight" in output
    assert not wellness.called
