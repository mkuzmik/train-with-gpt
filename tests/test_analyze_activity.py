"""Integration tests for analyze_activity tool.

Tests end-to-end: tool call → Strava API calls → data analysis → formatted output.
"""

import pytest
import respx
from httpx import Response

from train_with_gpt.server import call_tool


@pytest.fixture
def mock_strava_auth(monkeypatch):
    """Set mock Strava credentials and patch the strava client."""
    monkeypatch.setenv("STRAVA_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("STRAVA_CLIENT_ID", "12345")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "secret")
    
    # Patch the server's strava instance directly
    from train_with_gpt import server
    server.strava.access_token = "test_token"
    server.strava.client_id = "12345"
    server.strava.client_secret = "secret"
    
    yield


@pytest.mark.asyncio
@respx.mock
async def test_analyze_activity_basic(mock_strava_auth):
    """Test analyzing an activity with all API calls mocked."""
    activity_id = "123456"
    
    # Mock activity details
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}").mock(
        return_value=Response(200, json={
            "id": 123456,
            "name": "Long Run",
            "type": "Run",
            "distance": 21000,
            "moving_time": 7200,
            "total_elevation_gain": 200,
            "average_heartrate": 155,
            "max_heartrate": 180,
            "start_date_local": "2024-01-15T07:00:00Z",
        })
    )
    
    # Mock zones
    respx.get("https://www.strava.com/api/v3/athlete/zones").mock(
        return_value=Response(200, json={
            "heart_rate": {
                "zones": [
                    {"min": 0, "max": 130},
                    {"min": 130, "max": 150},
                    {"min": 150, "max": 170},
                    {"min": 170, "max": 190},
                ]
            }
        })
    )
    
    # Mock streams - need to return dict with 'time' key
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}/streams").mock(
        return_value=Response(200, json={
            "time": {"data": [0, 60, 120, 180, 240, 300, 360, 420, 480, 540]},
            "heartrate": {"data": [140, 145, 150, 155, 160, 165, 170, 155, 150, 145]}
        })
    )
    
    # Mock laps
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}/laps").mock(
        return_value=Response(200, json=[
            {
                "name": "Lap 1",
                "distance": 5000,
                "elapsed_time": 1800,
                "average_heartrate": 150,
                "min_heartrate": 140,
                "max_heartrate": 165
            }
        ])
    )
    
    result = await call_tool("analyze_activity", {"activity_id": activity_id})
    
    assert len(result) == 1
    output = result[0].text
    
    # Verify analysis output structure
    assert "Activity 123456" in output  # Activity ID is shown
    assert "Zone" in output or "Heart Rate" in output  # HR analysis present


@pytest.mark.asyncio
@respx.mock
async def test_analyze_activity_not_found(mock_strava_auth):
    """Test handling of non-existent activity."""
    respx.get("https://www.strava.com/api/v3/activities/999999").mock(
        return_value=Response(404, json={"message": "Not Found"})
    )
    
    result = await call_tool("analyze_activity", {"activity_id": "999999"})
    
    assert len(result) == 1
    assert "error" in result[0].text.lower() or "not found" in result[0].text.lower()
