"""Planned indoor cycling workouts on the intervals.icu calendar (issue #57).

plan_workout, get_planned_workouts and update_planned_workout. Personal
installs use the configured key; hosted users their own connected key (the
intervals.icu connect page says it's also used for planning workouts).
"""

import sys
from datetime import datetime
from typing import Any, Optional

import httpx
from mcp.types import TextContent, Tool, ToolAnnotations

from ..workout_text import (
    MAX_CADENCE,
    MAX_NAME_LENGTH,
    MAX_NOTES_LENGTH,
    MAX_REPEAT,
    MAX_STEP_SECONDS,
    MAX_WATTS,
    MIN_CADENCE,
    MIN_REPEAT,
    WorkoutError,
    build_description,
    check_name,
    format_duration,
    format_workout_doc,
    has_steps,
)

PLANNED_WORKOUT_TOOLS = ("plan_workout", "get_planned_workouts", "update_planned_workout")
INTERVALS_NOT_CONNECTED_MESSAGE = (
    "ℹ️ Planned workouts live on the intervals.icu calendar, and intervals.icu isn't connected for "
    "this athlete. To add it, sign in to this server again (e.g. disconnect and reconnect this "
    "connector in Claude's settings) and paste your intervals.icu API key on the page shown after "
    "the Strava login."
)
INTERVALS_NOT_OFFERED_MESSAGE = (
    "ℹ️ This server doesn't offer connecting intervals.icu, so workouts can't be planned on an "
    "intervals.icu calendar here."
)
MAX_RANGE_DAYS = 31
CYCLING_TYPES = ("Ride", "VirtualRide")
# What plan_workout creates. `indoor` marks a turbo session; Ride keeps the
# athlete's cycling FTP and zones for load and %FTP.
NEW_WORKOUT = {"category": "WORKOUT", "type": "Ride", "indoor": True}

_INT = "integer"
_STEP_PROPERTIES = {
    "duration_seconds": {"type": _INT, "minimum": 1, "maximum": MAX_STEP_SECONDS,
                         "description": "Step length in seconds (e.g. 600 for 10 minutes)."},
    "watts": {"type": _INT, "minimum": 1, "maximum": MAX_WATTS,
              "description": "Fixed power target in watts. Or use watts_low + watts_high."},
    "watts_low": {"type": _INT, "minimum": 1, "maximum": MAX_WATTS,
                  "description": "Lower end of a power range, or a ramp's starting watts."},
    "watts_high": {"type": _INT, "minimum": 1, "maximum": MAX_WATTS,
                   "description": "Upper end of a power range, or a ramp's ending watts."},
    "ramp": {"type": "boolean",
             "description": "true: power changes steadily from watts_low to watts_high (can go down for a cool-down)."},
    "cadence": {"type": _INT, "minimum": MIN_CADENCE, "maximum": MAX_CADENCE,
                "description": "Optional cadence target in rpm. Or use cadence_low + cadence_high."},
    "cadence_low": {"type": _INT, "minimum": MIN_CADENCE, "maximum": MAX_CADENCE,
                    "description": "Optional lower end of a cadence range in rpm."},
    "cadence_high": {"type": _INT, "minimum": MIN_CADENCE, "maximum": MAX_CADENCE,
                     "description": "Optional upper end of a cadence range in rpm."},
    "label": {"type": "string",
              "description": "Optional short cue shown on the step, e.g. 'Warmup' (letters only, no digits)."},
}
_STEP_SCHEMA = {
    "type": "object",
    "properties": _STEP_PROPERTIES,
    "required": ["duration_seconds"],
}
_REPEAT_SCHEMA = {
    "type": "object",
    "properties": {
        "repeat": {"type": _INT, "minimum": MIN_REPEAT, "maximum": MAX_REPEAT,
                   "description": "How many times to repeat the steps."},
        "steps": {"type": "array", "items": _STEP_SCHEMA, "minItems": 1,
                  "description": "Steps of one repetition (no nested repeats)."},
    },
    "required": ["repeat", "steps"],
}
STEPS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {"anyOf": [_STEP_SCHEMA, _REPEAT_SCHEMA]},
    "description": (
        "The workout in order. Each item is a step {duration_seconds, watts | watts_low+watts_high "
        "[+ ramp], optional cadence | cadence_low+cadence_high, optional label}, or a repeat block "
        "{repeat: N, steps: [...]} (no nested repeats)."
    ),
}
_NOTES_SCHEMA = {
    "type": ["string", "null"],
    "description": (
        f"Optional text shown above the steps (up to {MAX_NOTES_LENGTH} characters), e.g. the purpose "
        "of the session. Lines must not start with '-' or end with a repeat count like '3x'."
    ),
}


def _text(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=message)]


