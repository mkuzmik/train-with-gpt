"""plan_workout / get_planned_workouts / update_planned_workout handlers
(real IntervalsClient, intervals.icu stubbed with respx, synthetic data only)."""

import json

import httpx
import pytest
from httpx import Response

from tests.support import text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.tools import (
    get_planned_workouts_handler,
    plan_workout_handler,
    update_planned_workout_handler,
)

EVENTS = "https://intervals.icu/api/v1/athlete/0/events"
EVENT_7 = f"{EVENTS}/7"
STEPS = [
    {"duration_seconds": 600, "watts_low": 120, "watts_high": 200, "ramp": True, "label": "Warmup"},
    {"repeat": 3, "steps": [{"duration_seconds": 300, "watts": 260, "cadence": 95},
                            {"duration_seconds": 180, "watts": 140}]},
]
STEPS_TEXT = "- Warmup 10m ramp 120-200w\n\n3x\n- 5m 260w 95rpm\n- 3m 140w"
PARSED_DOC = {"steps": [
    {"text": "Warmup", "duration": 600, "ramp": True, "power": {"start": 120, "end": 200, "units": "w"}},
    {"reps": 3, "steps": [
        {"duration": 300, "power": {"value": 260, "units": "w"}, "cadence": {"value": 95, "units": "rpm"}},
        {"duration": 180, "power": {"value": 140, "units": "w"}},
    ]},
]}


def saved_event(**overrides):
    event = {
        "id": 7, "category": "WORKOUT", "type": "Ride", "indoor": True, "name": "Threshold triples",
        "start_date_local": "2030-03-05T00:00:00", "description": STEPS_TEXT, "moving_time": 2040,
        "icu_training_load": 48, "icu_intensity": 82.0, "workout_doc": PARSED_DOC,
    }
    event.update(overrides)
    return event


@pytest.fixture
def intervals(intervals_api_key):
    return IntervalsClient()


# --- plan_workout ------------------------------------------------------------------

async def test_plan_creates_an_indoor_ride_from_the_steps(intervals, http_mock):
    listed = http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))
    created = http_mock.post(EVENTS).mock(return_value=Response(200, json=saved_event()))

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "Threshold triples", "steps": STEPS, "notes": "Seated throughout."},
        intervals,
    ))

    assert dict(listed.calls.last.request.url.params) == {
        "oldest": "2030-03-05", "newest": "2030-03-05", "category": "WORKOUT", "resolve": "true"}
    request = created.calls.last.request
    assert request.url.params["upsertOnUid"] == "false"
    assert json.loads(request.content) == {
        "category": "WORKOUT", "type": "Ride", "indoor": True, "name": "Threshold triples",
        "start_date_local": "2030-03-05T00:00:00",
        "description": "Seated throughout.\n\n" + STEPS_TEXT,
    }
    assert "✅ Planned on intervals.icu" in output
    assert "📅 2030-03-05 | 🆔 7 | Threshold triples (Ride, indoor)" in output
    assert "⏱️ 34m | load 48 | IF 0.82" in output
    assert "- Warmup 10m ramp 120-200 W" in output
    assert "3x\n     - 5m 260 W 95 rpm" in output
    assert "⚠️" not in output


async def test_plan_does_not_create_a_second_workout_on_a_planned_day(intervals, http_mock):
    http_mock.get(EVENTS).mock(return_value=Response(200, json=[saved_event(name="Already there")]))
    created = http_mock.post(EVENTS)

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "Another", "steps": STEPS}, intervals))

    assert not created.called
    assert "already has 1 planned workout(s), so nothing was created" in output
    assert "🆔 7 | Already there" in output
    assert "update_planned_workout" in output and "add_another=true" in output


async def test_plan_with_add_another_skips_the_check(intervals, http_mock):
    listed = http_mock.get(EVENTS)
    created = http_mock.post(EVENTS).mock(return_value=Response(200, json=saved_event(id=8)))

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "Second", "steps": STEPS, "add_another": True}, intervals))

    assert not listed.called
    assert created.called
    assert "🆔 8" in output


