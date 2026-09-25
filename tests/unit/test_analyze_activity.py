"""Integration tests for analyze_activity tool.

Tests end-to-end: tool call → IntervalsClient (mocked) → data analysis → formatted output.
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


@pytest.mark.asyncio
async def test_analyze_activity_basic(mock_intervals):
    """Test analyzing an activity with a single lap and precomputed HR zone times."""
    activity_id = "i123456"

    mock_intervals.get_activity.return_value = {
        "id": activity_id,
        "name": "Long Run",
        "type": "Run",
        "distance": 21000,
        "moving_time": 7200,
        "average_heartrate": 155,
        "max_heartrate": 180,
        "start_date_local": "2024-01-15T07:00:00Z",
        "icu_hr_zones": [130, 150, 170, 190],
        "icu_hr_zone_times": [1000, 2000, 3000, 1200],
        "icu_power_zones": None,
        "icu_zone_times": None,
        "icu_intervals": [
            {
                "distance": 21000,
                "moving_time": 7200,
                "elapsed_time": 7200,
                "average_heartrate": 155,
                "min_heartrate": 120,
                "max_heartrate": 180,
                "average_speed": 2.9,
                "start_time": 0,
                "end_time": 7200,
            }
        ],
    }

    result = await call_tool("analyze_activity", {"activity_id": activity_id})

    assert len(result) == 1
    output = result[0].text

    # Verify analysis output structure
    assert f"Activity {activity_id}" in output
    assert "Heart Rate" in output
    assert "Zone 1" in output


@pytest.mark.asyncio
async def test_analyze_activity_multiple_laps_uses_pace_not_speed(mock_intervals):
    """A fast running lap (>21.6 km/h) must still show min/km pace, not km/h."""
    activity_id = "i654321"

    # 6.5 m/s ≈ 23.4 km/h ≈ 2:34/km — faster than the old 6.0 m/s speed heuristic,
    # which used to misclassify this as cycling.
    mock_intervals.get_activity.return_value = {
        "id": activity_id,
        "name": "Sprint Reps",
        "type": "Run",
        "distance": 3000,
        "moving_time": 462,
        "start_date_local": "2024-01-15T07:00:00Z",
        "icu_hr_zones": None,
        "icu_hr_zone_times": None,
        "icu_power_zones": None,
        "icu_zone_times": None,
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
            {
                "distance": 1000,
                "moving_time": 154,
                "elapsed_time": 154,
                "average_speed": 6.5,
                "average_heartrate": 178,
                "average_cadence": 95,
                "start_time": 154,
                "end_time": 308,
            },
        ],
    }

    result = await call_tool("analyze_activity", {"activity_id": activity_id})
    text = result[0].text

    assert "/km" in text
    assert "km/h" not in text
    assert "spm" in text
    assert "rpm" not in text


@pytest.mark.asyncio
async def test_analyze_activity_not_found(mock_intervals):
    """Test handling of non-existent activity."""
    mock_intervals.get_activity.side_effect = Exception("Activity not found")

    result = await call_tool("analyze_activity", {"activity_id": "i999999"})

    assert len(result) == 1
    assert "error" in result[0].text.lower() or "not found" in result[0].text.lower()


@pytest.mark.asyncio
async def test_analyze_activity_missing_id(mock_intervals):
    """Test missing activity_id returns an error without calling the API."""
    result = await call_tool("analyze_activity", {})

    assert len(result) == 1
    assert "activity_id" in result[0].text.lower()
    mock_intervals.get_activity.assert_not_called()
