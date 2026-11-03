"""Analyze activity tool."""

import sys
from mcp.types import Tool, TextContent

from ..intervals_client import IntervalsClient
from ..activity_source import strava_id_error
from ..strava_client import StravaClient
from ..helpers import calculate_zone_distribution


def analyze_activity_tool() -> Tool:
    """Return the analyze_activity tool definition."""
    return Tool(
        name="analyze_activity",
        description="Performs detailed analysis of a specific activity. Shows zone distribution, detects intervals, and provides coaching insights.",
        inputSchema={
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "string",
                    "description": "The activity ID to analyze (from get_activities).",
                },
            },
            "required": ["activity_id"],
        },
    )


def _format_zone_times(zone_boundaries: list, zone_times: list, unit: str) -> list[str]:
    """Format precomputed per-zone seconds (from intervals.icu) into display lines."""
    total = sum(zone_times) or 1
    lines = []
    for i, seconds in enumerate(zone_times):
        if not seconds or seconds <= 0:
            continue
        zone_num = i + 1
        zone_min = 0 if i == 0 else zone_boundaries[i - 1] + 1
        zone_max = zone_boundaries[i]
        zone_range = f"{zone_min}+ {unit}" if zone_max >= 999 else f"{zone_min}-{zone_max} {unit}"
        minutes = seconds // 60
        secs = seconds % 60
        percent = seconds / total * 100
        lines.append(f"  Zone {zone_num} ({zone_range}): {minutes}m{secs:02d}s ({percent:.1f}%)")
    return lines


def _power_zone_seconds(zone_times: list, zone_count: int) -> list[int]:
    """
    Seconds per power zone from intervals.icu's icu_zone_times.

    Unlike icu_hr_zone_times (plain seconds), it holds {"id": "Z1", "secs": ...}
    entries, plus extras such as the sweet-spot "SS" that aren't one of the zones.
    """
    seconds = [0] * zone_count
    for entry in zone_times:
        zone_id = str(entry.get("id", "")) if isinstance(entry, dict) else ""
        if zone_id[:1] == "Z" and zone_id[1:].isdigit() and 1 <= int(zone_id[1:]) <= zone_count:
            seconds[int(zone_id[1:]) - 1] = int(entry.get("secs") or 0)
    return seconds


def _zone_watts(percent_of_ftp, ftp) -> int:
    """A %-of-FTP zone limit in whole watts (used for both bucketing and labels)."""
    return round(percent_of_ftp * ftp / 100)


def _format_power_zone_times(zone_percents: list, zone_times: list, ftp) -> list[str]:
    """Like _format_zone_times, but icu_power_zones are % of FTP: show both % and watts."""
    total = sum(zone_times) or 1
    lines = []
    for i, seconds in enumerate(zone_times):
        if not seconds or seconds <= 0:
            continue
        pct_min = 0 if i == 0 else zone_percents[i - 1] + 1
        pct_max = zone_percents[i]
        is_top = pct_max >= 999
        zone_range = f"{pct_min}%+ FTP" if is_top else f"{pct_min}-{pct_max}% FTP"
        if ftp:
            watts_min = 0 if i == 0 else _zone_watts(zone_percents[i - 1], ftp) + 1
            watts_max = _zone_watts(pct_max, ftp)
            zone_range += f", {watts_min}+ W" if is_top else f", {watts_min}-{watts_max} W"
        percent = seconds / total * 100
        lines.append(f"  Zone {i + 1} ({zone_range}): {seconds // 60}m{seconds % 60:02d}s ({percent:.1f}%)")
    return lines


async def _power_zone_lines(activity: dict, activity_id: str, intervals: IntervalsClient) -> list[str]:
    power_zones = activity.get('icu_power_zones')
    if not power_zones:
        return []
    ftp = activity.get('icu_ftp')

    power_zone_times = activity.get('icu_zone_times')
    if power_zone_times:
        zone_times = _power_zone_seconds(power_zone_times, len(power_zones))
    elif ftp:
        # Not precomputed: bucket the raw power stream ourselves, with the
        # %-of-FTP limits turned into watts first.
        streams = await intervals.get_activity_streams(activity_id, stream_types=['watts'])
        power_data = streams.get('watts', {}).get('data')
        if not power_data:
            return []
        # The same rounded limits the zone labels show, so a reading lands in the zone it's displayed in.
        watt_boundaries = [_zone_watts(pct, ftp) for pct in power_zones[:-1]]
        zone_dist = calculate_zone_distribution(power_data, watt_boundaries)
        zone_times = [zone_dist.get(i + 1, 0) for i in range(len(power_zones))]
    else:
        return []

    zone_lines = _format_power_zone_times(power_zones, zone_times, ftp)
    if not zone_lines:
        return []
    return ["## ⚡ Power Analysis\n", "**Zone Distribution:**", *zone_lines, ""]


