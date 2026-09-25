"""Unit tests for the get_hrv_data tool handler (real IntervalsClient, stubbed HTTP)."""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.helpers import NO_WELLNESS_DATA_MESSAGE
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_hrv_data_handler

WELLNESS_URL = "https://intervals.icu/api/v1/athlete/0/wellness"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


@pytest.fixture
def wellness(http_mock):
    return http_mock.get(WELLNESS_URL)


async def test_single_day(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[{"id": "2024-01-15", "hrv": 52.0}]))

    output = text_of(await get_hrv_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert "💓 HRV: 52ms" in output
    assert dict(wellness.calls.last.request.url.params) == {"oldest": "2024-01-15", "newest": "2024-01-15"}


async def test_date_range_newest_first_with_summary(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[
        {"id": "2024-01-15", "hrv": 52.0},
        {"id": "2024-01-16", "hrv": 48.0},
        {"id": "2024-01-17", "restingHR": 50},  # no HRV that night: skipped
    ]))

    output = text_of(await get_hrv_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-17"}, intervals))

    assert "Found 2 night(s) with HRV data" in output
    assert output.index("📅 2024-01-16") < output.index("📅 2024-01-15")
    assert "Period Average: 50.0ms (2 days)" in output
    assert "Range: 48ms - 52ms" in output
    assert "Rolling Avg" not in output


async def test_rolling_averages_use_most_recent_days(intervals, wellness):
    records = [{"id": f"2024-01-{day:02d}", "hrv": 40 if day <= 16 else 60} for day in range(1, 31)]
    wellness.mock(return_value=Response(200, json=records))

    output = text_of(await get_hrv_data_handler({"start_date": "2024-01-01", "end_date": "2024-01-30"}, intervals))

    assert "7-day Rolling Avg: 60.0ms" in output
    assert "14-day Rolling Avg: 60.0ms" in output
    assert "28-day Rolling Avg: 50.0ms" in output


async def test_no_data_found(intervals, wellness):
    wellness.mock(return_value=Response(200, json=[]))

    output = text_of(await get_hrv_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output == "No HRV data found for the period 2024-01-15 to 2024-01-15"


async def test_api_error(intervals, wellness):
    wellness.mock(return_value=Response(500))

    output = text_of(await get_hrv_data_handler({"start_date": "2024-01-15", "end_date": "2024-01-15"}, intervals))

    assert output.startswith("❌ Error:")
    assert "INTERVALS_API_KEY" in output


@pytest.mark.parametrize("args, message", [
    ({"start_date": "2024-01-15"}, "Both start_date and end_date are required"),
    ({"start_date": "2024-01-15", "end_date": "yesterday"}, "Invalid date format"),
    ({"start_date": "2024-01-20", "end_date": "2024-01-15"}, "cannot be after end_date"),
    ({"start_date": "2024-01-01", "end_date": "2024-02-15"}, "Date range too large (45 days)"),
])
async def test_invalid_arguments_make_no_request(intervals, wellness, args, message):
    output = text_of(await get_hrv_data_handler(args, intervals))

    assert output.startswith("❌")
    assert message in output
    assert not wellness.called


async def test_strava_accounts_have_no_wellness_data(wellness):
    output = text_of(await get_hrv_data_handler(
        {"start_date": "2024-01-15", "end_date": "2024-01-15"}, StravaClient(access_token="t"),
    ))

    assert output == NO_WELLNESS_DATA_MESSAGE
    assert not wellness.called