@pytest.mark.parametrize("arguments, message", [
    ({"date": "05/03/2030", "name": "x", "steps": STEPS}, "date must be a date as YYYY-MM-DD"),
    ({"name": "x", "steps": STEPS}, "date is required"),
    ({"date": "2030-03-05", "name": " ", "steps": STEPS}, "name is required"),
    ({"date": "2030-03-05", "name": "x", "steps": [{"duration_seconds": 60}]}, "give a power target"),
    ({"date": "2030-03-05", "name": "x", "steps": STEPS, "notes": "- 5m easy"}, "would be read as a workout step"),
    ({"date": "2030-03-05", "name": "x", "steps": STEPS, "add_another": "yes"}, "add_another must be true or false"),
])
async def test_plan_refuses_invalid_input_without_calling_intervals(intervals, http_mock, arguments, message):
    listed, created = http_mock.get(EVENTS), http_mock.post(EVENTS)

    output = text_of(await plan_workout_handler(arguments, intervals))

    assert message in output and "Nothing was sent to intervals.icu" in output
    assert not listed.called and not created.called


async def test_plan_without_a_key_makes_no_request(http_mock):
    created = http_mock.post(EVENTS)
    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "x", "steps": STEPS, "add_another": True}, IntervalsClient()))
    assert "INTERVALS_API_KEY not configured" in output
    assert not created.called


async def test_plan_reports_a_rejected_request(intervals, http_mock):
    http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))
    http_mock.post(EVENTS).mock(return_value=Response(422, json={"error": "Invalid workout"}))

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "x", "steps": STEPS}, intervals))

    assert "❌ intervals.icu refused the request (HTTP 422)" in output
    assert "Invalid workout" in output


async def test_plan_timeout_says_it_may_have_been_created(intervals, http_mock):
    http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))
    http_mock.post(EVENTS).mock(side_effect=httpx.ReadTimeout("timed out"))

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "x", "steps": STEPS}, intervals))

    assert "may or may not have been created" in output
    assert "get_planned_workouts for 2030-03-05" in output


async def test_plan_warns_when_intervals_parsed_no_steps(intervals, http_mock):
    http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))
    http_mock.post(EVENTS).mock(return_value=Response(200, json=saved_event(workout_doc={})))

    output = text_of(await plan_workout_handler(
        {"date": "2030-03-05", "name": "x", "steps": STEPS}, intervals))

    assert "(no structured steps)" in output
    assert "⚠️ intervals.icu didn't return any structured steps" in output


# --- get_planned_workouts ----------------------------------------------------------

async def test_get_lists_a_range_sorted_by_date(intervals, http_mock):
    listed = http_mock.get(EVENTS).mock(return_value=Response(200, json=[
        saved_event(id=9, name="Later", start_date_local="2030-03-07T00:00:00"),
        saved_event(id=7, name="Earlier"),
    ]))

    output = text_of(await get_planned_workouts_handler(
        {"start_date": "2030-03-05", "end_date": "2030-03-07"}, intervals))

    assert dict(listed.calls.last.request.url.params) == {
        "oldest": "2030-03-05", "newest": "2030-03-07", "category": "WORKOUT", "resolve": "true"}
    assert "Planned workouts for 2030-03-05 to 2030-03-07 (2):" in output
    assert output.index("Earlier") < output.index("Later")


async def test_get_defaults_to_a_single_day_and_says_when_empty(intervals, http_mock):
    listed = http_mock.get(EVENTS).mock(return_value=Response(200, json=[]))

    output = text_of(await get_planned_workouts_handler({"start_date": "2030-03-05", "end_date": None}, intervals))

    assert listed.calls.last.request.url.params["newest"] == "2030-03-05"
    assert output == "No planned workouts for 2030-03-05."


async def test_get_shows_notes_and_other_sports(intervals, http_mock):
    http_mock.get(EVENTS).mock(return_value=Response(200, json=[saved_event(
        type="Run", indoor=None, workout_doc={"description": "Easy aerobic", "steps": [
            {"duration": 1800, "hr": {"start": 70, "end": 80, "units": "%hr"}}]},
    )]))

    output = text_of(await get_planned_workouts_handler({"start_date": "2030-03-05"}, intervals))

    assert "Threshold triples (Run)" in output
    assert "Notes: Easy aerobic" in output
    assert "- 30m 70-80% HR" in output


@pytest.mark.parametrize("arguments, message", [
    ({}, "start_date is required"),
    ({"start_date": "2030-03-05", "end_date": "2030-03-01"}, "can't be before start_date"),
    ({"start_date": "2030-01-01", "end_date": "2030-02-01"}, "date range too large (32 days)"),
])
async def test_get_refuses_invalid_ranges(intervals, http_mock, arguments, message):
    listed = http_mock.get(EVENTS)
    output = text_of(await get_planned_workouts_handler(arguments, intervals))
    assert message in output
    assert not listed.called