async def _analyze_activity_intervals(activity_id: str, intervals: IntervalsClient) -> str:
    """intervals.icu path: zones, per-lap stats, and HR zone-times all come precomputed."""
    activity = await intervals.get_activity(activity_id, intervals=True)
    activity_type = activity.get('type', 'Unknown')
    is_running = activity_type in ['Run', 'Walk', 'Hike']

    lines = [f"🔍 Detailed Analysis for Activity {activity_id}\n"]

    icu_intervals = activity.get('icu_intervals') or []

    # Laps / Intervals Analysis
    if icu_intervals and len(icu_intervals) > 1:
        lines.append("## 🏁 Laps / Intervals")
        lines.append("(Distance | Time | Pace/Speed | Heart Rate min/avg/max | Power | Cadence)\n")

        for i, lap in enumerate(icu_intervals, 1):
            lap_stats = []

            # Distance
            distance = (lap.get('distance') or 0) / 1000  # meters to km
            if distance > 0:
                lap_stats.append(f"{distance:.2f}km")

            # Time
            elapsed = int(lap.get('moving_time') or lap.get('elapsed_time') or 0)
            if elapsed > 0:
                minutes = elapsed // 60
                seconds = elapsed % 60
                lap_stats.append(f"{minutes}m{seconds:02d}s")

            # Pace/Speed
            avg_speed = lap.get('average_speed')
            if avg_speed and distance > 0 and elapsed > 0:
                if is_running:
                    pace_min_per_km = (elapsed / 60) / distance
                    pace_min = int(pace_min_per_km)
                    pace_sec = int((pace_min_per_km - pace_min) * 60)
                    lap_stats.append(f"⏱️ {pace_min}:{pace_sec:02d}/km")
                else:
                    speed_kmh = avg_speed * 3.6
                    lap_stats.append(f"⏱️ {speed_kmh:.1f}km/h")

            # Heart Rate - already precomputed per-lap by intervals.icu
            min_hr = lap.get('min_heartrate')
            avg_hr = lap.get('average_heartrate')
            max_hr = lap.get('max_heartrate')

            if avg_hr:
                hr_parts = []
                if min_hr:
                    hr_parts.append(f"min:{min_hr:.0f}")
                hr_parts.append(f"avg:{avg_hr:.0f}")
                if max_hr:
                    hr_parts.append(f"max:{max_hr:.0f}")
                lap_stats.append(f"❤️ {'/'.join(hr_parts)} bpm")

            # Power
            avg_watts = lap.get('average_watts')
            if avg_watts:
                lap_stats.append(f"⚡ {avg_watts:.0f}W")

            # Cadence
            avg_cadence = lap.get('average_cadence')
            if avg_cadence:
                if is_running:
                    cadence_value = avg_cadence * 2  # intervals.icu returns strides/min
                    lap_stats.append(f"🔄 {cadence_value:.0f} spm")
                else:
                    lap_stats.append(f"🔄 {avg_cadence:.0f} rpm")

            # Format lap line
            lap_stats_str = " | ".join(lap_stats)
            lines.append(f"  Lap {i}: {lap_stats_str}")

        lines.append("")
    elif icu_intervals and len(icu_intervals) == 1:
        lines.append("## ℹ️ Lap Information\n")
        lines.append("This activity has only one lap (no interval structure detected).\n")
    else:
        lines.append("## ℹ️ Lap Information\n")
        lines.append("No lap data available for this activity. The device may not have recorded laps.\n")

    # Heart Rate Zone Distribution - precomputed by intervals.icu
    hr_zones = activity.get('icu_hr_zones')
    hr_zone_times = activity.get('icu_hr_zone_times')
    if hr_zones and hr_zone_times:
        lines.append("## ❤️ Heart Rate Zone Distribution\n")
        lines.extend(_format_zone_times(hr_zones, hr_zone_times, "bpm"))
        lines.append("")

    # Power Zone Distribution (for cycling, or running with a power meter).
    # Read on its own: an unexpected power field must not hide laps and HR zones.
    try:
        lines.extend(await _power_zone_lines(activity, activity_id, intervals))
    except Exception as e:
        print(f"Error reading power zones for {activity_id}: {e}", file=sys.stderr)
        lines.append("## ⚡ Power Analysis\n")
        lines.append("⚠️ Couldn't read the power zones for this activity.\n")

    return "\n".join(lines)


