"""capture_intervals_shapes.py: the reference keeps structure and drops all data."""

import json
import re
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "capture_intervals_shapes.py"
REFERENCE = ROOT / "docs" / "intervals-api-shapes.md"

sys.path.insert(0, str(SCRIPT.parent))
try:
    import capture_intervals_shapes as cap
finally:
    sys.path.remove(str(SCRIPT.parent))

SPEC = {"components": {"schemas": {
    "Activity": {"properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "source": {"type": "string"},
        "start_date_local": {"type": "string"},
        "moving_time": {"type": "integer"},
        "stream_types": {"type": "array", "items": {"type": "string"}},
    }},
    "ActivityWithIntervals": {"properties": {
        "id": {"type": "string"},
        "icu_zone_times": {"type": "array", "items": {"$ref": "#/components/schemas/ZoneTime"}},
    }},
    "ZoneTime": {"properties": {"id": {"type": "string"}, "secs": {"type": "integer"}}},
    "ActivityStream": {"properties": {
        "type": {"type": "string"},
        "name": {"type": "string"},
        "data": {"type": "object"},
        "data2": {"type": "object"},
        "custom": {"type": "boolean"},
    }},
    "Wellness": {"properties": {
        "id": {"type": "string"},
        "weight": {"type": "number"},
        "comments": {"type": "string"},
    }},
}}}

ACTIVITY_ID = "i99887766"
SENTINELS = [
    ACTIVITY_ID, "SENTINEL_ACTIVITY_NAME", "2001-02-03", "SENTINEL_NOTE", "SENTINEL_CUSTOM_FIELD",
    "SENTINEL_CUSTOM_VALUE", "SENTINEL_CUSTOM_STREAM", "SENTINEL_UNKNOWN_STREAM",
    "SENTINEL_STREAM_NAME", "SENTINEL_MAP_KEY", "SENTINEL_VALUE_TYPE", "SENTINEL_COMMENT",
    "987654", "54.321", "4321", "111222",
]


def stub_api(http_mock):
    """Synthetic responses with a recognisable sentinel in every sensitive position."""
    activity = {
        "id": ACTIVITY_ID,
        "name": "SENTINEL_ACTIVITY_NAME",
        "source": "GARMIN",
        "start_date_local": "2001-02-03T04:05:06",
        "moving_time": 987654,
        "SENTINEL_CUSTOM_FIELD": "SENTINEL_CUSTOM_VALUE",
    }
    detail = {
        **activity,
        "stream_types": ["heartrate", "SENTINEL_CUSTOM_STREAM"],
        "icu_zone_times": [{"id": "SENTINEL_NOTE", "secs": 4321}],
        "tiz_map": {"SENTINEL_MAP_KEY": 111222},
    }
    streams = [
        {"type": "heartrate", "name": "SENTINEL_STREAM_NAME", "data": [987654, None],
         "custom": False, "valueType": "SENTINEL_VALUE_TYPE", "allNull": False},
        {"type": "SENTINEL_CUSTOM_STREAM", "name": "SENTINEL_STREAM_NAME", "data": [54.321],
         "custom": True},
        {"type": "SENTINEL_UNKNOWN_STREAM", "data": ["SENTINEL_NOTE"]},
        {"type": "watts", "name": "SENTINEL_STREAM_NAME", "data": [54.321], "custom": True},
    ]
    wellness = [{"id": "2001-02-03", "weight": 54.321, "comments": "SENTINEL_COMMENT",
                 "SENTINEL_CUSTOM_FIELD": 4321, "restingHR": None}]

    http_mock.get(cap.SPEC_URL).mock(return_value=httpx.Response(200, json=SPEC))
    http_mock.get(f"{cap.BASE_URL}/athlete/0/activities").mock(
        return_value=httpx.Response(200, json=[activity]))
    http_mock.get(f"{cap.BASE_URL}/activity/{ACTIVITY_ID}").mock(
        return_value=httpx.Response(200, json=detail))
    streams_route = http_mock.get(f"{cap.BASE_URL}/activity/{ACTIVITY_ID}/streams").mock(
        return_value=httpx.Response(200, json=streams))
    http_mock.get(f"{cap.BASE_URL}/athlete/0/wellness").mock(
        return_value=httpx.Response(200, json=wellness))
    return streams_route


