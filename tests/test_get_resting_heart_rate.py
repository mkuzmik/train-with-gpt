"""Integration tests for get_resting_heart_rate tool."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_garmin_auth():
    """Mock Garmin authentication."""
    with patch('train_with_gpt.server.garmin') as mock:
        # Make methods async
        mock.get_heart_rates = AsyncMock()
        yield mock


@pytest.mark.asyncio
async def test_get_resting_heart_rate_single_day(mock_garmin_auth):
    """Test fetching resting heart rate for a single day."""
    mock_hr_data = {
        "restingHeartRate": 52,
    }
    
    mock_garmin_auth.get_heart_rates.return_value = mock_hr_data
    
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    output = result[0].text
    assert "52 bpm" in output


@pytest.mark.asyncio
async def test_get_resting_heart_rate_date_range(mock_garmin_auth):
    """Test fetching resting heart rate for multiple days."""
    async def mock_get_hr(date):
        if date == "2024-01-15":
            return {"restingHeartRate": 52}
        elif date == "2024-01-16":
            return {"restingHeartRate": 54}
        return None
    
    mock_garmin_auth.get_heart_rates.side_effect = mock_get_hr
    
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
async def test_get_resting_heart_rate_no_data_found(mock_garmin_auth):
    """Test when no resting heart rate data is found."""
    mock_garmin_auth.get_heart_rates.return_value = None
    
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "No resting heart rate data found" in result[0].text


@pytest.mark.asyncio
async def test_get_resting_heart_rate_invalid_date_range(mock_garmin_auth):
    """Test validation of date range."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_resting_heart_rate_range_too_large(mock_garmin_auth):
    """Test that date ranges over 30 days are rejected."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"
    })
    
    assert len(result) == 1
    assert "too large" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_resting_heart_rate_missing_parameters(mock_garmin_auth):
    """Test that missing parameters are handled."""
    result = await call_tool("get_resting_heart_rate", {
        "start_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "required" in result[0].text.lower()
