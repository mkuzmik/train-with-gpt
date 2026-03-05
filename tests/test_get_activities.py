"""Integration tests for get_activities tool.

Tests end-to-end: tool call → HTTP to Strava API → response parsing → formatted output.
"""

import pytest
import respx
from httpx import Response

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_strava_auth(monkeypatch):
    """Set mock Strava credentials and patch the strava client."""
    monkeypatch.setenv("STRAVA_ACCESS_TOKEN", "test_token_12345")
    monkeypatch.setenv("STRAVA_CLIENT_ID", "12345")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    
    # Patch the server's strava instance directly
    from train_with_gpt import server
    from unittest.mock import MagicMock
    
    # Create a mock client with the token set
    original_strava = server.strava
    server.strava.access_token = "test_token_12345"
    server.strava.client_id = "12345"
    server.strava.client_secret = "secret"
    
    yield
    
    # Restore original
    server.strava = original_strava


@pytest.mark.asyncio
@respx.mock
async def test_get_activities_default_last_week(mock_strava_auth):
    """Test fetching activities from last 7 days with real API response structure."""
    mock_activities = [
        {
            "id": 123456789,
            "name": "Morning Run",
            "type": "Run",
            "distance": 10000.5,
            "moving_time": 3600,
            "total_elevation_gain": 150.2,
            "start_date": "2024-01-15T07:30:00Z",  # Changed from start_date_local
            "average_heartrate": 145,
            "max_heartrate": 178,
        },
        {
            "id": 987654321,
            "name": "Evening Ride",
            "type": "Ride",
            "distance": 25000,
            "moving_time": 4500,
            "total_elevation_gain": 300,
            "start_date": "2024-01-14T18:00:00Z",  # Changed from start_date_local
        }
    ]
    
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(200, json=mock_activities)
    )
    
    result = await call_tool("get_activities", {})
    
    assert len(result) == 1
    output = result[0].text
    
    # Verify both activities are in output (check types, not names)
    assert "Run" in output
    assert "Ride" in output
    # Distance is shown (in some format)
    assert "10" in output and "km" in output


@pytest.mark.asyncio
@respx.mock
async def test_get_activities_with_date_range(mock_strava_auth):
    """Test filtering activities by date range."""
    mock_activities = [
        {
            "id": 111,
            "name": "Training Run",
            "type": "Run",
            "distance": 5000,
            "moving_time": 1800,
            "start_date": "2024-01-10T10:00:00Z",
        }
    ]
    
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(200, json=mock_activities)
    )
    
    result = await call_tool("get_activities", {
        "start_date": "2024-01-10",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "Run" in result[0].text
    assert "5.00km" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_get_activities_empty_result(mock_strava_auth):
    """Test when no activities are found."""
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(200, json=[])
    )
    
    result = await call_tool("get_activities", {})
    
    assert len(result) == 1
    assert "no activities" in result[0].text.lower() or "0" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_get_activities_api_error(mock_strava_auth):
    """Test handling of Strava API errors."""
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(401, json={"message": "Unauthorized"})
    )
    
    result = await call_tool("get_activities", {})
    
    assert len(result) == 1
    assert "error" in result[0].text.lower() or "unauthorized" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_activities_invalid_date_format(mock_strava_auth):
    """Test validation of date format."""
    result = await call_tool("get_activities", {
        "start_date": "2024/01/10",  # Wrong format
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "invalid" in result[0].text.lower() or "error" in result[0].text.lower()


@pytest.mark.asyncio
async def test_get_activities_start_after_end(mock_strava_auth):
    """Test validation when start date is after end date."""
    result = await call_tool("get_activities", {
        "start_date": "2024-01-20",
        "end_date": "2024-01-15"
    })
    
    assert len(result) == 1
    assert "after" in result[0].text.lower() or "error" in result[0].text.lower()
