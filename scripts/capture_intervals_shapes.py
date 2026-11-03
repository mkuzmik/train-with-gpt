#!/usr/bin/env python3
"""Write the committed reference of what the intervals.icu API returns.

The reference (docs/intervals-api-shapes.md) keeps the structure of each
response and drops all data: every value becomes a fixed placeholder of the
same type (PLACEHOLDERS), and a field name appears only if the public OpenAPI spec (or EXTRA_FIELDS) lists it,
so user-defined custom field and stream names can't get out.

    INTERVALS_API_KEY=... uv run python scripts/capture_intervals_shapes.py
    uv run python scripts/capture_intervals_shapes.py --from-spec   # no key needed

Nothing but the output file is written. Failures report only the endpoint
template and status: URLs and response bodies can contain ids and data.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

BASE_URL = "https://intervals.icu/api/v1"
SPEC_URL = f"{BASE_URL}/docs"
DOCS_URL = "https://intervals.icu/api-docs.html"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "docs" / "intervals-api-shapes.md"

LIST = "GET /athlete/0/activities"
DETAIL = "GET /activity/{id}?intervals=true"
STREAMS = "GET /activity/{id}/streams?types=..."
WELLNESS = "GET /athlete/0/wellness"

# Returned by the real API but missing from the OpenAPI spec.
EXTRA_FIELDS = {"_note", "valueType"}
# The spec doesn't enumerate stream types. Anything else is reported as unlisted.
STREAM_TYPES = {
    "altitude", "cadence", "distance", "heartrate", "latlng", "respiration",
    "temp", "time", "torque", "velocity_smooth", "watts",
}
# Fixed stand-ins, so the type reads at a glance and the JSON keeps real types.
PLACEHOLDERS = {
    "null": None,
    "boolean": True,
    "integer": 1,
    "float": 1.5,
    "string": "text",
    "date": "2000-01-01",
    "date-time": "2000-01-01T00:00:00",
}
UNLISTED_FIELD = "<unlisted field>"
UNLISTED_STREAM = "<unlisted stream>"

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}.*")


class CaptureError(Exception):
    """A failure whose message is safe to print (no ids, URLs or data)."""


def json_type(value: Any) -> str:
    """The PLACEHOLDERS key for a scalar. Never includes any of the value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "float"
    if _DATE_TIME.fullmatch(value):
        return "date-time"
    if _DATE.fullmatch(value):
        return "date"
    return "string"


class Shape:
    """The merged structure of every value seen at one position in a response."""

    def __init__(self):
        self.scalars: set[str] = set()
        self.fields: Optional[dict[str, "Shape"]] = None
        self.items: Optional["Shape"] = None

    def observe(self, value: Any, known: set[str]) -> None:
        if isinstance(value, dict):
            self.fields = {} if self.fields is None else self.fields
            for key, child in value.items():
                name = key if key in known else UNLISTED_FIELD
                self.fields.setdefault(name, Shape()).observe(child, known)
        elif isinstance(value, list):
            self.items = Shape() if self.items is None else self.items
            for child in value:
                self.items.observe(child, known)
        else:
            self.scalars.add(json_type(value))

    def render(self) -> Any:
        """JSON whose leaves are placeholders, sorted so refreshes diff cleanly."""
        # A position seen with several types has no single stand-in: it gets a label.
        if self.fields is not None:
            rendered = {name: self.fields[name].render() for name in sorted(self.fields)}
            also = self.scalars | ({"array"} if self.items is not None else set())
            if also:
                rendered["<also>"] = _label(also)
            return rendered
        if self.items is not None:
            rendered = [self.items.render()] if _seen(self.items) else []
            if self.scalars:
                rendered.append(f"<also: {'|'.join(sorted(self.scalars))}>")
            return rendered
        if len(self.scalars) == 1:
            return PLACEHOLDERS[next(iter(self.scalars))]
        return _label(self.scalars)


