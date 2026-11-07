"""Structured cycling steps -> intervals.icu workout text, and parsed steps -> lines."""

import pytest

from train_with_gpt.workout_text import (
    WorkoutError,
    build_description,
    format_duration,
    format_workout_doc,
    render_steps,
)

SWEET_SPOT = [
    {"duration_seconds": 600, "watts_low": 120, "watts_high": 200, "ramp": True, "cadence": 90, "label": "Warmup"},
    {"repeat": 4, "steps": [
        {"duration_seconds": 480, "watts": 250, "cadence_low": 90, "cadence_high": 95},
        {"duration_seconds": 240, "watts": 150},
    ]},
    {"duration_seconds": 600, "watts_low": 180, "watts_high": 120, "ramp": True, "label": "Cooldown"},
]


@pytest.mark.parametrize("seconds, text", [
    (45, "45s"), (60, "1m"), (90, "1m30s"), (3600, "1h"), (5400, "1h30m"), (3750, "1h2m30s"),
])
def test_durations_use_workout_builder_units(seconds, text):
    assert format_duration(seconds) == text


def test_renders_steps_ramps_ranges_cadence_and_repeats():
    lines, total = render_steps(SWEET_SPOT)

    assert lines == [
        "- Warmup 10m ramp 120-200w 90rpm",
        "",
        "4x",
        "- 8m 250w 90-95rpm",
        "- 4m 150w",
        "",
        "- Cooldown 10m ramp 180-120w",
    ]
    assert total == 600 + 4 * (480 + 240) + 600


def test_repeat_blocks_are_separated_by_blank_lines_on_both_sides():
    block = {"repeat": 2, "steps": [{"duration_seconds": 30, "watts": 400}]}
    lines, _ = render_steps([block, block])
    assert lines == ["2x", "- 30s 400w", "", "2x", "- 30s 400w"]


def test_description_puts_notes_above_the_steps():
    text, _ = build_description([{"duration_seconds": 1200, "watts": 180}], "  Easy spin.\nStay seated.  ")
    assert text == "Easy spin.\nStay seated.\n\n- 20m 180w"


def test_empty_notes_are_left_out():
    assert build_description([{"duration_seconds": 60, "watts": 100}], "   ")[0] == "- 1m 100w"


@pytest.mark.parametrize("steps, message", [
    ([], "steps must be a non-empty list"),
    ("10m 200w", "steps must be a non-empty list"),
    ([{"watts": 200}], "steps[0]: duration_seconds must be a whole number"),
    ([{"duration_seconds": 0, "watts": 200}], "duration_seconds must be a whole number from 1"),
    ([{"duration_seconds": 60.5, "watts": 200}], "duration_seconds must be a whole number"),
    ([{"duration_seconds": True, "watts": 200}], "duration_seconds must be a whole number"),
    ([{"duration_seconds": 60}], "give a power target"),
    ([{"duration_seconds": 60, "watts": 200, "watts_low": 100, "watts_high": 300}], "not both"),
    ([{"duration_seconds": 60, "watts_low": 200}], "give a power target"),
    ([{"duration_seconds": 60, "watts_low": 250, "watts_high": 200}], "watts_low must be below watts_high"),
    ([{"duration_seconds": 60, "watts": 200, "ramp": True}], "a ramp needs watts_low"),
    ([{"duration_seconds": 60, "watts_low": 200, "watts_high": 200, "ramp": True}], "different start and end"),
    ([{"duration_seconds": 60, "watts": 3000}], "watts must be a whole number from 1 to 2500"),
    ([{"duration_seconds": 60, "watts": 200, "cadence": 250}], "cadence must be a whole number from 30 to 200"),
    ([{"duration_seconds": 60, "watts": 200, "cadence_low": 90}], "needs both cadence_low and cadence_high"),
    ([{"duration_seconds": 60, "watts": 200, "cadence_low": 95, "cadence_high": 90}], "cadence_low must be below"),
    ([{"duration_seconds": 60, "watts": 200, "cadence": 90, "cadence_low": 80, "cadence_high": 90}], "not both"),
    ([{"duration_seconds": 60, "watts": 200, "label": "Z2 spin"}], "no digits"),
    ([{"duration_seconds": 60, "watts": 200, "label": "Hard 100%"}], "no digits"),
    ([{"duration_seconds": 60, "watts": 200, "power": "high"}], "unknown field(s) power"),
    ([{"repeat": 1, "steps": [{"duration_seconds": 60, "watts": 200}]}], "repeat must be a whole number from 2"),
    ([{"repeat": 3, "steps": []}], "steps[0].steps must be a non-empty list"),
    ([{"repeat": 3, "steps": [{"repeat": 2, "steps": [{"duration_seconds": 60, "watts": 200}]}]}],
     "repeats can't be nested"),
    ([{"repeat": 3, "steps": [{"duration_seconds": 60, "watts": 200}], "watts": 100}], "a repeat block has only"),
    ([{"duration_seconds": 6 * 3600, "watts": 150}, {"duration_seconds": 3 * 3600, "watts": 150}],
     "the maximum is 8h"),
])
def test_invalid_steps_are_refused_with_a_clear_message(steps, message):
    with pytest.raises(WorkoutError) as error:
        render_steps(steps)
    assert message in str(error.value)


