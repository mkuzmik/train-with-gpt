"""Tests for Strava client.

IMPORTANT: Never make real Strava API calls in tests!

Test Coverage:
- Client initialization with/without credentials
- Activity fetching (mocked)
- Zone distribution calculation

When adding new Strava API methods:
1. Add test for successful API call (mock httpx)
2. Add test for API errors (network, auth, 404, etc.)
3. Add test for data parsing/transformation
4. Always mock httpx.AsyncClient to avoid real API calls

For helper functions (like calculate_zone_distribution):
- Test with various input data
- Test edge cases (empty data, single value, etc.)
- No mocking needed for pure functions

See TESTING.md for detailed guidelines.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from train_with_gpt.strava_client import StravaClient


def test_strava_client_initialization():
    """Test StravaClient initializes without access token."""
    with patch('train_with_gpt.strava_client.config') as mock_config:
        mock_config.client_id = None
        mock_config.client_secret = None
        mock_config.access_token = None
        mock_config.refresh_token = None
        
        client = StravaClient()
        
        assert client.access_token is None
        assert client.refresh_token is None


def test_strava_client_with_credentials():
    """Test StravaClient initializes with credentials."""
    with patch('train_with_gpt.strava_client.config') as mock_config:
        mock_config.client_id = "test_id"
        mock_config.client_secret = "test_secret"
        mock_config.access_token = "test_token"
        mock_config.refresh_token = "test_refresh"
        
        client = StravaClient()
        
        assert client.access_token == "test_token"
        assert client.refresh_token == "test_refresh"


@pytest.mark.asyncio
async def test_get_activities_last_week():
    """Test fetching activities from last week."""
    with patch('train_with_gpt.strava_client.config') as mock_config:
        mock_config.access_token = "test_token"
        
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": 123,
                "name": "Morning Run",
                "type": "Run",
                "distance": 5000,
                "moving_time": 1500
            }
        ]
        
        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            client = StravaClient()
            client.access_token = "test_token"
            activities = await client.get_activities_last_week()
            
            assert len(activities) == 1
            assert activities[0]["name"] == "Morning Run"
            assert activities[0]["distance"] == 5000


@pytest.mark.asyncio
async def test_calculate_zone_distribution():
    """Test zone distribution calculation."""
    from train_with_gpt.server import calculate_zone_distribution
    
    # Test data: HR values
    hr_data = [100, 120, 140, 160, 180, 160, 140, 120]
    zone_boundaries = [130, 150, 170]  # Zones: <130, 130-150, 150-170, >170
    
    distribution = calculate_zone_distribution(hr_data, zone_boundaries)
    
    # Zone 1: 100, 120, 120 = 3 values
    # Zone 2: 140, 140 = 2 values
    # Zone 3: 160, 160 = 2 values
    # Zone 4: 180 = 1 value
    
    assert distribution[1] == 3
    assert distribution[2] == 2
    assert distribution[3] == 2
    assert distribution[4] == 1
