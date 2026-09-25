"""Unit tests for the get_activities tool handler.

Handler + a real IntervalsClient/StravaClient; only intervals.icu's and
Strava's HTTP APIs are stubbed (respx).
"""

from datetime import datetime, timedelta

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_activities_handler

ACTIVITIES_URL = "https://intervals.icu/api/v1/athlete/0/activities"
STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


@pytest.fixture
def activities_api(http_mock):
    return http_mock.get(ACTIVITIES_URL)


async def test_default_is_last_seven_days(intervals, activities_api):
    activities_api.mock(return_value=Response(200, json=[
        {
            "id": "i123456789",
            "type": "Run",
            "distance": 10000.5,
            "moving_time": 3600,
            "total_elevation_gain": 150.2,
            "start_date": "2024-01-15T07:30:00Z",
            "average_heartrate": 145,
            "max_heartrate": 178,
            "average_cadence": 85,
            "average_temp": 12,
        },
        {
            "id": "i987654321",
            "type": "Ride",
            "distance": 25000,
            "moving_time": 4500,
            "average_speed": 5.5,
            "average_watts": 210,
            "average_cadence": 90,
            "start_date": "2024-01-14T18:00:00Z",
        },
    ]))

    before = datetime.now()
    output = text_of(await get_activities_handler({}, intervals))
    after = datetime.now()

    assert output.startswith("Found 2 activities for last 7 days:")
    # Run: distance, time, pace, elevation, HR, cadence doubled to steps/min, temp
    assert "2024-01-15 07:30" in output
    assert "10.00km | 1h00m00s | ⏱️ 5:59/km | ⛰️ 150m | ❤️ 145/178 bpm | 🔄 170 spm | 🌡️ 12°C" in output
    assert "🔗 ID: i123456789" in output
    # Ride: speed not pace, power, rpm
    assert "25.00km | 1h15m00s | ⏱️ 19.8km/h | ⚡ 210W | 🔄 90 rpm" in output

    params = activities_api.calls.last.request.url.params
    # (compare against both ends of the call, in case it straddled midnight)
    assert params["newest"] in {before.strftime("%Y-%m-%d"), after.strftime("%Y-%m-%d")}
    assert params["oldest"] in {
        (before - timedelta(days=7)).strftime("%Y-%m-%d"),
        (after - timedelta(days=7)).strftime("%Y-%m-%d"),
    }


async def test_explicit_date_range(intervals, activities_api):
    activities_api.mock(return_value=Response(200, json=[{
        "id": "i111", "type": "Run", "distance": 5000, "moving_time": 1800,
        "start_date": "2024-01-10T10:00:00Z",
    }]))

    output = text_of(await get_activities_handler({"start_date": "2024-01-10", "end_date": "2024-01-15"}, intervals))

    assert "Found 1 activities for 2024-01-10 to 2024-01-15" in output
    assert "5.00km" in output
    assert dict(activities_api.calls.last.request.url.params) == {"oldest": "2024-01-10", "newest": "2024-01-15"}


async def test_single_day(intervals, activities_api):
    activities_api.mock(return_value=Response(200, json=[]))

    output = text_of(await get_activities_handler({"start_date": "2024-01-10", "end_date": "2024-01-10"}, intervals))

    assert output == "No activities found for 2024-01-10."


async def test_activity_with_null_distance_and_time(intervals, activities_api):
    """Strength workouts come back with distance/moving_time present but null."""
    activities_api.mock(return_value=Response(200, json=[{
        "id": "i5", "type": "WeightTraining", "distance": None, "moving_time": None,
        "start_date": "2024-01-10T10:00:00Z",
    }]))

    output = text_of(await get_activities_handler({"start_date": "2024-01-10", "end_date": "2024-01-10"}, intervals))

    assert "WeightTraining" in output
    assert "No stats" in output


async def test_empty_result(intervals, activities_api):
    activities_api.mock(return_value=Response(200, json=[]))

    assert text_of(await get_activities_handler({}, intervals)) == "No activities found for last 7 days."


async def test_api_error(intervals, activities_api):
    activities_api.mock(return_value=Response(401, json={"error": "Unauthorized"}))

    output = text_of(await get_activities_handler({}, intervals))

    assert output.startswith("❌ Error:")
    assert "401" in output


@pytest.mark.parametrize("args, message", [
    ({"start_date": "2024/01/10", "end_date": "2024-01-15"}, "Invalid start_date format"),
    ({"start_date": "2024-01-10", "end_date": "15.01.2024"}, "Invalid end_date format"),
    ({"start_date": "2024-01-20", "end_date": "2024-01-15"}, "cannot be after end_date"),
])
async def test_invalid_arguments_make_no_request(intervals, activities_api, args, message):
    output = text_of(await get_activities_handler(args, intervals))

    assert output.startswith("❌")
    assert message in output
    assert not activities_api.called


async def test_strava_client_gets_all_pages_for_the_range(http_mock):
    route = http_mock.get(STRAVA_ACTIVITIES_URL).mock(return_value=Response(200, json=[{
        "id": 99, "sport_type": "TrailRun", "type": "Run", "distance": 8000, "moving_time": 3000,
        "start_date": "2024-01-12T09:00:00Z",
    }]))

    output = text_of(await get_activities_handler(
        {"start_date": "2024-01-10", "end_date": "2024-01-15"}, StravaClient(access_token="t"),
    ))

    assert "TrailRun" in output
    assert "🔗 ID: 99" in output
    params = route.calls.last.request.url.params
    assert int(params["after"]) == int(datetime(2024, 1, 10).timestamp())
    assert int(params["before"]) == int(datetime(2024, 1, 15, 23, 59, 59).timestamp())
    assert params["per_page"] == "200"
