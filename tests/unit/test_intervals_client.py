"""Unit tests for IntervalsClient; intervals.icu's HTTP API is stubbed with respx."""

import base64

import pytest
from httpx import Response

from tests.support import INTERVALS_API_KEY
from train_with_gpt.config import config
from train_with_gpt.intervals_client import IntervalsClient

API = "https://intervals.icu/api/v1"
EXPECTED_AUTH = "Basic " + base64.b64encode(f"API_KEY:{INTERVALS_API_KEY}".encode()).decode()


async def test_get_activities_sends_basic_auth_and_range(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/athlete/0/activities").mock(return_value=Response(200, json=[{"id": "i1"}]))

    activities = await IntervalsClient().get_activities("2024-01-01", "2024-01-07")

    assert activities == [{"id": "i1"}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == EXPECTED_AUTH
    assert dict(request.url.params) == {"oldest": "2024-01-01", "newest": "2024-01-07"}


async def test_missing_api_key_fails_before_any_request(http_mock):
    route = http_mock.get(f"{API}/athlete/0/activities")

    with pytest.raises(ValueError, match="INTERVALS_API_KEY not configured"):
        await IntervalsClient().get_activities("2024-01-01", "2024-01-07")

    assert not route.called


async def test_api_key_is_read_from_config_at_call_time(http_mock, monkeypatch):
    client = IntervalsClient()  # constructed before the key is configured
    monkeypatch.setattr(config, "intervals_api_key", "later-key")
    route = http_mock.get(f"{API}/athlete/0/wellness").mock(return_value=Response(200, json=[]))

    await client.get_wellness("2024-01-01", "2024-01-02")

    expected = "Basic " + base64.b64encode(b"API_KEY:later-key").decode()
    assert route.calls.last.request.headers["Authorization"] == expected


async def test_explicit_api_key_wins_over_config(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/athlete/0").mock(return_value=Response(200, json={"id": "i7", "name": "Jane"}))

    athlete = await IntervalsClient(api_key="users-own-key").get_athlete()

    assert athlete == {"id": "i7", "name": "Jane"}
    expected = "Basic " + base64.b64encode(b"API_KEY:users-own-key").decode()
    assert route.calls.last.request.headers["Authorization"] == expected


async def test_http_errors_are_raised(http_mock, intervals_api_key):
    http_mock.get(f"{API}/athlete/0/activities").mock(return_value=Response(401))

    with pytest.raises(Exception, match="401"):
        await IntervalsClient().get_activities("2024-01-01", "2024-01-07")


async def test_get_activity_includes_intervals_flag(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/activity/i42").mock(return_value=Response(200, json={"id": "i42"}))

    assert await IntervalsClient().get_activity("i42") == {"id": "i42"}
    assert route.calls.last.request.url.params["intervals"] == "true"

    await IntervalsClient().get_activity("i42", intervals=False)
    assert route.calls.last.request.url.params["intervals"] == "false"


async def test_get_activity_not_found(http_mock, intervals_api_key):
    http_mock.get(f"{API}/activity/i404").mock(return_value=Response(404))

    with pytest.raises(Exception, match="Activity not found"):
        await IntervalsClient().get_activity("i404")


async def test_get_activity_streams_reshapes_to_dict_by_type(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/activity/i1/streams").mock(return_value=Response(200, json=[
        {"type": "time", "data": [0, 1, 2]},
        {"type": "heartrate", "data": [120, 121, 122]},
        {"type": "watts"},
    ]))

    streams = await IntervalsClient().get_activity_streams("i1", ["time", "heartrate", "watts"])

    assert streams == {
        "time": {"data": [0, 1, 2]},
        "heartrate": {"data": [120, 121, 122]},
        "watts": {"data": []},
    }
    assert route.calls.last.request.url.params["types"] == "time,heartrate,watts"


async def test_get_activity_streams_default_types(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/activity/i1/streams").mock(return_value=Response(200, json=[]))

    await IntervalsClient().get_activity_streams("i1")

    assert route.calls.last.request.url.params["types"] == "time,heartrate,distance,cadence,watts,velocity_smooth"


async def test_get_activity_streams_not_found(http_mock, intervals_api_key):
    http_mock.get(f"{API}/activity/i1/streams").mock(return_value=Response(404))

    with pytest.raises(Exception, match="no stream data"):
        await IntervalsClient().get_activity_streams("i1")


async def test_get_wellness(http_mock, intervals_api_key):
    route = http_mock.get(f"{API}/athlete/0/wellness").mock(
        return_value=Response(200, json=[{"id": "2024-01-15", "hrv": 50}])
    )

    assert await IntervalsClient().get_wellness("2024-01-15", "2024-01-16") == [{"id": "2024-01-15", "hrv": 50}]
    assert dict(route.calls.last.request.url.params) == {"oldest": "2024-01-15", "newest": "2024-01-16"}
