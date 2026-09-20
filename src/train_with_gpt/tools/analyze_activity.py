"""Analyze activity tool."""

import sys
from mcp.types import Tool, TextContent

from ..intervals_client import IntervalsClient
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
                    "description": "The intervals.icu activity ID to analyze (from get_activities), e.g. 'i180171555'.",
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


async def analyze_activity_handler(arguments: dict, intervals: IntervalsClient) -> list[TextContent]:
    """Handle analyze_activity tool calls."""
    try:
        activity_id_raw = arguments.get("activity_id")

        if not activity_id_raw:
            return [TextContent(type="text", text="❌ Error: activity_id is required")]

        activity_id = str(activity_id_raw)

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

        # Power Zone Distribution (for cycling, or running with a power meter)
        power_zones = activity.get('icu_power_zones')
        power_zone_times = activity.get('icu_zone_times')
        if power_zones and power_zone_times:
            lines.append("## ⚡ Power Analysis\n")
            lines.append("**Zone Distribution:**")
            lines.extend(_format_zone_times(power_zones, power_zone_times, "W"))
            lines.append("")
        elif power_zones:
            # Fallback: intervals.icu hasn't precomputed power zone times for this
            # activity - bucket the raw power stream ourselves.
            streams = await intervals.get_activity_streams(activity_id, stream_types=['watts'])
            power_data = streams.get('watts', {}).get('data')
            if power_data:
                zone_boundaries = power_zones[:-1]
                zone_dist = calculate_zone_distribution(power_data, zone_boundaries)
                zone_times = [zone_dist.get(i + 1, 0) for i in range(len(power_zones))]

                lines.append("## ⚡ Power Analysis\n")
                lines.append("**Zone Distribution:**")
                lines.extend(_format_zone_times(power_zones, zone_times, "W"))
                lines.append("")

        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        print(f"Error analyzing activity: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
