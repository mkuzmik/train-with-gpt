"""Get wellness tool: training load (fitness, fatigue, form) from intervals.icu."""

import sys
from datetime import date, datetime, timedelta
from mcp.types import Tool, TextContent

from ..helpers import NO_WELLNESS_DATA_MESSAGE
from ..strava_client import StravaClient

# A full year covers a season or a build-up; intervals.icu returns it in one request.
MAX_RANGE_DAYS = 366
# Longer ranges get one row per ISO week unless daily rows are asked for.
DAILY_ROWS_MAX_DAYS = 14
METRICS = ("load",)
LOAD_FIELDS = ["id", "ctl", "atl", "rampRate", "ctlLoad"]


def get_wellness_tool() -> Tool:
    """Return the get_wellness tool definition."""
    return Tool(
        name="get_wellness",
        description=(
            f"Get daily wellness metrics from intervals.icu for a date range (up to {MAX_RANGE_DAYS} days). "
            "metrics='load' (default): fitness (CTL, long-term training load), fatigue (ATL, "
            "short-term training load), form (fitness - fatigue, TSB; also as % of fitness), ramp "
            "rate and the day's training load, as calculated by intervals.icu. Ranges up to "
            f"{DAILY_ROWS_MAX_DAYS} days list every day; longer ranges list one row per ISO week "
            "(values at the week's last day, load summed) unless daily=true. Includes a summary "
            "(latest values, fitness change, peak fitness, lowest/highest form). Read form and "
            "ramp rate against the athlete's own history and plan, not fixed thresholds."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format. Required.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Required.",
                },
                "metrics": {
                    "type": "string",
                    "enum": list(METRICS),
                    "description": "Which metrics to return. 'load': fitness, fatigue, form, ramp rate, daily load.",
                },
                "daily": {
                    "type": "boolean",
                    "description": f"List every day even for ranges longer than {DAILY_ROWS_MAX_DAYS} days.",
                },
            },
            "required": ["start_date", "end_date"],
        },
    )


def _form(fitness: float, fatigue: float) -> str:
    form = fitness - fatigue
    text = f"{form:+.0f}"
    if fitness:
        text += f" ({form / fitness * 100:+.0f}%)"
    return text


def _values(day: dict) -> str:
    parts = [
        f"fitness {day['ctl']:.0f}",
        f"fatigue {day['atl']:.0f}",
        f"form {_form(day['ctl'], day['atl'])}",
    ]
    if day.get("rampRate") is not None:
        parts.append(f"ramp {day['rampRate']:+.1f}")
    return " | ".join(parts)


def _daily_lines(days: list[dict]) -> list[str]:
    lines = []
    for day in days:
        line = f"📅 {day['id']}: {_values(day)}"
        if day.get("ctlLoad") is not None:
            line += f" | load {day['ctlLoad']:.0f}"
        lines.append(line)
    return lines


def _weekly_lines(days: list[dict], start: date, end: date) -> list[str]:
    weeks: dict[tuple[int, int], list[dict]] = {}
    for day in days:
        weeks.setdefault(day["date"].isocalendar()[:2], []).append(day)

    lines = []
    for (year, week), week_days in weeks.items():
        monday = date.fromisocalendar(year, week, 1)
        first, last = max(monday, start), min(monday + timedelta(days=6), end)
        partial = ", partial week" if first != monday or last != monday + timedelta(days=6) else ""
        week_load = sum(d["ctlLoad"] for d in week_days if d.get("ctlLoad") is not None)
        lines.append(
            f"📅 {year}-W{week:02d} ({first} → {last}{partial}): "
            f"{_values(week_days[-1])} | week load {week_load:.0f}"
        )
    return lines


def _summary_lines(days: list[dict]) -> list[str]:
    latest, first = days[-1], days[0]
    peak = max(days, key=lambda d: d["ctl"])
    lowest_form = min(days, key=lambda d: d["ctl"] - d["atl"])
    highest_form = max(days, key=lambda d: d["ctl"] - d["atl"])
    total_load = sum(d["ctlLoad"] for d in days if d.get("ctlLoad") is not None)

    latest_line = (
        f"   Latest ({latest['id']}): fitness {latest['ctl']:.0f}, fatigue {latest['atl']:.0f}, "
        f"form {_form(latest['ctl'], latest['atl'])}"
    )
    if latest.get("rampRate") is not None:
        latest_line += f", ramp rate {latest['rampRate']:+.1f}"
    return [
        "📊 Summary:",
        latest_line,
        f"   Fitness over the period: {first['ctl']:.0f} → {latest['ctl']:.0f} "
        f"({latest['ctl'] - first['ctl']:+.0f})",
        f"   Peak fitness: {peak['ctl']:.0f} on {peak['id']}",
        f"   Lowest form: {_form(lowest_form['ctl'], lowest_form['atl'])} on {lowest_form['id']}",
        f"   Highest form: {_form(highest_form['ctl'], highest_form['atl'])} on {highest_form['id']}",
        f"   Total load: {total_load:.0f}",
    ]


def _error(text: str) -> list[TextContent]:
    return [TextContent(type="text", text=f"❌ {text}")]


async def get_wellness_handler(arguments: dict, intervals) -> list[TextContent]:
    """Handle get_wellness tool calls."""
    try:
        if isinstance(intervals, StravaClient):
            return [TextContent(type="text", text=NO_WELLNESS_DATA_MESSAGE)]

        start_date_str = arguments.get("start_date")
        end_date_str = arguments.get("end_date")
        metrics = arguments.get("metrics") or "load"
        daily = bool(arguments.get("daily"))

        if not start_date_str or not end_date_str:
            return _error("Both start_date and end_date are required")
        if metrics not in METRICS:
            return _error(f"Unknown metrics '{metrics}'. Use one of: {', '.join(METRICS)}")

        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError as e:
            return _error(f"Invalid date format. Use YYYY-MM-DD (e.g., 2024-01-15): {e}")

        if start_date > end_date:
            return _error(f"start_date ({start_date_str}) cannot be after end_date ({end_date_str})")

        # Both ends are inclusive, so count calendar days, not the difference.
        days_in_range = (end_date - start_date).days + 1
        if days_in_range > MAX_RANGE_DAYS:
            return _error(f"Date range too large ({days_in_range} days). Maximum is {MAX_RANGE_DAYS} days.")

        records = await intervals.get_wellness(start_date_str, end_date_str, fields=LOAD_FIELDS)

        days = []
        for record in records:
            if record.get("ctl") is None or record.get("atl") is None:
                continue
            days.append({**record, "date": date.fromisoformat(record["id"])})
        days.sort(key=lambda d: d["date"])

        if not days:
            return [TextContent(
                type="text",
                text=f"No fitness/fatigue data found for the period {start_date_str} to {end_date_str}",
            )]

        lines = [
            f"Training load from {start_date_str} to {end_date_str} (source: intervals.icu)",
            "Fitness = CTL (long-term load), fatigue = ATL (short-term load), form = fitness - fatigue "
            "(TSB, with % of fitness).",
            "",
        ]
        if daily or days_in_range <= DAILY_ROWS_MAX_DAYS:
            lines.extend(_daily_lines(days))
        else:
            lines.append("One row per ISO week: values at the week's last day with data, load summed.")
            lines.extend(_weekly_lines(days, start_date, end_date))
        lines.append("")
        lines.extend(_summary_lines(days))

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        print(f"Error fetching wellness data: {e}", file=sys.stderr)
        return _error(f"Error: {str(e)}")
