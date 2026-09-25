"""Tests for analyze_lap tool.

Tests end-to-end: tool call → IntervalsClient (mocked) → lap splitting → formatted output.
"""

import pytest
from unittest.mock import patch, AsyncMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_intervals():
    """Mock the server's IntervalsClient instance."""
    with patch('train_with_gpt.server.intervals') as mock:
        mock.get_activity = AsyncMock()
        mock.get_activity_streams = AsyncMock()
        yield mock


def _two_lap_activity(activity_id: str, sport_type: str = "Run") -> dict:
    """Build a mock activity with two 1500s laps via icu_intervals."""
    return {
        "id": activity_id,
        "type": sport_type,
        "icu_intervals": [
            {
                "distance": 5000,
                "moving_time": 1500,
                "elapsed_time": 1500,
                "average_speed": 3.33,
                "average_heartrate": 150,
                "min_heartrate": 140,
                "max_heartrate": 165,
                "average_cadence": 85,
                "start_time": 0,
                "end_time": 1500,
            },
            {
                "distance": 5000,
                "moving_time": 1500,
                "elapsed_time": 1500,
                "average_speed": 3.33,
                "average_heartrate": 155,
                "min_heartrate": 145,
                "max_heartrate": 170,
                "average_cadence": 87,
                "start_time": 1500,
                "end_time": 3000,
            },
        ],
    }


def _mock_streams(n: int = 3000) -> dict:
    """Build a mock stream response spanning both laps (0..n-1 s at 1 s intervals)."""
    return {
        "time":            {"data": list(range(n))},
        "distance":        {"data": [i * 3.33 for i in range(n)]},
        "heartrate":       {"data": [150 + (i % 20) for i in range(n)]},
        "velocity_smooth": {"data": [3.33] * n},
        "cadence":         {"data": [85] * n},
        "watts":           {"data": [None] * n},
    }


@pytest.mark.asyncio
async def test_analyze_lap_success(mock_intervals):
    """Happy path: split lap 1 of a 2-lap run into 4 segments."""
    activity_id = "i111111"
    mock_intervals.get_activity.return_value = _two_lap_activity(activity_id)
    mock_intervals.get_activity_streams.return_value = _mock_streams()

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 1,
        "num_splits": 4,
    })

    assert len(result) == 1
    text = result[0].text

    assert "Lap 1 Analysis" in text
    assert f"Activity {activity_id}" in text
    assert "4 segments" in text
    for i in range(1, 5):
        assert str(i) in text


@pytest.mark.asyncio
async def test_analyze_lap_second_lap(mock_intervals):
    """Verify lap_number 2 is correctly analysed."""
    activity_id = "i222222"
    mock_intervals.get_activity.return_value = _two_lap_activity(activity_id)
    mock_intervals.get_activity_streams.return_value = _mock_streams()

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 2,
        "num_splits": 2,
    })

    assert len(result) == 1
    text = result[0].text
    assert "Lap 2 Analysis" in text
    assert "2 segments" in text


@pytest.mark.asyncio
async def test_analyze_lap_missing_activity_id(mock_intervals):
    """Missing activity_id returns an error."""
    result = await call_tool("analyze_lap", {"lap_number": 1, "num_splits": 4})
    assert "❌" in result[0].text
    assert "activity_id" in result[0].text.lower()


@pytest.mark.asyncio
async def test_analyze_lap_missing_lap_number(mock_intervals):
    """Missing lap_number returns an error."""
    result = await call_tool("analyze_lap", {"activity_id": "i111111", "num_splits": 4})
    assert "❌" in result[0].text
    assert "lap_number" in result[0].text.lower()


@pytest.mark.asyncio
async def test_analyze_lap_missing_num_splits(mock_intervals):
    """Missing num_splits returns an error."""
    result = await call_tool("analyze_lap", {"activity_id": "i111111", "lap_number": 1})
    assert "❌" in result[0].text
    assert "num_splits" in result[0].text.lower()


@pytest.mark.asyncio
async def test_analyze_lap_invalid_lap_number(mock_intervals):
    """lap_number beyond available laps returns an error."""
    activity_id = "i333333"
    mock_intervals.get_activity.return_value = _two_lap_activity(activity_id)

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 99,
        "num_splits": 4,
    })

    assert "❌" in result[0].text
    assert "99" in result[0].text


@pytest.mark.asyncio
async def test_analyze_lap_num_splits_too_small(mock_intervals):
    """num_splits < 2 returns a validation error."""
    result = await call_tool("analyze_lap", {
        "activity_id": "i111111",
        "lap_number": 1,
        "num_splits": 1,
    })
    assert "❌" in result[0].text
    assert "num_splits" in result[0].text.lower()


@pytest.mark.asyncio
async def test_analyze_lap_fast_running_uses_pace_not_speed(mock_intervals):
    """A fast running lap (>21.6 km/h) must still show min/km pace, not km/h."""
    activity_id = "i555555"

    # 6.5 m/s ≈ 23.4 km/h ≈ 2:34/km — faster than the old 6.0 m/s speed heuristic,
    # which used to misclassify this as cycling.
    mock_intervals.get_activity.return_value = {
        "id": activity_id,
        "type": "Run",
        "icu_intervals": [
            {
                "distance": 1000,
                "moving_time": 154,
                "elapsed_time": 154,
                "average_speed": 6.5,
                "average_heartrate": 175,
                "average_cadence": 95,
                "start_time": 0,
                "end_time": 154,
            },
        ],
    }
    n = 154
    mock_intervals.get_activity_streams.return_value = {
        "time":            {"data": list(range(n))},
        "distance":        {"data": [i * 6.5 for i in range(n)]},
        "heartrate":       {"data": [175] * n},
        "velocity_smooth": {"data": [6.5] * n},
        "cadence":         {"data": [95] * n},
        "watts":           {"data": [None] * n},
    }

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 1,
        "num_splits": 2,
    })

    text = result[0].text
    assert "/km" in text
    assert "km/h" not in text
    assert "spm" in text
    assert "rpm" not in text


@pytest.mark.asyncio
async def test_analyze_lap_no_laps(mock_intervals):
    """Activity with no laps returns a friendly error."""
    activity_id = "i444444"
    mock_intervals.get_activity.return_value = {
        "id": activity_id,
        "type": "Run",
        "icu_intervals": [],
    }

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 1,
        "num_splits": 4,
    })

    assert "❌" in result[0].text
    assert "no lap data" in result[0].text.lower()
