"""Planned cycling workouts: structured steps <-> intervals.icu's workout text.

intervals.icu only accepts a workout's structure as text in the event's
`description` (its workout-builder syntax; posting `workout_doc` directly isn't
supported). It parses that text into `workout_doc`, which is what comes back
when the event is read. So the tools take structured steps, check them, and
render the text here; reading back goes through `format_workout_doc`.

Syntax used (intervals.icu "Workout Builder Syntax Quick Guide"):
    - Warmup 10m ramp 120-200w 90rpm      one step per "-" line
    4x                                    repeat block, blank line before and after
    - 8m 250w 90-95rpm
Nested repeats are not supported by intervals.icu.
"""

import re
from typing import Any, Optional

MAX_STEP_SECONDS = 6 * 3600
MAX_TOTAL_SECONDS = 8 * 3600
MAX_WATTS = 2500
MIN_CADENCE, MAX_CADENCE = 30, 200
MIN_REPEAT, MAX_REPEAT = 2, 50
MAX_STEPS = 60
MAX_LABEL_LENGTH = 40
MAX_NAME_LENGTH = 100
MAX_NOTES_LENGTH = 2000

# Letters, spaces and light punctuation only: digits, % or ^ in a cue could be
# read by intervals.icu as a duration, target or timed prompt.
_LABEL_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|[ '&/(),.!?-])*$")
# Workout-builder keywords intervals.icu reads anywhere in a step, so a label
# containing one would change the step: "press lap" makes it last until the lap
# button is pressed (Garmin), the others change or switch off the target.
_RESERVED_LABEL_RE = re.compile(
    r"\b(press\s+lap|ramp|free\s*ride|pace|hr|lthr|mmp|rpm)\b", re.IGNORECASE
)
# A notes line that intervals.icu would read as a step or a repeat header.
_STEP_LINE_RE = re.compile(r"^\s*-")
_REPEAT_LINE_RE = re.compile(r"\d+\s*x\s*$", re.IGNORECASE)

STEP_FIELDS = ("duration_seconds", "watts", "watts_low", "watts_high", "ramp",
               "cadence", "cadence_low", "cadence_high", "label")


class WorkoutError(ValueError):
    """Invalid workout input; the message says what to fix."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int_in(value: Any, low: int, high: int, where: str, what: str) -> int:
    if not _is_int(value) or not low <= value <= high:
        raise WorkoutError(f"{where}: {what} must be a whole number from {low} to {high}, got {value!r}")
    return value


def format_duration(seconds: int) -> str:
    """Seconds in workout-builder form: 3600 -> 1h, 90 -> 1m30s, 5400 -> 1h30m."""
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    parts = [f"{hours}h" if hours else "", f"{minutes}m" if minutes else "", f"{secs}s" if secs else ""]
    return "".join(parts) or "0s"


def _step_line(step: Any, where: str) -> tuple[str, int]:
    """One validated step as a workout-builder line, and its duration."""
    if not isinstance(step, dict):
        raise WorkoutError(f"{where}: each step must be an object")
    unknown = set(step) - set(STEP_FIELDS)
    if unknown:
        raise WorkoutError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")

    seconds = _int_in(step.get("duration_seconds"), 1, MAX_STEP_SECONDS, where, "duration_seconds")

    watts, low, high = step.get("watts"), step.get("watts_low"), step.get("watts_high")
    ramp = step.get("ramp") or False
    if not isinstance(ramp, bool):
        raise WorkoutError(f"{where}: ramp must be true or false")
    if watts is not None and (low is not None or high is not None):
        raise WorkoutError(f"{where}: give either watts, or watts_low and watts_high, not both")
    if watts is not None:
        if ramp:
            raise WorkoutError(f"{where}: a ramp needs watts_low (start) and watts_high (end)")
        target = f"{_int_in(watts, 1, MAX_WATTS, where, 'watts')}w"
    elif low is not None and high is not None:
        low = _int_in(low, 1, MAX_WATTS, where, "watts_low")
        high = _int_in(high, 1, MAX_WATTS, where, "watts_high")
        if ramp:
            if low == high:
                raise WorkoutError(f"{where}: a ramp needs different start and end watts")
            target = f"ramp {low}-{high}w"  # may go down, e.g. a cool-down ramp
        else:
            if low >= high:
                raise WorkoutError(f"{where}: watts_low must be below watts_high")
            target = f"{low}-{high}w"
    else:
        raise WorkoutError(f"{where}: give a power target: watts, or watts_low and watts_high")

    parts = []
    label = step.get("label")
    if label is not None:
        if not isinstance(label, str) or not label.strip():
            raise WorkoutError(f"{where}: label must be non-empty text")
        label = label.strip()
        if len(label) > MAX_LABEL_LENGTH or not _LABEL_RE.match(label):
            raise WorkoutError(
                f"{where}: label must be up to {MAX_LABEL_LENGTH} letters, spaces and simple punctuation, "
                "with no digits, % or ^ (intervals.icu would read those as part of the step)"
            )
        reserved = _RESERVED_LABEL_RE.search(label)
        if reserved:
            raise WorkoutError(
                f"{where}: label contains {reserved.group(0)!r}, a reserved workout word that intervals.icu "
                "would act on (e.g. 'press lap' waits for the lap button); choose other words"
            )
        parts.append(label)
    parts += [format_duration(seconds), target]

    cadence, c_low, c_high = step.get("cadence"), step.get("cadence_low"), step.get("cadence_high")
    if cadence is not None and (c_low is not None or c_high is not None):
        raise WorkoutError(f"{where}: give either cadence, or cadence_low and cadence_high, not both")
    if cadence is not None:
        parts.append(f"{_int_in(cadence, MIN_CADENCE, MAX_CADENCE, where, 'cadence')}rpm")
    elif c_low is not None or c_high is not None:
        if c_low is None or c_high is None:
            raise WorkoutError(f"{where}: a cadence range needs both cadence_low and cadence_high")
        c_low = _int_in(c_low, MIN_CADENCE, MAX_CADENCE, where, "cadence_low")
        c_high = _int_in(c_high, MIN_CADENCE, MAX_CADENCE, where, "cadence_high")
        if c_low >= c_high:
            raise WorkoutError(f"{where}: cadence_low must be below cadence_high")
        parts.append(f"{c_low}-{c_high}rpm")

    return "- " + " ".join(parts), seconds


def _check_count(items: Any, where: str) -> list:
    if not isinstance(items, list) or not items:
        raise WorkoutError(f"{where} must be a non-empty list")
    if len(items) > MAX_STEPS:
        raise WorkoutError(f"{where} has {len(items)} items; the maximum is {MAX_STEPS}")
    return items


def render_steps(steps: Any) -> tuple[list[str], int]:
    """Validated steps as workout-builder lines (with blank lines around repeat
    blocks, as intervals.icu requires), and the total duration in seconds."""
    lines: list[str] = []
    total = 0
    for i, item in enumerate(_check_count(steps, "steps")):
        where = f"steps[{i}]"
        if isinstance(item, dict) and ("repeat" in item or "steps" in item):
            extra = set(item) - {"repeat", "steps"}
            if extra:
                raise WorkoutError(f"{where}: a repeat block has only 'repeat' and 'steps', not {', '.join(sorted(extra))}")
            times = _int_in(item.get("repeat"), MIN_REPEAT, MAX_REPEAT, where, "repeat")
            block, block_seconds = [], 0
            for j, inner in enumerate(_check_count(item.get("steps"), f"{where}.steps")):
                inner_where = f"{where}.steps[{j}]"
                if isinstance(inner, dict) and ("repeat" in inner or "steps" in inner):
                    raise WorkoutError(f"{inner_where}: repeats can't be nested (intervals.icu doesn't support it)")
                line, seconds = _step_line(inner, inner_where)
                block.append(line)
                block_seconds += seconds
            if lines and lines[-1] != "":
                lines.append("")
            lines += [f"{times}x", *block, ""]
            total += times * block_seconds
        else:
            line, seconds = _step_line(item, where)
            lines.append(line)
            total += seconds
    while lines and lines[-1] == "":
        lines.pop()
    if total > MAX_TOTAL_SECONDS:
        raise WorkoutError(
            f"the workout lasts {format_duration(total)}; the maximum is {format_duration(MAX_TOTAL_SECONDS)}"
        )
    return lines, total


def check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise WorkoutError("name is required")
    name = name.strip()
    if len(name) > MAX_NAME_LENGTH or "\n" in name or "\r" in name:
        raise WorkoutError(f"name must be one line of up to {MAX_NAME_LENGTH} characters")
    return name


def check_notes(notes: Any) -> Optional[str]:
    """Free text shown above the steps; None if empty. Lines intervals.icu would
    parse as steps or repeats are refused rather than silently changing the workout."""
    if notes is None:
        return None
    if not isinstance(notes, str):
        raise WorkoutError("notes must be text")
    notes = notes.strip()
    if not notes:
        return None
    if len(notes) > MAX_NOTES_LENGTH:
        raise WorkoutError(f"notes are too long ({len(notes)} characters); the maximum is {MAX_NOTES_LENGTH}")
    for line in notes.splitlines():
        if _STEP_LINE_RE.match(line) or _REPEAT_LINE_RE.search(line):
            raise WorkoutError(
                f"notes line {line.strip()!r} would be read as a workout step or repeat; "
                "don't start note lines with '-' or end them with a repeat count like '3x'"
            )
    return notes


def build_description(steps: Any, notes: Any = None) -> tuple[str, int]:
    """The event description intervals.icu parses: notes, a blank line, the steps."""
    lines, total = render_steps(steps)
    notes = check_notes(notes)
    text = "\n".join(lines)
    return (f"{notes}\n\n{text}" if notes else text), total


# --- reading back --------------------------------------------------------------

def _number(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _span(target: dict, ramp: bool = False) -> Optional[str]:
    start, end = target.get("start"), target.get("end")
    # A resolved fixed target (resolve=true) comes back as start == end == value.
    if start is not None and end is not None and (ramp or start != end):
        return f"{_number(start)}-{_number(end)}"
    if start is not None and start == end:
        return _number(start)
    if target.get("value") is not None:
        return _number(target["value"])
    return None


_UNIT_LABELS = {"%ftp": "% FTP", "w": " W", "watts": " W", "rpm": " rpm", "%hr": "% HR",
                "%lthr": "% LTHR", "%pace": "% pace", "power_zone": "", "hr_zone": " HR"}


def _target(target: Any, default_unit: str = "", ramp: bool = False) -> Optional[str]:
    if not isinstance(target, dict):
        return None
    span = _span(target, ramp)
    if span is None:
        return None
    units = str(target.get("units") or default_unit)
    if units == "power_zone":
        return f"Z{span}"
    return span + _UNIT_LABELS.get(units.lower(), f" {units}" if units else "")


def _step_text(step: dict) -> str:
    parts = []
    if step.get("text"):
        parts.append(str(step["text"]).strip())
    if step.get("duration") is not None:
        parts.append(format_duration(step["duration"]))
    elif step.get("distance") is not None:
        parts.append(f"{_number(step['distance'])} m")
    if step.get("freeride"):
        parts.append("free ride")
    else:
        # `_power` is present with resolve=true: the target converted to watts.
        ramp = bool(step.get("ramp"))
        power = _target(step.get("_power"), "w", ramp) or _target(step.get("power"), ramp=ramp)
        if power:
            parts.append(("ramp " if ramp else "") + power)
        for key in ("hr", "pace"):
            other = _target(step.get(key))
            if other:
                parts.append(other)
    cadence = _target(step.get("cadence"), "rpm")
    if cadence:
        parts.append(cadence)
    return " ".join(parts) or "(empty step)"


def format_workout_doc(doc: Any, indent: str = "   ") -> list[str]:
    """The parsed steps intervals.icu returned, one line each, repeats indented."""
    steps = doc.get("steps") if isinstance(doc, dict) else None
    if not steps:
        return []
    lines = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if step.get("reps") and step.get("steps"):
            lines.append(f"{indent}{step['reps']}x")
            lines += [f"{indent}  - {_step_text(s)}" for s in step["steps"] if isinstance(s, dict)]
        else:
            lines.append(f"{indent}- {_step_text(step)}")
    return lines


def has_steps(event: dict) -> bool:
    doc = event.get("workout_doc")
    return bool(isinstance(doc, dict) and doc.get("steps"))
