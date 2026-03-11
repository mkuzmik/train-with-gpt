"""Integration tests for get_hrv_data tool."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_garmin_auth():
    """Mock Garmin authentication."""
    with patch('train_with_gpt.server.garmin') as mock:
        # Make methods async
        mock.get_hrv_data = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_get_hrv_data_single_day(mock_garmin_auth):
    """Test fetching HRV data for a single day."""
    mock_hrv_data = {
        "hrvSummary": {
            "lastNightAvg": 52,
            "weeklyAvg": 50,
            "status": "BALANCED",
        }
    }
    
    mock_garmin_auth.get_hrv_data.return_value = mock_hrv_data
    
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    output = result[0].text
    assert "52ms" in output
    assert "BALANCED" in output


@pytest.mark.asyncio
async def test_get_hrv_data_date_range(mock_garmin_auth):
    """Test fetching HRV data for multiple days."""
    async def mock_get_hrv(date):
        if date == "2024-01-15":
            return {"hrvSummary": {"lastNightAvg": 52, "weeklyAvg": 50, "status": "BALANCED"}}
        elif date == "2024-01-16":
            return {"hrvSummary": {"lastNightAvg": 48, "weeklyAvg": 50, "status": "UNBALANCED"}}
        return None
    
    mock_garmin_auth.get_hrv_data.side_effect = mock_get_hrv
    
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
async def test_get_hrv_data_no_data_found(mock_garmin_auth):
    """Test when no HRV data is found."""
    mock_garmin_auth.get_hrv_data.return_value = None
    
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "No HRV data found" in result[0].text


@pytest.mark.asyncio
async def test_get_hrv_data_invalid_date_range(mock_garmin_auth):
    """Test validation of date range."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_range_too_large(mock_garmin_auth):
    """Test that date ranges over 30 days are rejected."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"
    })
    
    assert len(result) == 1
    assert "too large" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_missing_parameters(mock_garmin_auth):
    """Test that missing parameters are handled."""
    result = await call_tool("get_hrv_data", {
        "start_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "required" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_hrv_data_rolling_averages(mock_garmin_auth):
    """Test that rolling averages are calculated for sufficient data."""
    # Create 30 days of mock data
    async def mock_get_hrv(date):
        # Return data with HRV varying from 45-55
        day = int(date.split("-")[-1])
        return {"hrvSummary": {"lastNightAvg": 45 + (day % 10), "weeklyAvg": 50, "status": "BALANCED"}}
    
    mock_garmin_auth.get_hrv_data.side_effect = mock_get_hrv
    
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