def plan_workout_tool() -> Tool:
    return Tool(
        name="plan_workout",
        description=(
            "Put an indoor (turbo trainer) cycling workout on the athlete's intervals.icu calendar for a "
            "date: steps with duration and target watts (fixed, range or ramp), optional cadence, and "
            "repeat blocks. Only call it for a workout the athlete has agreed to. intervals.icu works out "
            "the duration and training load. If the date already has a planned workout, nothing is "
            "created and the existing one is shown: change it with update_planned_workout, or pass "
            "add_another=true to plan a second workout that day."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Local date YYYY-MM-DD."},
                "name": {"type": "string", "description": f"Workout title (one line, up to {MAX_NAME_LENGTH} characters)."},
                "steps": STEPS_SCHEMA,
                "notes": _NOTES_SCHEMA,
                "add_another": {
                    "type": ["boolean", "null"],
                    "description": "true: create it even if the date already has a planned workout. Default false.",
                },
            },
            "required": ["date", "name", "steps"],
        },
        annotations=ToolAnnotations(
            title="Plan a turbo workout", readOnlyHint=False, destructiveHint=False,
            idempotentHint=False, openWorldHint=True,
        ),
    )


def get_planned_workouts_tool() -> Tool:
    return Tool(
        name="get_planned_workouts",
        description=(
            "Read the planned workouts on the athlete's intervals.icu calendar for a date or a date "
            f"range (up to {MAX_RANGE_DAYS} days): id, name, sport, duration, training load and each "
            "step with its target in watts and cadence. Use it before planning a day and to check a "
            "workout after planning or changing it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Local date YYYY-MM-DD. Required."},
                "end_date": {"type": ["string", "null"],
                             "description": "Local date YYYY-MM-DD, inclusive. Defaults to start_date."},
            },
            "required": ["start_date"],
        },
        annotations=ToolAnnotations(
            title="Get planned workouts", readOnlyHint=True, openWorldHint=True,
        ),
    )


def update_planned_workout_tool() -> Tool:
    return Tool(
        name="update_planned_workout",
        description=(
            "Change a planned workout on the athlete's intervals.icu calendar by its id (from "
            "get_planned_workouts or plan_workout): move it to another date, rename it, or replace its "
            "steps. Only for workouts the athlete has agreed to change. Giving steps replaces the whole "
            "structure and the notes above it: pass notes again to keep them. Steps can only be replaced "
            "on cycling workouts."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workout_id": {"type": _INT, "description": "The planned workout's id."},
                "date": {"type": ["string", "null"], "description": "New local date YYYY-MM-DD."},
                "name": {"type": ["string", "null"], "description": "New title."},
                "steps": {**STEPS_SCHEMA, "type": ["array", "null"],
                          "description": "New steps, replacing the old ones. " + STEPS_SCHEMA["description"]},
                "notes": {**_NOTES_SCHEMA, "description": "New notes; only together with steps. " + _NOTES_SCHEMA["description"]},
            },
            "required": ["workout_id"],
        },
        annotations=ToolAnnotations(
            title="Update a planned workout", readOnlyHint=False, destructiveHint=True,
            idempotentHint=True, openWorldHint=True,
        ),
    )


# --- shared ---------------------------------------------------------------------

