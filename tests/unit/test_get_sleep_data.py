"""Integration tests for get_sleep_data tool.

Tests end-to-end: tool call → IntervalsClient (mocked) → response parsing → formatted output.
"""

import pytest
from unittest.mock import patch, AsyncMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_intervals():
    """Mock the server's IntervalsClient instance."""
    with patch('train_with_gpt.server.intervals') as mock:
        mock.get_wellness = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_get_sleep_data_single_night(mock_intervals):
    """Test getting sleep data for one night with a realistic intervals.icu wellness record."""
    mock_intervals.get_wellness.return_value = [
        {
            "id": "2024-01-15",
            "sleepSecs": 28800,  # 8 hours
            "sleepScore": 85.0,
        }
    ]

    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    output = result[0].text

    # Verify date and duration are shown
    assert "2024-01-15" in output
    assert "8h" in output or "8 h" in output
    # Verify score is shown
    assert "85" in output

    mock_intervals.get_wellness.assert_called_once_with("2024-01-15", "2024-01-15")


@pytest.mark.asyncio
async def test_get_sleep_data_date_range(mock_intervals):
    """Test getting sleep data for multiple nights."""
    mock_intervals.get_wellness.return_value = [
        {"id": "2024-01-15", "sleepSecs": 28800, "sleepScore": 80.0},
        {"id": "2024-01-16", "sleepSecs": 27000, "sleepScore": 78.0},
        {"id": "2024-01-17", "sleepSecs": 29000, "sleepScore": 82.0},
    ]

    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-17"
    })

    assert len(result) == 1
    output = result[0].text

    # Verify all dates mentioned
    assert "2024-01-15" in output
    assert "2024-01-17" in output
    # Verify summary stats
    assert "average" in output.lower() or "summary" in output.lower()


@pytest.mark.asyncio
async def test_get_sleep_data_no_data_found(mock_intervals):
    """Test when no sleep data exists for requested dates."""
    mock_intervals.get_wellness.return_value = []

    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    output = result[0].text.lower()
    assert "no" in output or "found 0" in output or "sleep data" in output


@pytest.mark.asyncio
async def test_get_sleep_data_invalid_date_range(mock_intervals):
    """Test validation: start after end."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower() or "error" in result[0].text.lower()

    # Should not call API
    mock_intervals.get_wellness.assert_not_called()


@pytest.mark.asyncio
async def test_get_sleep_data_range_too_large(mock_intervals):
    """Test rejection of ranges over 30 days."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"  # 45 days
    })

    assert len(result) == 1
    assert "too large" in result[0].text.lower() or "maximum" in result[0].text.lower()

    # Should not call API
    mock_intervals.get_wellness.assert_not_called()


@pytest.mark.asyncio
async def test_get_sleep_data_missing_parameters(mock_intervals):
    """Test error when required parameters missing."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15"
        # Missing end_date
    })

    assert len(result) == 1
    assert "required" in result[0].text.lower() or "error" in result[0].text.lower()
