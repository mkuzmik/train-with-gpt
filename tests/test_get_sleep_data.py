"""Integration tests for get_sleep_data tool.

Tests end-to-end: tool call → Garmin API (mocked) → response parsing → formatted output.
"""

import pytest
from unittest.mock import patch, MagicMock

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_garmin(monkeypatch):
    """Mock Garmin client at library level."""
    monkeypatch.setenv("GARMIN_EMAIL", "test@example.com")
    monkeypatch.setenv("GARMIN_PASSWORD", "testpass")
    
    with patch('train_with_gpt.garmin_client.Garmin') as mock_class:
        mock_client = MagicMock()
        mock_class.return_value = mock_client
        yield mock_client


@pytest.mark.asyncio
async def test_get_sleep_data_single_night(mock_garmin):
    """Test getting sleep data for one night with realistic Garmin response."""
    mock_garmin.get_sleep_data.return_value = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 28800,  # 8 hours
            "deepSleepSeconds": 7200,
            "lightSleepSeconds": 14400,
            "remSleepSeconds": 5400,
            "awakeSleepSeconds": 1800,
            "sleepStartTimestampGMT": 1705363200000,  # 2024-01-15 22:00
            "sleepEndTimestampGMT": 1705392000000,    # 2024-01-16 06:00
            "avgSpo2Value": 96,
            "avgRespirationValue": 14,
            "restlessMomentCount": 3,
        },
        "sleepScores": {
            "overall": {"value": 85}
        }
    }
    
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
    
    # Verify API called correctly
    mock_garmin.get_sleep_data.assert_called_once_with("2024-01-15")


@pytest.mark.asyncio
async def test_get_sleep_data_date_range(mock_garmin):
    """Test getting sleep data for multiple nights."""
    def mock_response(date_str):
        return {
            "dailySleepDTO": {
                "sleepTimeSeconds": 28800,
                "sleepStartTimestampGMT": 1705363200000,
                "sleepEndTimestampGMT": 1705392000000,
            },
            "sleepScores": {"overall": {"value": 80}}
        }
    
    mock_garmin.get_sleep_data.side_effect = mock_response
    
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
async def test_get_sleep_data_no_data_found(mock_garmin):
    """Test when no sleep data exists for requested dates."""
    # Return None to simulate no data
    mock_garmin.get_sleep_data.return_value = None
    
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    # When None is returned, the tool should handle it gracefully
    # Either show "no data" or skip the date
    output = result[0].text.lower()
    assert "no" in output or "found 0" in output or "sleep data" in output


@pytest.mark.asyncio
async def test_get_sleep_data_invalid_date_range(mock_garmin):
    """Test validation: start after end."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "cannot be after" in result[0].text.lower() or "error" in result[0].text.lower()
    
    # Should not call API
    mock_garmin.get_sleep_data.assert_not_called()


@pytest.mark.asyncio
async def test_get_sleep_data_range_too_large(mock_garmin):
    """Test rejection of ranges over 30 days."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-01",
        "end_date": "2024-02-15"  # 45 days
    })
    
    assert len(result) == 1
    assert "too large" in result[0].text.lower() or "maximum" in result[0].text.lower()
    
    # Should not call API
    mock_garmin.get_sleep_data.assert_not_called()


@pytest.mark.asyncio
async def test_get_sleep_data_missing_parameters(mock_garmin):
    """Test error when required parameters missing."""
    result = await call_tool("get_sleep_data", {
        "start_date": "2024-01-15"
        # Missing end_date
    })
    
    assert len(result) == 1
    assert "required" in result[0].text.lower() or "error" in result[0].text.lower()
