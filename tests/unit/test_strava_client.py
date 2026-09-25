"""Unit tests for the per-user Strava client (multi-user OAuth data path).

Strava's HTTP API is stubbed with respx (`http_mock`); nothing else is faked.
"""

import asyncio
import time
from urllib.parse import parse_qs

import pytest
from httpx import Response

from tests.support import STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
from train_with_gpt.strava_client import StravaClient

API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"


def _token_response(access="new-access-token", refresh="new-refresh-token", expires_at=9999999999):
    return Response(200, json={"access_token": access, "refresh_token": refresh, "expires_at": expires_at})


async def test_get_activities_uses_bearer_token_and_params(http_mock):
    route = http_mock.get(f"{API}/athlete/activities").mock(
        return_value=Response(200, json=[{"id": 1, "name": "Run"}])
    )

    activities = await StravaClient(access_token="user-access-token").get_activities(
        after=100, before=200, per_page=500,
    )

    assert activities == [{"id": 1, "name": "Run"}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer user-access-token"
    assert dict(request.url.params) == {"page": "1", "per_page": "200", "after": "100", "before": "200"}


async def test_refresh_on_401_retries_and_persists_new_token(http_mock, strava_app_credentials):
    refreshed = {}

    async def on_refresh(access_token, refresh_token, expires_at):
        refreshed.update(access_token=access_token, refresh_token=refresh_token, expires_at=expires_at)

    client = StravaClient(
        access_token="stale-token",
        refresh_token="refresh-token",
        expires_at=None,  # not proactively expired, but a 401 should still trigger a refresh
        on_refresh=on_refresh,
    )

    activities_route = http_mock.get(f"{API}/athlete/activities")
    activities_route.side_effect = [
        Response(401, json={"message": "Unauthorized"}),
        Response(200, json=[{"id": 2, "name": "Ride"}]),
    ]
    token_route = http_mock.post(TOKEN_URL).mock(return_value=_token_response())

    activities = await client.get_activities()

    assert activities == [{"id": 2, "name": "Ride"}]
    assert client.access_token == "new-access-token"
    assert refreshed == {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_at": 9999999999,
    }
    # The refresh used our app credentials and the user's refresh token...
    form = parse_qs(token_route.calls.last.request.content.decode())
    assert form == {
        "client_id": [STRAVA_CLIENT_ID],
        "client_secret": [STRAVA_CLIENT_SECRET],
        "refresh_token": ["refresh-token"],
        "grant_type": ["refresh_token"],
    }
    # ...and the retry carried the new access token.
    assert activities_route.calls.last.request.headers["Authorization"] == "Bearer new-access-token"


async def test_401_without_refresh_token_is_returned_as_is(http_mock):
    http_mock.get(f"{API}/athlete").mock(return_value=Response(401))

    with pytest.raises(Exception, match="401"):
        await StravaClient(access_token="t").get_athlete()


async def test_refresh_without_app_credentials_fails(http_mock):
    http_mock.get(f"{API}/athlete/activities").mock(return_value=Response(401))
    client = StravaClient(access_token="t", refresh_token="r")

    with pytest.raises(ValueError, match="Missing credentials"):
        await client.get_activities()


async def test_proactive_refresh_when_expiring_soon(http_mock, strava_app_credentials):
    client = StravaClient(
        access_token="soon-to-expire",
        refresh_token="refresh-token",
        expires_at=int(time.time()) + 5,  # inside the 60s refresh window
    )
    http_mock.post(TOKEN_URL).mock(return_value=_token_response(access="fresh-token"))
    route = http_mock.get(f"{API}/athlete/activities").mock(return_value=Response(200, json=[]))

    await client.get_activities()

    assert client.access_token == "fresh-token"
    assert route.calls.last.request.headers["Authorization"] == "Bearer fresh-token"


async def test_no_refresh_when_token_is_fresh(http_mock, strava_app_credentials):
    token_route = http_mock.post(TOKEN_URL)
    http_mock.get(f"{API}/athlete/activities").mock(return_value=Response(200, json=[]))
    client = StravaClient(access_token="t", refresh_token="r", expires_at=int(time.time()) + 3600)

    await client.get_activities()

    assert not token_route.called


async def test_concurrent_refreshes_for_same_user_refresh_once(http_mock, strava_app_credentials):
    """Strava rotates refresh tokens: a second concurrent refresh would use a dead one."""
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

    token_route = http_mock.post(TOKEN_URL).mock(
        return_value=_token_response(access="fresh", refresh="refresh-2")
    )
    http_mock.get(f"{API}/athlete/activities").mock(return_value=Response(200, json=[]))

    a, b = make_client(), make_client()
    await asyncio.gather(a.get_activities(), b.get_activities())

    assert token_route.call_count == 1
    assert a.access_token == b.access_token == "fresh"
    assert b.refresh_token == "refresh-2"


async def test_get_all_activities_follows_pages(http_mock):
    route = http_mock.get(f"{API}/athlete/activities")
    route.side_effect = [
        Response(200, json=[{"id": i} for i in range(200)]),
        Response(200, json=[{"id": i} for i in range(200, 250)]),
    ]

    activities = await StravaClient(access_token="t").get_all_activities(after=1, before=2)

    assert len(activities) == 250
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


async def test_get_athlete(http_mock):
    http_mock.get(f"{API}/athlete").mock(
        return_value=Response(200, json={"id": 999, "firstname": "Jane", "lastname": "Doe"})
    )

    athlete = await StravaClient(access_token="token").get_athlete()

    assert athlete["id"] == 999


async def test_get_activity_details(http_mock):
    http_mock.get(f"{API}/activities/77").mock(return_value=Response(200, json={"id": 77, "sport_type": "Run"}))

    assert (await StravaClient(access_token="t").get_activity_details(77))["sport_type"] == "Run"


async def test_get_activity_laps_returns_empty_on_404(http_mock):
    http_mock.get(f"{API}/activities/123/laps").mock(return_value=Response(404, json={"message": "Not Found"}))

    assert await StravaClient(access_token="token").get_activity_laps(123) == []


async def test_get_activity_laps_raises_on_other_errors(http_mock):
    http_mock.get(f"{API}/activities/123/laps").mock(return_value=Response(500))

    with pytest.raises(Exception, match="Failed to fetch laps: 500"):
        await StravaClient(access_token="token").get_activity_laps(123)


async def test_get_activity_streams_requests_keys_by_type(http_mock):
    route = http_mock.get(f"{API}/activities/5/streams").mock(
        return_value=Response(200, json={"time": {"data": [0, 1]}})
    )

    streams = await StravaClient(access_token="t").get_activity_streams(5, stream_types=["time", "heartrate"])

    assert streams == {"time": {"data": [0, 1]}}
    assert dict(route.calls.last.request.url.params) == {"keys": "time,heartrate", "key_by_type": "true"}


async def test_get_activity_streams_not_found(http_mock):
    http_mock.get(f"{API}/activities/5/streams").mock(return_value=Response(404))

    with pytest.raises(Exception, match="not found"):
        await StravaClient(access_token="t").get_activity_streams(5)


async def test_athlete_zones_are_cached_until_forced(http_mock):
    route = http_mock.get(f"{API}/athlete/zones").mock(
        return_value=Response(200, json={"heart_rate": {"zones": []}})
    )
    client = StravaClient(access_token="t")

    await client.get_athlete_zones()
    await client.get_athlete_zones()
    assert route.call_count == 1

    await client.get_athlete_zones(force_refresh=True)
    assert route.call_count == 2


async def test_athlete_zones_error(http_mock):
    http_mock.get(f"{API}/athlete/zones").mock(return_value=Response(403))

    with pytest.raises(Exception, match="Failed to fetch zones: 403"):
        await StravaClient(access_token="t").get_athlete_zones()