async def _analyze_activity_strava(activity_id: int, strava: StravaClient) -> str:
    """Strava path: no precomputed zones/intervals - reconstruct from zones + streams + laps."""
    zones_data = await strava.get_athlete_zones()

    activity_details = await strava.get_activity_details(activity_id)
    activity_type = activity_details.get('sport_type') or activity_details.get('type', 'Unknown')
    is_running = activity_type in ['Run', 'Walk', 'Hike']

    streams = await strava.get_activity_streams(activity_id)
    laps = await strava.get_activity_laps(activity_id)

    lines = [f"🔍 Detailed Analysis for Activity {activity_id}\n"]

    has_hr = 'heartrate' in streams and streams['heartrate'].get('data')
    has_power = 'watts' in streams and streams['watts'].get('data')
    has_time = 'time' in streams and streams['time'].get('data')

    if not has_time:
        return "❌ No time stream data available for this activity"

    time_data = streams['time']['data']
    total_time = time_data[-1] if time_data else 0

    # Laps Analysis
    if laps and len(laps) > 1:
        lines.append("## 🏁 Laps / Intervals")
        lines.append("(Distance | Time | Pace/Speed | Heart Rate min/avg/max | Power | Cadence)\n")

        lap_end_times = []
        cumulative_time = 0
        for lap in laps:
            cumulative_time += lap.get('elapsed_time', 0)
            lap_end_times.append(cumulative_time)

        for i, lap in enumerate(laps, 1):
            lap_stats = []

            distance = lap.get('distance', 0) / 1000
            if distance > 0:
                lap_stats.append(f"{distance:.2f}km")

            elapsed = lap.get('elapsed_time', 0)
            if elapsed > 0:
                minutes = elapsed // 60
                seconds = elapsed % 60
                lap_stats.append(f"{minutes}m{seconds:02d}s")

            avg_speed = lap.get('average_speed')
            if avg_speed and distance > 0:
                if is_running:
                    pace_min_per_km = (elapsed / 60) / distance
                    pace_min = int(pace_min_per_km)
                    pace_sec = int((pace_min_per_km - pace_min) * 60)
                    lap_stats.append(f"⏱️ {pace_min}:{pace_sec:02d}/km")
                else:
                    speed_kmh = avg_speed * 3.6
                    lap_stats.append(f"⏱️ {speed_kmh:.1f}km/h")

            # Heart Rate - Strava doesn't always give min/max per lap; reconstruct from streams
            min_hr = lap.get('min_heartrate')
            avg_hr = lap.get('average_heartrate')
            max_hr = lap.get('max_heartrate')

            if has_hr and (not min_hr or not max_hr):
                hr_data = streams['heartrate']['data']
                lap_start_time = lap_end_times[i - 2] if i > 1 else 0
                lap_end_time = lap_end_times[i - 1]

                lap_hr_values = []
                for j, t in enumerate(time_data):
                    if lap_start_time <= t <= lap_end_time and j < len(hr_data):
                        if hr_data[j]:
                            lap_hr_values.append(hr_data[j])

                if lap_hr_values:
                    if not min_hr:
                        min_hr = min(lap_hr_values)
                    if not max_hr:
                        max_hr = max(lap_hr_values)

            if avg_hr:
                hr_parts = []
                if min_hr:
                    hr_parts.append(f"min:{min_hr:.0f}")
                hr_parts.append(f"avg:{avg_hr:.0f}")
                if max_hr:
                    hr_parts.append(f"max:{max_hr:.0f}")
                lap_stats.append(f"❤️ {'/'.join(hr_parts)} bpm")

            avg_watts = lap.get('average_watts')
            if avg_watts:
                lap_stats.append(f"⚡ {avg_watts:.0f}W")

            avg_cadence = lap.get('average_cadence')
            if avg_cadence:
                if is_running:
                    cadence_value = avg_cadence * 2  # Strava returns strides/min
                    lap_stats.append(f"🔄 {cadence_value:.0f} spm")
                else:
                    lap_stats.append(f"🔄 {avg_cadence:.0f} rpm")

            lap_stats_str = " | ".join(lap_stats)
            lines.append(f"  Lap {i}: {lap_stats_str}")

        lines.append("")
    elif laps and len(laps) == 1:
        lines.append("## ℹ️ Lap Information\n")
        lines.append("This activity has only one lap (no interval structure detected).\n")
    else:
        lines.append("## ℹ️ Lap Information\n")
        lines.append("No lap data available for this activity. The device may not have recorded laps.\n")

    # Heart Rate Analysis
    if has_hr and zones_data.get('heart_rate'):
        hr_data = streams['heartrate']['data']
        hr_zones = zones_data['heart_rate'].get('zones', [])

        lines.append("## ❤️ Heart Rate Zone Distribution\n")

        if hr_zones:
            zone_boundaries = [z.get('max', 0) for z in hr_zones[:-1]]
            zone_dist = calculate_zone_distribution(hr_data, zone_boundaries)
            total_points = sum(zone_dist.values())

            for zone_num in sorted(zone_dist.keys()):
                time_in_zone = zone_dist[zone_num]
                if time_in_zone > 0:
                    percent = (time_in_zone / total_points * 100) if total_points > 0 else 0
                    actual_seconds = int(time_in_zone * (total_time / len(hr_data))) if hr_data else 0
                    minutes = actual_seconds // 60
                    seconds = actual_seconds % 60

                    if zone_num <= len(hr_zones):
                        zone_info = hr_zones[zone_num - 1]
                        zone_min = zone_info.get('min', 0)
                        zone_max = zone_info.get('max', -1)
                        zone_range = f"{zone_min}+ bpm" if zone_max == -1 else f"{zone_min}-{zone_max} bpm"
                    else:
                        zone_range = "above zones"

                    lines.append(f"  Zone {zone_num} ({zone_range}): {minutes}m{seconds:02d}s ({percent:.1f}%)")

        lines.append("")

    # Power Analysis (for cycling)
    if has_power and zones_data.get('power'):
        power_data = streams['watts']['data']
        power_zones = zones_data['power'].get('zones', [])

        lines.append("## ⚡ Power Analysis\n")

        if power_zones:
            zone_boundaries = [z.get('max', 0) for z in power_zones[:-1]]
            zone_dist = calculate_zone_distribution(power_data, zone_boundaries)

            lines.append("**Zone Distribution:**")
            for zone_num in sorted(zone_dist.keys()):
                time_in_zone = zone_dist[zone_num]
                if time_in_zone > 0:
                    percent = (time_in_zone / total_time * 100) if total_time > 0 else 0
                    minutes = time_in_zone // 60
                    seconds = time_in_zone % 60

                    if zone_num <= len(power_zones):
                        zone_info = power_zones[zone_num - 1]
                        zone_min = zone_info.get('min', 0)
                        zone_max = zone_info.get('max', '∞')
                        zone_range = f"{zone_min}-{zone_max}W"
                    else:
                        zone_range = "above zones"

                    lines.append(f"  Zone {zone_num} ({zone_range}): {minutes}m{seconds:02d}s ({percent:.1f}%)")

        lines.append("")

    return "\n".join(lines)


async def analyze_activity_handler(arguments: dict, intervals) -> list[TextContent]:
    """Handle analyze_activity tool calls."""
    try:
        activity_id_raw = arguments.get("activity_id")

        if not activity_id_raw:
            return [TextContent(type="text", text="❌ Error: activity_id is required")]

        if isinstance(intervals, StravaClient):
            id_error = strava_id_error(activity_id_raw)
            if id_error:
                return [TextContent(type="text", text=id_error)]
            text = await _analyze_activity_strava(int(activity_id_raw), intervals)
        else:
            text = await _analyze_activity_intervals(str(activity_id_raw), intervals)

        return [TextContent(type="text", text=text)]

    except Exception as e:
        print(f"Error analyzing activity: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
