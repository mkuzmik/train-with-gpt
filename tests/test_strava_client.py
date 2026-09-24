"""Tests for the per-user Strava client (multi-user OAuth data path)."""

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from train_with_gpt.strava_client import StravaClient


@pytest.fixture
def strava_creds(monkeypatch):
    """Provide the server's own Strava app credentials for token refresh calls."""
    with patch("train_with_gpt.strava_client.config.client_id", "app-client-id"), \
         patch("train_with_gpt.strava_client.config.client_secret", "app-client-secret"):
        yield


@pytest.mark.asyncio
@respx.mock
async def test_get_activities_uses_bearer_token():
    client = StravaClient(access_token="user-access-token")

    route = respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(200, json=[{"id": 1, "name": "Run"}])
    )

    activities = await client.get_activities()

    assert activities == [{"id": 1, "name": "Run"}]
    assert route.calls.last.request.headers["Authorization"] == "Bearer user-access-token"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_on_401_retries_and_persists_new_token(strava_creds):
    refreshed = {}

    async def on_refresh(access_token, refresh_token, expires_at):
        refreshed["access_token"] = access_token
        refreshed["refresh_token"] = refresh_token
        refreshed["expires_at"] = expires_at

    client = StravaClient(
        access_token="stale-token",
        refresh_token="refresh-token",
        expires_at=None,  # not proactively expired, but a 401 should still trigger a refresh
        on_refresh=on_refresh,
    )

    activities_route = respx.get("https://www.strava.com/api/v3/athlete/activities")
    activities_route.side_effect = [
        Response(401, json={"message": "Unauthorized"}),
        Response(200, json=[{"id": 2, "name": "Ride"}]),
    ]

    respx.post("https://www.strava.com/oauth/token").mock(
        return_value=Response(200, json={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_at": 9999999999,
        })
    )

    activities = await client.get_activities()

    assert activities == [{"id": 2, "name": "Ride"}]
    assert client.access_token == "new-access-token"
    assert refreshed == {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_at": 9999999999,
    }


@pytest.mark.asyncio
@respx.mock
async def test_proactive_refresh_when_expiring_soon(strava_creds):
    import time

    client = StravaClient(
        access_token="soon-to-expire",
        refresh_token="refresh-token",
        expires_at=int(time.time()) + 5,  # inside the 60s refresh window
    )

    respx.post("https://www.strava.com/oauth/token").mock(
        return_value=Response(200, json={
            "access_token": "fresh-token",
            "refresh_token": "fresh-refresh",
            "expires_at": 9999999999,
        })
    )
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(
        return_value=Response(200, json=[])
    )

    await client.get_activities()

    assert client.access_token == "fresh-token"


@pytest.mark.asyncio
@respx.mock
async def test_get_activity_laps_returns_empty_on_404():
    client = StravaClient(access_token="token")

    respx.get("https://www.strava.com/api/v3/activities/123/laps").mock(
        return_value=Response(404, json={"message": "Not Found"})
    )

    laps = await client.get_activity_laps(123)
    assert laps == []


@pytest.mark.asyncio
@respx.mock
async def test_get_athlete():
    client = StravaClient(access_token="token")

    respx.get("https://www.strava.com/api/v3/athlete").mock(
        return_value=Response(200, json={"id": 999, "firstname": "Jane", "lastname": "Doe"})
    )

    athlete = await client.get_athlete()
    assert athlete["id"] == 999


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_refreshes_for_same_user_refresh_once(strava_creds):
    """Strava rotates refresh tokens: a second concurrent refresh would use a dead one."""
    import asyncio
    import time

    stored = {"tokens": ("stale", "refresh-1", int(time.time()) - 10)}

    async def on_refresh(access_token, refresh_token, expires_at):
        stored["tokens"] = (access_token, refresh_token, expires_at)

    lock = asyncio.Lock()

    def make_client():
        access, refresh, expires = stored["tokens"]
        return StravaClient(
            access_token=access, refresh_token=refresh, expires_at=expires,
            on_refresh=on_refresh, refresh_lock=lock,
            load_stored_tokens=lambda: stored["tokens"],
        )

    token_route = respx.post("https://www.strava.com/oauth/token").mock(
        return_value=Response(200, json={
            "access_token": "fresh", "refresh_token": "refresh-2", "expires_at": 9999999999,
        })
    )
    respx.get("https://www.strava.com/api/v3/athlete/activities").mock(return_value=Response(200, json=[]))

    a, b = make_client(), make_client()
    await asyncio.gather(a.get_activities(), b.get_activities())

    assert token_route.call_count == 1
    assert a.access_token == b.access_token == "fresh"
    assert b.refresh_token == "refresh-2"


@pytest.mark.asyncio
@respx.mock
async def test_get_all_activities_follows_pages():
    client = StravaClient(access_token="t")
    route = respx.get("https://www.strava.com/api/v3/athlete/activities")
    route.side_effect = [
        Response(200, json=[{"id": i} for i in range(200)]),
        Response(200, json=[{"id": i} for i in range(200, 250)]),
    ]

    activities = await client.get_all_activities(after=1, before=2)

    assert len(activities) == 250
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]
