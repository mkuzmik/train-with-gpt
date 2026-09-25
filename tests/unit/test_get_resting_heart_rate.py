"""Integration tests for get_resting_heart_rate tool."""

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
async def test_get_resting_heart_rate_single_day(mock_intervals):
    """Test fetching resting heart rate for a single day."""
    mock_intervals.get_wellness.return_value = [
        {"id": "2024-01-15", "restingHR": 52},
    ]

    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    output = result[0].text
    assert "52 bpm" in output


@pytest.mark.asyncio
async def test_get_resting_heart_rate_date_range(mock_intervals):
    """Test fetching resting heart rate for multiple days."""
    mock_intervals.get_wellness.return_value = [
        {"id": "2024-01-15", "restingHR": 52},
        {"id": "2024-01-16", "restingHR": 54},
    ]

    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-16"
    })

    assert len(result) == 1
    output = result[0].text
    assert "2024-01-15" in output
    assert "2024-01-16" in output
    assert "52 bpm" in output
    assert "54 bpm" in output
    assert "Summary" in output


@pytest.mark.asyncio
async def test_get_resting_heart_rate_no_data_found(mock_intervals):
    """Test when no resting heart rate data is found."""
    mock_intervals.get_wellness.return_value = []

    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "No resting heart rate data found" in result[0].text


@pytest.mark.asyncio
async def test_get_resting_heart_rate_invalid_date_range(mock_intervals):
    """Test validation of date range."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_resting_heart_rate_range_too_large(mock_intervals):
    """Test that date ranges over 30 days are rejected."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"
    })

    assert len(result) == 1
    assert "too large" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_resting_heart_rate_missing_parameters(mock_intervals):
    """Test that missing parameters are handled."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "required" in result[0].text.lower()
