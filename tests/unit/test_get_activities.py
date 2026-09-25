"""Integration tests for get_activities tool.

Tests end-to-end: tool call → IntervalsClient (mocked) → response parsing → formatted output.
"""

import pytest
from unittest.mock import patch, AsyncMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_intervals():
    """Mock the server's IntervalsClient instance."""
    with patch('train_with_gpt.server.intervals') as mock:
        mock.get_activities = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_get_activities_default_last_week(mock_intervals):
    """Test fetching activities from last 7 days with a realistic intervals.icu response."""
    mock_intervals.get_activities.return_value = [
        {
            "id": "i123456789",
            "name": "Morning Run",
            "type": "Run",
            "distance": 10000.5,
            "moving_time": 3600,
            "total_elevation_gain": 150.2,
            "start_date": "2024-01-15T07:30:00Z",
            "average_heartrate": 145,
            "max_heartrate": 178,
        },
        {
            "id": "i987654321",
            "name": "Evening Ride",
            "type": "Ride",
            "distance": 25000,
            "moving_time": 4500,
            "total_elevation_gain": 300,
            "start_date": "2024-01-14T18:00:00Z",
        }
    ]

    result = await call_tool("get_activities", {})

    assert len(result) == 1
    output = result[0].text

    # Verify both activities are in output (check types, not names)
    assert "Run" in output
    assert "Ride" in output
    # Distance is shown (in some format)
    assert "10" in output and "km" in output


@pytest.mark.asyncio
async def test_get_activities_with_date_range(mock_intervals):
    """Test filtering activities by date range."""
    mock_intervals.get_activities.return_value = [
        {
            "id": "i111",
            "name": "Training Run",
            "type": "Run",
            "distance": 5000,
            "moving_time": 1800,
            "start_date": "2024-01-10T10:00:00Z",
        }
    ]

    result = await call_tool("get_activities", {
        "start_date": "2024-01-10",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "Run" in result[0].text
    assert "5.00km" in result[0].text
    mock_intervals.get_activities.assert_called_once_with(
        oldest="2024-01-10", newest="2024-01-15"
    )


@pytest.mark.asyncio
async def test_get_activities_empty_result(mock_intervals):
    """Test when no activities are found."""
    mock_intervals.get_activities.return_value = []

    result = await call_tool("get_activities", {})

    assert len(result) == 1
    assert "no activities" in result[0].text.lower() or "0" in result[0].text


@pytest.mark.asyncio
async def test_get_activities_api_error(mock_intervals):
    """Test handling of intervals.icu API errors."""
    mock_intervals.get_activities.side_effect = Exception("Unauthorized")

    result = await call_tool("get_activities", {})

    assert len(result) == 1
    assert "error" in result[0].text.lower() or "unauthorized" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_activities_invalid_date_format(mock_intervals):
    """Test validation of date format."""
    result = await call_tool("get_activities", {
        "start_date": "2024/01/10",  # Wrong format
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "invalid" in result[0].text.lower() or "error" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_activities_start_after_end(mock_intervals):
    """Test validation when start date is after end date."""
    result = await call_tool("get_activities", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "after" in result[0].text.lower() or "error" in result[0].text.lower()