# --- update_planned_workout --------------------------------------------------------

async def test_update_replaces_steps_and_notes_keeping_other_fields(intervals, http_mock):
    http_mock.get(EVENT_7).mock(return_value=Response(200, json=saved_event(start_date_local="2030-03-05T06:30:00")))
    updated = http_mock.put(EVENT_7).mock(return_value=Response(200, json=saved_event(name="Easier")))

    output = text_of(await update_planned_workout_handler({
        "workout_id": 7, "name": "Easier", "steps": [{"duration_seconds": 2700, "watts": 170}], "notes": "Tired legs.",
    }, intervals))

    assert json.loads(updated.calls.last.request.content) == {
        "category": "WORKOUT", "type": "Ride", "indoor": True, "name": "Easier",
        "start_date_local": "2030-03-05T06:30:00", "description": "Tired legs.\n\n- 45m 170w",
    }
    assert "✅ Updated on intervals.icu" in output and "Easier" in output


async def test_update_moves_the_date_and_keeps_the_time_and_steps(intervals, http_mock):
    http_mock.get(EVENT_7).mock(return_value=Response(200, json=saved_event(start_date_local="2030-03-05T06:30:00")))
    updated = http_mock.put(EVENT_7).mock(return_value=Response(200, json=saved_event()))

    await update_planned_workout_handler({"workout_id": "7", "date": "2030-03-06"}, intervals)

    body = json.loads(updated.calls.last.request.content)
    assert body["start_date_local"] == "2030-03-06T06:30:00"
    assert body["description"] == STEPS_TEXT
    assert body["name"] == "Threshold triples"


async def test_update_unknown_or_non_workout_id(intervals, http_mock):
    http_mock.get(EVENT_7).mock(return_value=Response(404))
    updated = http_mock.put(EVENT_7)
    output = text_of(await update_planned_workout_handler({"workout_id": 7, "name": "x"}, intervals))
    assert "No planned workout with id 7" in output
    assert not updated.called

    http_mock.get(EVENT_7).mock(return_value=Response(200, json=saved_event(category="NOTE")))
    output = text_of(await update_planned_workout_handler({"workout_id": 7, "name": "x"}, intervals))
    assert "No planned workout with id 7" in output
    assert not updated.called


async def test_update_refuses_new_steps_on_a_non_cycling_workout(intervals, http_mock):
    http_mock.get(EVENT_7).mock(return_value=Response(200, json=saved_event(type="Run")))
    updated = http_mock.put(EVENT_7)

    output = text_of(await update_planned_workout_handler(
        {"workout_id": 7, "steps": [{"duration_seconds": 60, "watts": 100}]}, intervals))

    assert "only cycling workouts' steps can be replaced" in output
    assert not updated.called


@pytest.mark.parametrize("arguments, message", [
    ({"workout_id": 7}, "give at least one of date, name or steps"),
    ({"workout_id": 7, "notes": "x"}, "notes can only be changed together with steps"),
    ({"workout_id": "abc", "name": "x"}, "workout_id must be the planned workout's numeric id"),
    ({"workout_id": 7, "date": "tomorrow"}, "date must be a date as YYYY-MM-DD"),
    ({"workout_id": 7, "steps": [{"repeat": 2, "steps": [{"repeat": 2, "steps": []}]}]}, "can't be nested"),
])
async def test_update_refuses_invalid_input_without_calling_intervals(intervals, http_mock, arguments, message):
    fetched, updated = http_mock.get(EVENT_7), http_mock.put(EVENT_7)

    output = text_of(await update_planned_workout_handler(arguments, intervals))

    assert message in output
    assert not fetched.called and not updated.called


async def test_update_reports_a_rejected_request(intervals, http_mock):
    http_mock.get(EVENT_7).mock(return_value=Response(200, json=saved_event()))
    http_mock.put(EVENT_7).mock(return_value=Response(403, text="Forbidden"))

    output = text_of(await update_planned_workout_handler({"workout_id": 7, "name": "x"}, intervals))

    assert "❌ intervals.icu refused the request (HTTP 403): Forbidden" in output
