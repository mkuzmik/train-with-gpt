"""Unit tests for the analyze_activity tool handler.

Handler + real IntervalsClient/StravaClient; only the HTTP APIs are stubbed.
"""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import analyze_activity_handler

INTERVALS = "https://intervals.icu/api/v1"
STRAVA = "https://www.strava.com/api/v3"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


def _stub_activity(http_mock, activity_id, body, status=200):
    return http_mock.get(f"{INTERVALS}/activity/{activity_id}").mock(return_value=Response(status, json=body))


async def test_single_lap_with_precomputed_hr_zones(intervals, http_mock):
    activity_id = "i123456"
    route = _stub_activity(http_mock, activity_id, {
        "id": activity_id,
        "type": "Run",
        "icu_hr_zones": [130, 150, 170, 190],
        "icu_hr_zone_times": [1000, 2000, 3000, 1200],
        "icu_power_zones": None,
        "icu_zone_times": None,
        "icu_intervals": [{"distance": 21000, "moving_time": 7200, "start_time": 0, "end_time": 7200}],
    })

    output = text_of(await analyze_activity_handler({"activity_id": activity_id}, intervals))

    assert f"Activity {activity_id}" in output
    assert "only one lap" in output
    assert "Heart Rate Zone Distribution" in output
    assert "Zone 1 (0-130 bpm): 16m40s (13.9%)" in output
    assert "Zone 3 (151-170 bpm): 50m00s (41.7%)" in output
    assert route.calls.last.request.url.params["intervals"] == "true"


async def test_multiple_fast_running_laps_use_pace_not_speed(intervals, http_mock):
    """A fast running lap (>21.6 km/h) must still show min/km pace, not km/h."""
    lap = {
        "distance": 1000, "moving_time": 154, "elapsed_time": 154, "average_speed": 6.5,
        "average_heartrate": 175, "min_heartrate": 150, "max_heartrate": 182, "average_cadence": 95,
    }
    _stub_activity(http_mock, "i654321", {"id": "i654321", "type": "Run", "icu_intervals": [lap, lap]})

    output = text_of(await analyze_activity_handler({"activity_id": "i654321"}, intervals))

    assert "Lap 1: 1.00km | 2m34s | ⏱️ 2:34/km | ❤️ min:150/avg:175/max:182 bpm | 🔄 190 spm" in output
    assert "Lap 2:" in output
    assert "km/h" not in output
    assert "rpm" not in output


async def test_ride_laps_show_speed_power_and_rpm(intervals, http_mock):
    lap = {"distance": 10000, "moving_time": 1200, "average_speed": 8.33, "average_watts": 250, "average_cadence": 88}
    _stub_activity(http_mock, "i2", {
        "id": "i2", "type": "Ride", "icu_intervals": [lap, lap],
        "icu_power_zones": [150, 200, 999], "icu_zone_times": [600, 1200, 600],
    })

    output = text_of(await analyze_activity_handler({"activity_id": "i2"}, intervals))

    assert "⏱️ 30.0km/h | ⚡ 250W | 🔄 88 rpm" in output
    assert "Power Analysis" in output
    assert "Zone 3 (201+ W): 10m00s (25.0%)" in output


async def test_power_zones_fall_back_to_stream_when_not_precomputed(intervals, http_mock):
    _stub_activity(http_mock, "i3", {"id": "i3", "type": "Ride", "icu_power_zones": [100, 200, 999]})
    streams = http_mock.get(f"{INTERVALS}/activity/i3/streams").mock(
        return_value=Response(200, json=[{"type": "watts", "data": [50] * 60 + [150] * 120 + [300] * 60}])
    )

    output = text_of(await analyze_activity_handler({"activity_id": "i3"}, intervals))

    assert streams.calls.last.request.url.params["types"] == "watts"
    assert "No lap data available" in output
    assert "Zone 1 (0-100 W): 1m00s (25.0%)" in output
    assert "Zone 2 (101-200 W): 2m00s (50.0%)" in output
    assert "Zone 3 (201+ W): 1m00s (25.0%)" in output


async def test_activity_not_found(intervals, http_mock):
    _stub_activity(http_mock, "i999999", {}, status=404)

    output = text_of(await analyze_activity_handler({"activity_id": "i999999"}, intervals))

    assert output == "❌ Error: Activity not found"


async def test_missing_activity_id_makes_no_request(intervals, http_mock):
    output = text_of(await analyze_activity_handler({}, intervals))

    assert output == "❌ Error: activity_id is required"
    assert not http_mock.calls


async def test_strava_path_reconstructs_laps_and_zones(http_mock):
    http_mock.get(f"{STRAVA}/athlete/zones").mock(return_value=Response(200, json={
        "heart_rate": {"zones": [{"min": 0, "max": 140}, {"min": 140, "max": 160}, {"min": 160, "max": -1}]},
    }))
    http_mock.get(f"{STRAVA}/activities/77").mock(return_value=Response(200, json={"id": 77, "sport_type": "Run"}))
    n = 600
    http_mock.get(f"{STRAVA}/activities/77/streams").mock(return_value=Response(200, json={
        "time": {"data": list(range(n))},
        "heartrate": {"data": [130] * 300 + [170] * 300},
    }))
    http_mock.get(f"{STRAVA}/activities/77/laps").mock(return_value=Response(200, json=[
        {"distance": 1000, "elapsed_time": 300, "average_speed": 3.33, "average_heartrate": 130},
        {"distance": 1000, "elapsed_time": 300, "average_speed": 3.33, "average_heartrate": 170},
    ]))

    output = text_of(await analyze_activity_handler({"activity_id": "77"}, StravaClient(access_token="t")))

    assert "Detailed Analysis for Activity 77" in output
    # min/max HR per lap reconstructed from the HR stream
    assert "Lap 1: 1.00km | 5m00s | ⏱️ 5:00/km | ❤️ min:130/avg:130/max:170 bpm" in output
    assert "Zone 1 (0-140 bpm)" in output
    assert "Zone 3 (160+ bpm)" in output


async def test_strava_path_without_time_stream(http_mock):
    http_mock.get(f"{STRAVA}/athlete/zones").mock(return_value=Response(200, json={}))
    http_mock.get(f"{STRAVA}/activities/78").mock(return_value=Response(200, json={"type": "Run"}))
    http_mock.get(f"{STRAVA}/activities/78/streams").mock(return_value=Response(200, json={}))
    http_mock.get(f"{STRAVA}/activities/78/laps").mock(return_value=Response(200, json=[]))

    output = text_of(await analyze_activity_handler({"activity_id": 78}, StravaClient(access_token="t")))

    assert output == "❌ No time stream data available for this activity"