def run(tmp_path, monkeypatch, *args):
    monkeypatch.setenv("INTERVALS_API_KEY", "SENTINEL_API_KEY")
    output = tmp_path / "shapes.md"
    return cap.main(["--output", str(output), *args]), output


def blocks(text):
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", text, re.S)]


def leaves(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from leaves(value)
    elif isinstance(node, list):
        for value in node:
            yield from leaves(value)
    else:
        yield node


def test_no_sentinel_reaches_the_output(tmp_path, monkeypatch, http_mock, capsys):
    stub_api(http_mock)
    code, output = run(tmp_path, monkeypatch)
    captured = capsys.readouterr()
    everything = output.read_text() + captured.out + captured.err
    assert code == 0
    assert "SENTINEL_API_KEY" not in everything
    for sentinel in SENTINELS:
        assert sentinel not in everything


def test_output_keeps_the_structure(tmp_path, monkeypatch, http_mock):
    stub_api(http_mock)
    _, output = run(tmp_path, monkeypatch)
    text = output.read_text()
    activities, detail, streams, wellness = blocks(text)

    assert "live API responses" in text
    assert activities[0]["moving_time"] == 1
    assert activities[0]["start_date_local"] == "2000-01-01T00:00:00"
    assert activities[0]["name"] == "text"
    assert activities[0]["<unlisted field>"] == "text"
    # The shape that caused real bugs: zone times are objects, not plain seconds.
    assert detail["icu_zone_times"] == [{"id": "text", "secs": 1}]
    assert wellness[0]["id"] == "2000-01-01"
    assert wellness[0]["weight"] == 1.5
    assert wellness[0]["<unlisted field>"] == "<integer|null>"  # custom field + restingHR

    assert set(streams) == {"heartrate", "<unlisted stream>"}
    assert streams["heartrate"]["data"] == ["<integer|null>"]
    assert streams["heartrate"]["valueType"] == "text"
    assert streams["heartrate"]["custom"] is True
    assert "<unlisted field>" in streams["heartrate"]  # allNull isn't in this test's spec


def test_requests_every_stream_type_the_activity_has(tmp_path, monkeypatch, http_mock):
    streams_route = stub_api(http_mock)
    run(tmp_path, monkeypatch)
    assert streams_route.calls[0].request.url.params["types"] == "heartrate,SENTINEL_CUSTOM_STREAM"


def test_strava_stubs_are_not_fetched(tmp_path, monkeypatch, http_mock, capsys):
    stub_api(http_mock)
    http_mock.get(f"{cap.BASE_URL}/athlete/0/activities").mock(return_value=httpx.Response(
        200, json=[{"id": "1", "source": "STRAVA", "_note": "SENTINEL_NOTE"}]))
    code, output = run(tmp_path, monkeypatch)
    assert code == 1
    assert not output.exists()
    assert "no data to describe" in capsys.readouterr().err


def test_a_failing_activity_is_skipped_without_printing_its_id(tmp_path, monkeypatch, http_mock, capsys):
    stub_api(http_mock)
    good = {"id": "i5", "source": "GARMIN"}
    http_mock.get(f"{cap.BASE_URL}/athlete/0/activities").mock(return_value=httpx.Response(
        200, json=[{"id": ACTIVITY_ID, "source": "GARMIN"}, good]))
    http_mock.get(f"{cap.BASE_URL}/activity/{ACTIVITY_ID}").mock(
        return_value=httpx.Response(422, json={"error": "SENTINEL_NOTE"}))
    http_mock.get(f"{cap.BASE_URL}/activity/i5").mock(return_value=httpx.Response(200, json=good))
    http_mock.get(f"{cap.BASE_URL}/activity/i5/streams").mock(return_value=httpx.Response(
        200, json=[{"type": "time", "data": [1]}]))
    code, _ = run(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert code == 0
    assert "HTTP 422" in err
    assert ACTIVITY_ID not in err
    assert "SENTINEL_NOTE" not in err


@pytest.mark.parametrize("failure", [httpx.Response(401), httpx.ConnectError("SENTINEL_NOTE")])
def test_failure_prints_no_details_and_keeps_the_existing_file(tmp_path, monkeypatch, http_mock, capsys, failure):
    stub_api(http_mock)
    route = http_mock.get(f"{cap.BASE_URL}/athlete/0/activities")
    route.mock(side_effect=failure) if isinstance(failure, Exception) else route.mock(return_value=failure)
    output = tmp_path / "shapes.md"
    output.write_text("previous")
    monkeypatch.setenv("INTERVALS_API_KEY", "SENTINEL_API_KEY")
    assert cap.main(["--output", str(output)]) == 1
    captured = capsys.readouterr()
    assert output.read_text() == "previous"
    assert "SENTINEL" not in captured.out + captured.err


def test_missing_key_fails_without_calling_the_api(tmp_path, http_mock, capsys):
    http_mock.get(cap.SPEC_URL).mock(return_value=httpx.Response(200, json=SPEC))
    assert cap.main(["--output", str(tmp_path / "shapes.md")]) == 1
    assert "INTERVALS_API_KEY" in capsys.readouterr().err


def test_from_spec_needs_no_key_and_says_it_is_synthetic(tmp_path, http_mock):
    http_mock.get(cap.SPEC_URL).mock(return_value=httpx.Response(200, json=SPEC))
    output = tmp_path / "shapes.md"
    assert cap.main(["--from-spec", "--output", str(output)]) == 0
    text = output.read_text()
    assert "**Source: synthetic." in text
    streams = blocks(text)[2]
    assert streams["time"]["data"] == [1.5]
    assert streams["latlng"]["data2"] == [1.5]


def test_committed_reference_holds_structure_only():
    """Also guards future refreshes: a leaked value or id fails here."""
    text = REFERENCE.read_text()
    sections = blocks(text)
    assert len(sections) == 4
    assert set(sections[2]) <= cap.STREAM_TYPES | {cap.UNLISTED_STREAM}
    allowed = list(cap.PLACEHOLDERS.values())
    for leaf in leaves(sections):
        is_label = isinstance(leaf, str) and re.fullmatch(r"<[a-z |:-]+>", leaf)
        # type() too, since 1 == True and 1 == 1.0 in Python.
        assert is_label or any(type(leaf) is type(a) and leaf == a for a in allowed), leaf
    assert set(re.findall(r"\d{4}-\d{2}-\d{2}", text)) <= {"2000-01-01"}
    assert not re.search(r"\bi\d{4,}\b", text)


def test_strava_rows_are_left_out_of_the_list_shape(tmp_path, monkeypatch, http_mock):
    stub_api(http_mock)
    http_mock.get(f"{cap.BASE_URL}/athlete/0/activities").mock(return_value=httpx.Response(200, json=[
        {"id": ACTIVITY_ID, "source": "GARMIN", "moving_time": 1},
        {"id": "1", "source": "STRAVA", "name": "SENTINEL_ACTIVITY_NAME", "_note": "SENTINEL_NOTE"},
    ]))
    code, output = run(tmp_path, monkeypatch)
    assert code == 0
    assert set(blocks(output.read_text())[0][0]) == {"id", "source", "moving_time"}


def test_object_and_array_at_one_position_keep_both_structures():
    shape = cap.Shape()
    known = {"a", "b"}
    shape.observe({"a": 1}, known)
    shape.observe([{"b": 1.5}], known)
    assert shape.render() == {"a": 1, "<also array>": [{"b": 1.5}]}