def _seen(shape: Shape) -> bool:
    return bool(shape.scalars) or shape.fields is not None or shape.items is not None


def _label(types: set[str]) -> str:
    return f"<{'|'.join(sorted(types))}>"


def known_fields(spec: dict) -> set[str]:
    """Every property name of every schema in the public spec, plus EXTRA_FIELDS."""
    names = set(EXTRA_FIELDS)
    for schema in spec.get("components", {}).get("schemas", {}).values():
        names.update(schema.get("properties", {}))
    return names


def shape_of(responses: list, known: set[str]) -> Any:
    shape = Shape()
    for response in responses:
        shape.observe(response, known)
    return shape.render()


def stream_shapes(responses: list, known: set[str]) -> dict:
    """One shape per stream type. Custom streams never show their user-chosen type."""
    shapes: dict[str, Shape] = {}
    for response in responses:
        for entry in response if isinstance(response, list) else []:
            if not isinstance(entry, dict):
                continue
            standard = entry.get("type") in STREAM_TYPES and not entry.get("custom")
            label = entry["type"] if standard else UNLISTED_STREAM
            shapes.setdefault(label, Shape()).observe(entry, known)
    return {label: shapes[label].render() for label in sorted(shapes)}


def render_reference(samples: dict[str, list], known: set[str], source: str) -> str:
    """The reference file. Refuses to produce one with an endpoint missing."""
    sections = {
        LIST: shape_of(samples[LIST], known),
        DETAIL: shape_of(samples[DETAIL], known),
        STREAMS: stream_shapes(samples[STREAMS], known),
        WELLNESS: shape_of(samples[WELLNESS], known),
    }
    for endpoint, shape in sections.items():
        if not samples[endpoint] or not shape:
            raise CaptureError(f"{endpoint}: no data to describe")

    lines = [
        "# intervals.icu API response shapes",
        "",
        "Generated by `scripts/capture_intervals_shapes.py`; see \"intervals.icu API",
        "reference\" in the README to refresh it. Don't edit by hand.",
        f"Official API docs: <{DOCS_URL}>",
        "",
        f"**Source: {source}**",
        "",
        "Structure only. Every value is a fixed placeholder showing its type, never",
        "real data: `1` integer, `1.5` float, `true` boolean, `\"text\"` string,",
        "`\"2000-01-01\"` date, `\"2000-01-01T00:00:00\"` date-time, `null`. A position",
        "seen with several types shows a label such as `\"<float|null>\"`, and `<also>`",
        "marks an object or array that sometimes holds another type. Arrays show one",
        "merged item whatever their real length. `<unlisted field>` and",
        "`<unlisted stream>` stand for names the public spec doesn't list, which",
        "includes user-defined custom fields and streams.",
        "",
        "Streams are shown keyed by stream type, but the API returns a list of these",
        "entries. An invalid name in `types` makes the whole request fail with HTTP 422.",
    ]
    for endpoint, shape in sections.items():
        lines += ["", f"## `{endpoint}`", "", "```json", json.dumps(shape, indent=2), "```"]
    return "\n".join(lines) + "\n"