@pytest.mark.parametrize("label", [
    "Press lap when ready", "PRESS LAP", "Ramp up", "Freeride", "Easy pace", "Low HR", "Hold rpm",
])
def test_labels_with_workout_builder_keywords_are_refused(label):
    """intervals.icu reads these anywhere in a step: 'press lap' makes the step wait for the
    lap button on Garmin, others change the target."""
    with pytest.raises(WorkoutError, match="reserved"):
        render_steps([{"duration_seconds": 600, "watts": 200, "label": label}])


@pytest.mark.parametrize("label", ["Warmup", "Main set", "Over-unders", "Lapland", "Shred", "Cooldown"])
def test_ordinary_labels_are_kept(label):
    assert render_steps([{"duration_seconds": 600, "watts": 200, "label": label}])[0] == [f"- {label} 10m 200w"]


@pytest.mark.parametrize("notes", ["Warm up well\n- 5m easy", "Do this 3x", "Main set 4X  "])
def test_notes_that_would_parse_as_steps_or_repeats_are_refused(notes):
    with pytest.raises(WorkoutError, match="would be read as a workout step or repeat"):
        build_description([{"duration_seconds": 60, "watts": 100}], notes)


def test_reads_back_parsed_steps_in_watts_with_cadence_and_repeats():
    # Shape from intervals.icu's workout_doc with resolve=true (`_power` in watts).
    doc = {"steps": [
        {"text": "Warmup", "duration": 600, "ramp": True, "warmup": True,
         "power": {"start": 40.0, "end": 66.7, "units": "%ftp"}, "_power": {"start": 120.0, "end": 200.0},
         "cadence": {"value": 90.0, "units": "rpm"}},
        {"reps": 4, "text": "4x", "steps": [
            {"duration": 480, "power": {"value": 250, "units": "w"}, "cadence": {"start": 90, "end": 95, "units": "rpm"}},
            {"duration": 240, "power": {"value": 50.0, "units": "%ftp"}},
        ]},
        {"duration": 1200, "freeride": True},
    ]}

    assert format_workout_doc(doc) == [
        "   - Warmup 10m ramp 120-200 W 90 rpm",
        "   4x",
        "     - 8m 250 W 90-95 rpm",
        "     - 4m 50% FTP",
        "   - 20m free ride",
    ]


def test_no_steps_reads_back_as_nothing():
    assert format_workout_doc(None) == []
    assert format_workout_doc({}) == []
    assert format_workout_doc({"steps": []}) == []
