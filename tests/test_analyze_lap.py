"""Tests for analyze_lap tool.

Tests end-to-end: tool call → Strava API calls → lap splitting → formatted output.
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

    from train_with_gpt import server
    server.strava.access_token = "test_token"
    server.strava.client_id = "12345"
    server.strava.client_secret = "secret"

    yield


def _mock_laps(activity_id: str):
    """Register two-lap mock for the given activity."""
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}/laps").mock(
        return_value=Response(200, json=[
            {
                "name": "Lap 1",
                "distance": 5000,
                "elapsed_time": 1500,
                "average_speed": 3.33,
                "average_heartrate": 150,
                "min_heartrate": 140,
                "max_heartrate": 165,
                "average_cadence": 85,
            },
            {
                "name": "Lap 2",
                "distance": 5000,
                "elapsed_time": 1500,
                "average_speed": 3.33,
                "average_heartrate": 155,
                "min_heartrate": 145,
                "max_heartrate": 170,
                "average_cadence": 87,
            },
        ])
    )


def _mock_streams(activity_id: str):
    """Register stream mock spanning both laps (0–2999 s at 1 s intervals)."""
    n = 3000  # 2 laps × 1500 s
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}/streams").mock(
        return_value=Response(200, json={
            "time":             {"data": list(range(n))},
            "distance":         {"data": [i * 3.33 for i in range(n)]},
            "heartrate":        {"data": [150 + (i % 20) for i in range(n)]},
            "velocity_smooth":  {"data": [3.33] * n},
            "cadence":          {"data": [85] * n},
            "watts":            {"data": [None] * n},
        })
    )


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_success(mock_strava_auth):
    """Happy path: split lap 1 of a 2-lap run into 4 segments."""
    activity_id = "111111"
    _mock_laps(activity_id)
    _mock_streams(activity_id)

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 1,
        "num_splits": 4,
    })

    assert len(result) == 1
    text = result[0].text

    assert "Lap 1 Analysis" in text
    assert "Activity 111111" in text
    assert "4 segments" in text
    # Four split rows should appear (labelled 1–4)
    for i in range(1, 5):
        assert str(i) in text


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_second_lap(mock_strava_auth):
    """Verify lap_number 2 is correctly analysed."""
    activity_id = "222222"
    _mock_laps(activity_id)
    _mock_streams(activity_id)

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 2,
        "num_splits": 2,
    })

    assert len(result) == 1
    text = result[0].text
    assert "Lap 2 Analysis" in text
    assert "2 segments" in text


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_missing_activity_id(mock_strava_auth):
    """Missing activity_id returns an error."""
    result = await call_tool("analyze_lap", {"lap_number": 1, "num_splits": 4})
    assert "❌" in result[0].text
    assert "activity_id" in result[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_missing_lap_number(mock_strava_auth):
    """Missing lap_number returns an error."""
    result = await call_tool("analyze_lap", {"activity_id": "111111", "num_splits": 4})
    assert "❌" in result[0].text
    assert "lap_number" in result[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_missing_num_splits(mock_strava_auth):
    """Missing num_splits returns an error."""
    result = await call_tool("analyze_lap", {"activity_id": "111111", "lap_number": 1})
    assert "❌" in result[0].text
    assert "num_splits" in result[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_invalid_lap_number(mock_strava_auth):
    """lap_number beyond available laps returns an error."""
    activity_id = "333333"
    _mock_laps(activity_id)
    _mock_streams(activity_id)

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 99,
        "num_splits": 4,
    })

    assert "❌" in result[0].text
    assert "99" in result[0].text


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_num_splits_too_small(mock_strava_auth):
    """num_splits < 2 returns a validation error."""
    result = await call_tool("analyze_lap", {
        "activity_id": "111111",
        "lap_number": 1,
        "num_splits": 1,
    })
    assert "❌" in result[0].text
    assert "num_splits" in result[0].text.lower()


@pytest.mark.asyncio
@respx.mock
async def test_analyze_lap_no_laps(mock_strava_auth):
    """Activity with no laps returns a friendly error."""
    activity_id = "444444"
    respx.get(f"https://www.strava.com/api/v3/activities/{activity_id}/laps").mock(
        return_value=Response(200, json=[])
    )

    result = await call_tool("analyze_lap", {
        "activity_id": activity_id,
        "lap_number": 1,
        "num_splits": 4,
    })

    assert "❌" in result[0].text
    assert "no lap data" in result[0].text.lower()
