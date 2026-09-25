"""Analyze a single lap split into N segments tool."""

import sys
from mcp.types import Tool, TextContent

from ..intervals_client import IntervalsClient
from ..strava_client import StravaClient

_STREAM_TYPES = ['time', 'distance', 'heartrate', 'velocity_smooth', 'cadence', 'watts']


def analyze_lap_tool() -> Tool:
    """Return the analyze_lap tool definition."""
    return Tool(
        name="analyze_lap",
        description=(
            "Splits a specific lap of an activity into a given number of equal-time segments "
            "and shows detailed metrics per segment (distance, pace/speed, heart rate, power, cadence). "
            "Useful for fine-grained analysis of a single lap or interval."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "The activity ID (from get_activities or analyze_activity).",
                },
                "lap_number": {
                    "type": "number",
                    "description": "1-based index of the lap to analyse (e.g. 1 for the first lap).",
                },
                "num_splits": {
                    "type": "number",
                    "description": "Number of equal-time segments to split the lap into (e.g. 4 for quarters).",
                },
            },
            "required": ["activity_id", "lap_number", "num_splits"],
        },
    )


async def _resolve_intervals_lap(activity_id: str, lap_number: int, intervals: IntervalsClient):
    """intervals.icu path: lap boundaries come straight off icu_intervals, no reconstruction."""
    activity = await intervals.get_activity(activity_id, intervals=True)
    activity_type = activity.get('type', 'Unknown')

    laps = activity.get('icu_intervals') or []
    if not laps:
        return None, "❌ No lap data available for this activity"
    if lap_number > len(laps):
        return None, f"❌ Error: lap_number {lap_number} exceeds total laps ({len(laps)})"

    streams = await intervals.get_activity_streams(activity_id, stream_types=_STREAM_TYPES)
    if 'time' not in streams or not streams['time'].get('data'):
        return None, "❌ No time stream data available for this activity"

    lap = laps[lap_number - 1]
    lap_start_t = lap.get('start_time', 0)
    lap_end_t = lap.get('end_time', 0)
    return (activity_type, lap_start_t, lap_end_t, streams), None


async def _resolve_strava_lap(activity_id: int, lap_number: int, strava: StravaClient):
    """Strava path: laps have no absolute start/end time - reconstruct via cumulative elapsed_time."""
    activity_details = await strava.get_activity_details(activity_id)
    activity_type = activity_details.get('sport_type') or activity_details.get('type', 'Unknown')

    laps = await strava.get_activity_laps(activity_id)
    if not laps:
        return None, "❌ No lap data available for this activity"
    if lap_number > len(laps):
        return None, f"❌ Error: lap_number {lap_number} exceeds total laps ({len(laps)})"

    streams = await strava.get_activity_streams(activity_id, stream_types=_STREAM_TYPES)
    if 'time' not in streams or not streams['time'].get('data'):
        return None, "❌ No time stream data available for this activity"

    cumulative = 0
    lap_boundaries = []
    for lap in laps:
        start = cumulative
        cumulative += lap.get('elapsed_time', 0)
        lap_boundaries.append((start, cumulative))

    lap_start_t, lap_end_t = lap_boundaries[lap_number - 1]
    return (activity_type, lap_start_t, lap_end_t, streams), None


