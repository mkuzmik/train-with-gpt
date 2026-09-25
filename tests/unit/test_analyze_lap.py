"""Unit tests for the analyze_lap tool handler.

Handler + real IntervalsClient/StravaClient; only the HTTP APIs are stubbed.
"""

import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import analyze_lap_handler

INTERVALS = "https://intervals.icu/api/v1"
STRAVA = "https://www.strava.com/api/v3"


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


def _two_lap_activity(activity_id, sport_type="Run"):
    """Two 1500 s laps, as intervals.icu returns them in icu_intervals."""
    return {
        "id": activity_id,
        "type": sport_type,
        "icu_intervals": [
            {"distance": 5000, "elapsed_time": 1500, "start_time": 0, "end_time": 1500},
            {"distance": 5000, "elapsed_time": 1500, "start_time": 1500, "end_time": 3000},
        ],
    }


def _streams(n=3000, speed=3.33, cadence=85):
    """intervals.icu stream payload, 1 sample/s, spanning both laps."""
    return [
        {"type": "time", "data": list(range(n))},
        {"type": "distance", "data": [i * speed for i in range(n)]},
        {"type": "heartrate", "data": [150 + (i % 20) for i in range(n)]},
        {"type": "velocity_smooth", "data": [speed] * n},
        {"type": "cadence", "data": [cadence] * n},
        {"type": "watts", "data": [None] * n},
    ]


def _stub(http_mock, activity_id, activity, streams=None):
    http_mock.get(f"{INTERVALS}/activity/{activity_id}").mock(return_value=Response(200, json=activity))
    return http_mock.get(f"{INTERVALS}/activity/{activity_id}/streams").mock(
        return_value=Response(200, json=streams if streams is not None else _streams())
    )


def _rows(output):
    """The per-split table rows (after the dashed header rule)."""
    return output.split("-" * 80 + "\n", 1)[1].splitlines()


async def test_split_first_lap_into_quarters(intervals, http_mock):
    streams = _stub(http_mock, "i111111", _two_lap_activity("i111111"))

    output = text_of(await analyze_lap_handler(
        {"activity_id": "i111111", "lap_number": 1, "num_splits": 4}, intervals,
    ))

    assert "Lap 1 Analysis — Activity i111111" in output
    assert "Lap duration: 25m00s" in output
    assert "Split into 4 segments" in output
    rows = _rows(output)
    assert len(rows) == 4
    # 375 s per quarter at 3.33 m/s ≈ 1.245 km, 5:00/km, 170 spm, HR 150..169
    first = rows[0].split()
    assert first[0] == "1"
    assert first[1:3] == ["1.245", "km"]
    assert first[3] == "6m15s"
    assert first[4] == "5:01/km"
    assert first[5] == "150/159/169"
    assert first[6] == "—"  # no power
    assert first[7:] == ["170", "spm"]
    assert streams.calls.last.request.url.params["types"] == "time,distance,heartrate,velocity_smooth,cadence,watts"


async def test_second_lap_uses_its_own_time_window(intervals, http_mock):
    _stub(http_mock, "i222222", _two_lap_activity("i222222"))

    output = text_of(await analyze_lap_handler(
        {"activity_id": "i222222", "lap_number": 2, "num_splits": 2}, intervals,
    ))

    assert "Lap 2 Analysis" in output
    assert "2 segments" in output
    assert [row.split()[3] for row in _rows(output)] == ["12m30s", "12m30s"]


async def test_fast_running_lap_uses_pace_not_speed(intervals, http_mock):
    """A fast running lap (>21.6 km/h) must still show min/km pace, not km/h."""
    n = 154
    _stub(
        http_mock, "i555555",
        {"id": "i555555", "type": "Run", "icu_intervals": [{"start_time": 0, "end_time": 154}]},
        streams=_streams(n=n, speed=6.5, cadence=95),
    )

    output = text_of(await analyze_lap_handler(
        {"activity_id": "i555555", "lap_number": 1, "num_splits": 2}, intervals,
    ))

    assert "/km" in output
    assert "km/h" not in output
    assert "190 spm" in output
    assert "rpm" not in output


async def test_ride_shows_speed_and_rpm(intervals, http_mock):
    _stub(http_mock, "i6", _two_lap_activity("i6", sport_type="Ride"), streams=_streams(speed=10, cadence=90))

    output = text_of(await analyze_lap_handler({"activity_id": "i6", "lap_number": 1, "num_splits": 2}, intervals))

    assert "36.0 km/h" in output
    assert "90 rpm" in output
    assert "/km" not in output


@pytest.mark.parametrize("args, message", [
    ({"lap_number": 1, "num_splits": 4}, "activity_id is required"),
    ({"activity_id": "i1", "num_splits": 4}, "lap_number is required"),
    ({"activity_id": "i1", "lap_number": 1}, "num_splits is required"),
    ({"activity_id": "i1", "lap_number": -1, "num_splits": 4}, "lap_number must be >= 1"),
    ({"activity_id": "i1", "lap_number": 1, "num_splits": 1}, "num_splits must be >= 2"),
])
async def test_argument_validation_makes_no_request(intervals, http_mock, args, message):
    output = text_of(await analyze_lap_handler(args, intervals))

    assert output == f"❌ Error: {message}"
    assert not http_mock.calls


async def test_lap_number_beyond_available_laps(intervals, http_mock):
    streams = _stub(http_mock, "i333333", _two_lap_activity("i333333"))

    output = text_of(await analyze_lap_handler(
        {"activity_id": "i333333", "lap_number": 99, "num_splits": 4}, intervals,
    ))

    assert output == "❌ Error: lap_number 99 exceeds total laps (2)"
    assert not streams.called


async def test_activity_without_laps(intervals, http_mock):
    _stub(http_mock, "i444444", {"id": "i444444", "type": "Run", "icu_intervals": []})

    output = text_of(await analyze_lap_handler(
        {"activity_id": "i444444", "lap_number": 1, "num_splits": 4}, intervals,
    ))

    assert output == "❌ No lap data available for this activity"


async def test_activity_without_time_stream(intervals, http_mock):
    _stub(http_mock, "i7", _two_lap_activity("i7"), streams=[{"type": "heartrate", "data": [1, 2]}])

    output = text_of(await analyze_lap_handler({"activity_id": "i7", "lap_number": 1, "num_splits": 2}, intervals))

    assert output == "❌ No time stream data available for this activity"


async def test_strava_path_derives_lap_window_from_elapsed_times(http_mock):
    http_mock.get(f"{STRAVA}/activities/8").mock(return_value=Response(200, json={"sport_type": "Run"}))
    http_mock.get(f"{STRAVA}/activities/8/laps").mock(return_value=Response(200, json=[
        {"elapsed_time": 600}, {"elapsed_time": 400},
    ]))
    n = 1000
    http_mock.get(f"{STRAVA}/activities/8/streams").mock(return_value=Response(200, json={
        "time": {"data": list(range(n))},
        "distance": {"data": [i * 4.0 for i in range(n)]},
    }))

    output = text_of(await analyze_lap_handler(
        {"activity_id": "8", "lap_number": 2, "num_splits": 2}, StravaClient(access_token="t"),
    ))

    assert "Lap 2 Analysis — Activity 8" in output
    assert "Lap duration: 6m40s" in output
    assert [row.split()[3] for row in _rows(output)] == ["3m20s", "3m20s"]