def get_json(client: httpx.Client, endpoint: str, url: str, params: Optional[dict] = None) -> Any:
    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as e:
        raise CaptureError(f"{endpoint}: request failed ({type(e).__name__})") from None
    if response.status_code != 200:
        raise CaptureError(f"{endpoint}: HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise CaptureError(f"{endpoint}: response is not JSON") from None


def fetch_samples(client: httpx.Client, days: int, max_activities: int) -> dict[str, list]:
    """Real responses, held in memory only. Strava-sourced activities are stubs
    the API won't detail (and Strava data is off limits), so they get no detail."""
    today = dt.date.today()
    window = {"oldest": (today - dt.timedelta(days=days)).isoformat(), "newest": today.isoformat()}
    activities = get_json(client, LIST, f"{BASE_URL}/athlete/0/activities", window)
    samples = {
        LIST: [activities],
        DETAIL: [],
        STREAMS: [],
        WELLNESS: [get_json(client, WELLNESS, f"{BASE_URL}/athlete/0/wellness", window)],
    }

    usable = [a for a in activities if a.get("id") and a.get("source") != "STRAVA"]
    for activity in usable[:max_activities]:
        # One bad activity shouldn't stop a refresh; a missing endpoint still does.
        try:
            detail = get_json(
                client, DETAIL, f"{BASE_URL}/activity/{activity['id']}", {"intervals": "true"}
            )
            samples[DETAIL].append(detail)
            # stream_types lists what this activity has, so all are valid names.
            types = detail.get("stream_types") or []
            params = {"types": ",".join(types)} if types else None
            samples[STREAMS].append(
                get_json(client, STREAMS, f"{BASE_URL}/activity/{activity['id']}/streams", params)
            )
        except CaptureError as e:
            print(f"Skipping one activity: {e}", file=sys.stderr)
    return samples


def spec_samples(spec: dict) -> dict[str, list]:
    """Synthetic responses built from the public spec, for when no key is at hand."""
    schemas = spec["components"]["schemas"]

    def build(schema: dict, parents: tuple = ()) -> Any:
        if "$ref" in schema:
            name = schema["$ref"].rsplit("/", 1)[-1]
            return None if name in parents else build(schemas[name], parents + (name,))
        kind = schema.get("type")
        if kind == "array":
            return [build(schema.get("items", {}), parents)]
        if kind == "object" or "properties" in schema:
            return {k: build(v, parents) for k, v in schema.get("properties", {}).items()}
        if kind == "string":
            key = "date-time" if schema.get("format") == "date-time" else "string"
            return PLACEHOLDERS[key]
        return {
            "integer": PLACEHOLDERS["integer"],
            "number": PLACEHOLDERS["float"],
            "boolean": PLACEHOLDERS["boolean"],
        }.get(kind)

    streams = []
    for stream_type in sorted(STREAM_TYPES):
        # The spec types data/data2 as objects; the API returns arrays of values.
        entry = {**build(schemas["ActivityStream"]), "type": stream_type, "valueType": "text", "custom": False}
        entry["data"] = [PLACEHOLDERS["float"]]
        entry["data2"] = [PLACEHOLDERS["float"]] if stream_type == "latlng" else None
        streams.append(entry)

    return {
        LIST: [[build(schemas["Activity"])]],
        DETAIL: [build(schemas["ActivityWithIntervals"])],
        STREAMS: [streams],
        WELLNESS: [[build(schemas["Wellness"])]],
    }


def capture(from_spec: bool, days: int, max_activities: int) -> str:
    with httpx.Client(timeout=60.0) as public:
        spec = get_json(public, "GET OpenAPI spec", SPEC_URL)
    known = known_fields(spec)

    if from_spec:
        source = (
            "synthetic. Built from the public OpenAPI spec, not from a live response, "
            "so which fields can be null, and integer vs float in stream data, are unconfirmed."
        )
        return render_reference(spec_samples(spec), known, source)

    api_key = os.environ.get("INTERVALS_API_KEY")
    if not api_key:
        raise CaptureError("INTERVALS_API_KEY is not set (or use --from-spec)")
    with httpx.Client(auth=("API_KEY", api_key), timeout=60.0) as client:
        samples = fetch_samples(client, days, max_activities)
    return render_reference(samples, known, "live API responses with all values removed.")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--from-spec", action="store_true",
                        help="use synthetic responses built from the public spec; needs no key")
    parser.add_argument("--days", type=int, default=30, help="date range to sample (default: 30)")
    parser.add_argument("--activities", type=int, default=5,
                        help="activities to sample detail and streams from (default: 5)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    try:
        reference = capture(args.from_spec, args.days, args.activities)
    except CaptureError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    args.output.write_text(reference)
    print(f"Wrote {args.output}. Review `git diff` before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