def _render_lap_analysis(
    activity_id, lap_number: int, num_splits: int,
    activity_type: str, lap_start_t: float, lap_end_t: float, streams: dict,
) -> str:
    """Shared rendering: split [lap_start_t, lap_end_t] into num_splits equal-time windows."""
    is_running = activity_type in ['Run', 'Walk', 'Hike']

    time_data = streams['time']['data']
    lap_elapsed = lap_end_t - lap_start_t

    if lap_elapsed <= 0:
        return "❌ Error: lap has zero elapsed time"

    lap_indices = [i for i, t in enumerate(time_data) if lap_start_t <= t <= lap_end_t]
    if not lap_indices:
        return "❌ No stream data found for this lap's time range"

    split_duration = lap_elapsed / num_splits
    groups = []
    for s in range(num_splits):
        split_start = lap_start_t + s * split_duration
        split_end = lap_start_t + (s + 1) * split_duration
        if s < num_splits - 1:
            group = [i for i in lap_indices if split_start <= time_data[i] < split_end]
        else:
            group = [i for i in lap_indices if split_start <= time_data[i] <= split_end]
        groups.append(group)

    def stream_vals(key, indices):
        data = streams.get(key, {}).get('data', [])
        return [data[i] for i in indices if i < len(data) and data[i] is not None]

    lines = [
        f"🔍 Lap {lap_number} Analysis — Activity {activity_id}",
        f"Lap duration: {lap_elapsed // 60}m{lap_elapsed % 60:02d}s  |  "
        f"Split into {num_splits} segments\n",
        f"{'Split':<6} {'Distance':>10} {'Time':>8} {'Pace/Speed':>12} "
        f"{'HR min/avg/max':>18} {'Power':>8} {'Cadence':>10}",
        "-" * 80,
    ]

    dist_data = streams.get('distance', {}).get('data', [])

    for s, group in enumerate(groups, 1):
        if not group:
            continue

        first, last = group[0], group[-1]

        win_start = lap_start_t + (s - 1) * split_duration
        win_end = lap_start_t + s * split_duration
        elapsed = int(round(min(win_end, lap_end_t) - win_start))
        elapsed_str = f"{elapsed // 60}m{elapsed % 60:02d}s"

        dist_str = "—"
        if dist_data and first < len(dist_data) and last < len(dist_data):
            dist_km = (dist_data[last] - dist_data[first]) / 1000
            dist_str = f"{dist_km:.3f} km"

        pace_str = "—"
        if dist_data and first < len(dist_data) and last < len(dist_data) and elapsed > 0:
            dist_km = (dist_data[last] - dist_data[first]) / 1000
            if dist_km > 0:
                if is_running:
                    pmin_per_km = (elapsed / 60) / dist_km
                    pm = int(pmin_per_km)
                    ps = int((pmin_per_km - pm) * 60)
                    pace_str = f"{pm}:{ps:02d}/km"
                else:
                    pace_str = f"{dist_km / elapsed * 3600:.1f} km/h"
        elif not dist_data:
            vel_vals = stream_vals('velocity_smooth', group)
            if vel_vals and elapsed > 0:
                avg_vel = sum(vel_vals) / len(vel_vals)
                if not is_running:
                    pace_str = f"{avg_vel * 3.6:.1f} km/h"

        hr_str = "—"
        hr_vals = stream_vals('heartrate', group)
        if hr_vals:
            hr_str = f"{min(hr_vals)}/{int(sum(hr_vals)/len(hr_vals))}/{max(hr_vals)}"

        pwr_str = "—"
        pwr_vals = stream_vals('watts', group)
        if pwr_vals:
            pwr_str = f"{int(sum(pwr_vals)/len(pwr_vals))}W"

        cad_str = "—"
        cad_vals = stream_vals('cadence', group)
        if cad_vals:
            avg_cad = sum(cad_vals) / len(cad_vals)
            if is_running:
                cad_str = f"{int(avg_cad * 2)} spm"
            else:
                cad_str = f"{int(avg_cad)} rpm"

        lines.append(
            f"{s:<6} {dist_str:>10} {elapsed_str:>8} {pace_str:>12} "
            f"{hr_str:>18} {pwr_str:>8} {cad_str:>10}"
        )

    return "\n".join(lines)


async def analyze_lap_handler(arguments: dict, intervals) -> list[TextContent]:
    """Handle analyze_lap tool calls."""
    try:
        activity_id_raw = arguments.get("activity_id")
        lap_number_raw = arguments.get("lap_number")
        num_splits_raw = arguments.get("num_splits")

        if not activity_id_raw:
            return [TextContent(type="text", text="❌ Error: activity_id is required")]
        if not lap_number_raw:
            return [TextContent(type="text", text="❌ Error: lap_number is required")]
        if not num_splits_raw:
            return [TextContent(type="text", text="❌ Error: num_splits is required")]

        lap_number = int(lap_number_raw)
        num_splits = int(num_splits_raw)

        if lap_number < 1:
            return [TextContent(type="text", text="❌ Error: lap_number must be >= 1")]
        if num_splits < 2:
            return [TextContent(type="text", text="❌ Error: num_splits must be >= 2")]

        if isinstance(intervals, StravaClient):
            activity_id = int(activity_id_raw)
            resolved, error = await _resolve_strava_lap(activity_id, lap_number, intervals)
        else:
            activity_id = str(activity_id_raw)
            resolved, error = await _resolve_intervals_lap(activity_id, lap_number, intervals)

        if error:
            return [TextContent(type="text", text=error)]

        activity_type, lap_start_t, lap_end_t, streams = resolved
        text = _render_lap_analysis(activity_id, lap_number, num_splits, activity_type, lap_start_t, lap_end_t, streams)

        return [TextContent(type="text", text=text)]

    except Exception as e:
        print(f"Error analyzing lap: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
