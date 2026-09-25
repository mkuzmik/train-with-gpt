"""Integration tests for get_hrv_data tool."""

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
async def test_get_hrv_data_single_day(mock_intervals):
    """Test fetching HRV data for a single day."""
    mock_intervals.get_wellness.return_value = [
        {"id": "2024-01-15", "hrv": 52.0},
    ]

    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    output = result[0].text
    assert "52ms" in output


@pytest.mark.asyncio
async def test_get_hrv_data_date_range(mock_intervals):
    """Test fetching HRV data for multiple days."""
    mock_intervals.get_wellness.return_value = [
        {"id": "2024-01-15", "hrv": 52.0},
        {"id": "2024-01-16", "hrv": 48.0},
    ]

    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-16"
    })

    assert len(result) == 1
    output = result[0].text
    assert "2024-01-15" in output
    assert "2024-01-16" in output
    assert "52ms" in output
    assert "48ms" in output
    assert "Summary" in output


@pytest.mark.asyncio
async def test_get_hrv_data_no_data_found(mock_intervals):
    """Test when no HRV data is found."""
    mock_intervals.get_wellness.return_value = []

    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "No HRV data found" in result[0].text


@pytest.mark.asyncio
async def test_get_hrv_data_invalid_date_range(mock_intervals):
    """Test validation of date range."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_range_too_large(mock_intervals):
    """Test that date ranges over 30 days are rejected."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"
    })

    assert len(result) == 1
    assert "too large" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_missing_parameters(mock_intervals):
    """Test that missing parameters are handled."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15"
    })

    assert len(result) == 1
    assert "required" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_rolling_averages(mock_intervals):
    """Test that rolling averages are calculated for sufficient data."""
    # Create 30 days of mock data
    records = []
    for day in range(1, 31):
        records.append({"id": f"2024-01-{day:02d}", "hrv": 45 + (day % 10)})

    mock_intervals.get_wellness.return_value = records

    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-01",
        "end_date": "2024-01-30"
    })

    assert len(result) == 1
    output = result[0].text
    # Should have rolling averages
    assert "7-day Rolling Avg" in output
    assert "14-day Rolling Avg" in output
    assert "28-day Rolling Avg" in output