def _parse_date(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise WorkoutError(f"{field} is required, as YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise WorkoutError(f"{field} must be a date as YYYY-MM-DD, got {value!r}") from None


def _event_date(event: dict) -> str:
    return str(event.get("start_date_local") or "")[:10]


def format_event(event: dict) -> str:
    """One planned workout as the tools show it."""
    sport = event.get("type") or "?"
    if event.get("indoor"):
        sport += ", indoor"
    lines = [f"📅 {_event_date(event)} | 🆔 {event.get('id')} | {event.get('name') or '(no name)'} ({sport})"]

    stats = []
    if event.get("moving_time"):
        stats.append(f"⏱️ {format_duration(event['moving_time'])}")
    if event.get("icu_training_load") is not None:
        stats.append(f"load {event['icu_training_load']}")
    if event.get("icu_intensity") is not None:
        stats.append(f"IF {event['icu_intensity'] / 100:.2f}")  # reported as % of FTP
    if stats:
        lines.append("   " + " | ".join(stats))

    doc = event.get("workout_doc")
    notes = doc.get("description") if isinstance(doc, dict) else None
    if notes:
        notes = str(notes).strip()
        lines.append("   Notes: " + (notes if len(notes) <= 300 else notes[:300] + "…"))
    steps = format_workout_doc(doc)
    if steps:
        lines.append("   Steps:")
        lines += steps
    else:
        lines.append("   (no structured steps)")
    return "\n".join(lines)


def _http_error(e: httpx.HTTPStatusError) -> str:
    detail = (e.response.text or "").strip().replace("\n", " ")
    if len(detail) > 300:
        detail = detail[:300] + "…"
    return f"❌ intervals.icu refused the request (HTTP {e.response.status_code})" + (f": {detail}" if detail else "")


def _unparsed_warning(event: dict) -> str:
    if has_steps(event):
        return ""
    return ("\n\n⚠️ intervals.icu didn't return any structured steps for this workout, so it may not have "
            "understood them. Check it with get_planned_workouts.")


def _error(e: Exception, action: str) -> list[TextContent]:
    if isinstance(e, WorkoutError):
        return _text(f"❌ {e}. Nothing was sent to intervals.icu.")
    if isinstance(e, httpx.HTTPStatusError):
        return _text(_http_error(e))
    print(f"Error while {action}: {type(e).__name__}", file=sys.stderr)
    return _text(f"❌ Error while {action}: {e}")


# --- handlers -------------------------------------------------------------------

async def get_planned_workouts_handler(arguments: dict, intervals) -> list[TextContent]:
    try:
        start = _parse_date(arguments.get("start_date"), "start_date")
        end_arg = arguments.get("end_date")
        end = start if end_arg is None else _parse_date(end_arg, "end_date")
        if end < start:
            raise WorkoutError(f"end_date ({end}) can't be before start_date ({start})")
        days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
        if days > MAX_RANGE_DAYS:
            raise WorkoutError(f"date range too large ({days} days); the maximum is {MAX_RANGE_DAYS}")

        events = await intervals.list_events(start, end)
        period = start if start == end else f"{start} to {end}"
        if not events:
            return _text(f"No planned workouts for {period}.")
        events = sorted(events, key=lambda e: (str(e.get("start_date_local") or ""), e.get("id") or 0))
        lines = [f"Planned workouts for {period} ({len(events)}):", ""]
        lines += [format_event(e) + "\n" for e in events]
        return _text("\n".join(lines).rstrip())
    except Exception as e:
        return _error(e, "reading planned workouts")


async def plan_workout_handler(arguments: dict, intervals) -> list[TextContent]:
    try:
        date = _parse_date(arguments.get("date"), "date")
        name = check_name(arguments.get("name"))
        description, _ = build_description(arguments.get("steps"), arguments.get("notes"))
        add_another = arguments.get("add_another") or False
        if not isinstance(add_another, bool):
            raise WorkoutError("add_another must be true or false")

        if not add_another:
            existing = await intervals.list_events(date, date)
            if existing:
                shown = "\n\n".join(format_event(e) for e in existing)
                return _text(
                    f"⚠️ {date} already has {len(existing)} planned workout(s), so nothing was created:\n\n"
                    f"{shown}\n\nTo change one, use update_planned_workout with its id. To plan another "
                    "workout on the same day, call plan_workout again with add_another=true."
                )

        event = {**NEW_WORKOUT, "name": name, "start_date_local": f"{date}T00:00:00", "description": description}
        try:
            saved = await intervals.create_event(event)
        except httpx.TimeoutException:
            return _text(
                "⚠️ intervals.icu didn't answer in time, so the workout may or may not have been created. "
                f"Check with get_planned_workouts for {date} before trying again."
            )
        return _text(f"✅ Planned on intervals.icu:\n\n{format_event(saved)}{_unparsed_warning(saved)}")
    except Exception as e:
        return _error(e, "planning the workout")


def _parse_id(value: Any) -> int:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise WorkoutError("workout_id must be the planned workout's numeric id")
    return value


async def update_planned_workout_handler(arguments: dict, intervals) -> list[TextContent]:
    try:
        workout_id = _parse_id(arguments.get("workout_id"))
        date = arguments.get("date")
        date = None if date is None else _parse_date(date, "date")
        name = arguments.get("name")
        name = None if name is None else check_name(name)
        steps, notes = arguments.get("steps"), arguments.get("notes")
        if notes is not None and steps is None:
            raise WorkoutError("notes can only be changed together with steps (giving steps replaces both)")
        description = None if steps is None else build_description(steps, notes)[0]
        if date is None and name is None and description is None:
            raise WorkoutError("give at least one of date, name or steps to change")

        current = await intervals.get_event(workout_id)
        if current is None or current.get("category") != "WORKOUT":
            return _text(f"❌ No planned workout with id {workout_id}. Find it with get_planned_workouts.")
        if description is not None and current.get("type") not in CYCLING_TYPES:
            return _text(
                f"❌ Workout {workout_id} is a {current.get('type') or 'non-cycling'} workout; "
                "only cycling workouts' steps can be replaced. Nothing was changed."
            )

        start = str(current.get("start_date_local") or "")
        if date is not None:
            # Keep a planned time of day, if it had one.
            start = date + (start[10:] if len(start) > 10 else "T00:00:00")
        # Send every field this tool manages, so the result is the same whether
        # intervals.icu treats PUT as a partial or a full update of them.
        update = {
            "category": "WORKOUT",
            "type": current.get("type"),
            "name": name if name is not None else current.get("name"),
            "start_date_local": start,
            "description": description if description is not None else current.get("description"),
        }
        if current.get("indoor") is not None:
            update["indoor"] = current["indoor"]

        saved = await intervals.update_event(workout_id, update)
        if saved is None:
            return _text(f"❌ No planned workout with id {workout_id}. Find it with get_planned_workouts.")
        warning = _unparsed_warning(saved) if description is not None else ""
        return _text(f"✅ Updated on intervals.icu:\n\n{format_event(saved)}{warning}")
    except Exception as e:
        return _error(e, "updating the planned workout")
