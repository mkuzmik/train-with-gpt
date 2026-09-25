"""Unit tests for the get_sleep_data tool handler (real IntervalsClient, stubbed HTTP)."""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.helpers import NO_WELLNESS_DATA_MESSAGE
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_sleep_data_handler

WELLNESS_URL = "https://intervals.icu/api/v1/athlete/0/wellness"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


@pytest.fixture
def wellness(http_mock):
    return http_mock.get(WELLNESS_URL)


async def test_single_night(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "sleepSecs": 28800, "sleepScore": 85.0}]))

    output = text_of(await get_sleep_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert "Night of 2024-01-15" in output
    assert "8h 0m | ⭐ Score: 85/100" in output
    assert dict(wellness.calls.last.request.url.params) == {"oldest": "2024-01-15", "newest": "2024-01-15"}


async def test_date_range_with_summary(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        {"id": "2024-01-15", "sleepSecs": 28800, "sleepScore": 80.0},
        {"id": "2024-01-16", "sleepSecs": 27000, "sleepScore": 78.0},
        {"id": "2024-01-17", "sleepSecs": 30600, "sleepScore": 82.0},
        {"id": "2024-01-18", "hrv": 50},  # no sleep that night: skipped
    ]))

    output = text_of(await get_sleep_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-18"}, intervals))

    assert "Found 3 night(s) with sleep data" in output
    assert "7h 30m" in output
    assert "Average Duration: 8h 0m" in output
    assert "Average Quality Score: 80.0/100" in output


async def test_night_without_score(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "sleepSecs": 3600 * 7}]))

    output = text_of(await get_sleep_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert "7h 0m | ⭐ No score" in output
    assert "Summary" not in output


async def test_no_data_found(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[]))

    output = text_of(await get_sleep_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output == "No sleep data found for the period 2024-01-15 to 2024-01-15"


async def test_api_error(intervals, wellness):
    wellness.mock(return_value=Response(500))

    output = text_of(await get_sleep_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output.startswith("❌ Error:")


@pytest.mark.parametrize("args, message", [
    ({"start_date": "2024-01-15"}, "Both start_date and end_date are required"),
    ({"start_date": "15-01-2024", "end_date": "2024-01-15"}, "Invalid date format"),
    ({"start_date": "2024-01-20", "end_date": "2024-01-15"}, "cannot be after end_date"),
    ({"start_date": "2024-01-01", "end_date": "2024-02-15"}, "Date range too large (45 days)"),
])
async def test_invalid_arguments_make_no_request(intervals, wellness, args, message):
    output = text_of(await get_sleep_data_handler(args, intervals))

    assert output.startswith("❌")
    assert message in output
    assert not wellness.called


async def test_strava_accounts_have_no_wellness_data(wellness):
    output = text_of(await get_sleep_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, StravaClient(access_token="t"),
    ))

    assert output == NO_WELLNESS_DATA_MESSAGE
    assert not wellness.called
