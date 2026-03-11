"""Analyze activity tool."""

import sys
from mcp.types import Tool, TextContent

from ..strava_client import StravaClient
from ..helpers import calculate_zone_distribution


def analyze_activity_tool() -> Tool:
    """Return the analyze_activity tool definition."""
    return Tool(
        name="analyze_activity",
        description="Performs detailed analysis of a specific activity using stream data. Shows zone distribution, detects intervals, and provides coaching insights.",
        inputSchema={
            "type": "object",
            "properties": {
                "activity_id": {
                    "type": "number",
                    "description": "The Strava activity ID to analyze (from get_last_week_activities)",
                },
            },
            "required": ["activity_id"],
        },
    )


async def analyze_activity_handler(arguments: dict, strava: StravaClient) -> list[TextContent]:
    """Handle analyze_activity tool calls."""
    try:
        # Handle both string and number inputs
        activity_id_raw = arguments.get("activity_id")
        activity_id = int(activity_id_raw) if activity_id_raw else None
        
        if not activity_id:
            return [TextContent(type="text", text="❌ Error: activity_id is required")]
        
        # Fetch zones
        zones_data = await strava.get_athlete_zones()
        
        # Fetch streams and laps
        streams = await strava.get_activity_streams(activity_id)
        laps = await strava.get_activity_laps(activity_id)
        
        # Build analysis report
        lines = [f"🔍 Detailed Analysis for Activity {activity_id}\n"]
        
        # Check what data we have
        has_hr = 'heartrate' in streams and streams['heartrate'].get('data')
        has_power = 'watts' in streams and streams['watts'].get('data')
        has_time = 'time' in streams and streams['time'].get('data')
        
        if not has_time:
            return [TextContent(type="text", text="❌ No time stream data available for this activity")]
        
        time_data = streams['time']['data']
        total_time = time_data[-1] if time_data else 0
        
        # Laps Analysis
        if laps and len(laps) > 1:  # More than 1 lap means intervals/structured workout
            lines.append("## 🏁 Laps / Intervals")
            lines.append("(Distance | Time | Pace/Speed | Heart Rate min/avg/max | Power | Cadence)\n")
            
            # Calculate cumulative lap times for stream data lookup
            lap_end_times = []
            cumulative_time = 0
            for lap in laps:
                cumulative_time += lap.get('elapsed_time', 0)
                lap_end_times.append(cumulative_time)
            
            for i, lap in enumerate(laps, 1):
                lap_stats = []
                
                # Distance
                distance = lap.get('distance', 0) / 1000  # meters to km
                if distance > 0:
                    lap_stats.append(f"{distance:.2f}km")
                
                # Time
                elapsed = lap.get('elapsed_time', 0)
                if elapsed > 0:
                    minutes = elapsed // 60
                    seconds = elapsed % 60
                    lap_stats.append(f"{minutes}m{seconds:02d}s")
                
                # Pace/Speed
                avg_speed = lap.get('average_speed')
                if avg_speed and distance > 0:
                    # Determine activity type - use 6.0 m/s (21.6 km/h) as threshold
                    if avg_speed < 6.0:  # Likely running
                        pace_min_per_km = (elapsed / 60) / distance
                        pace_min = int(pace_min_per_km)
                        pace_sec = int((pace_min_per_km - pace_min) * 60)
                        lap_stats.append(f"⏱️ {pace_min}:{pace_sec:02d}/km")
                    else:  # Likely cycling
                        speed_kmh = avg_speed * 3.6
                        lap_stats.append(f"⏱️ {speed_kmh:.1f}km/h")
                
                # Heart Rate - calculate min/max from streams if not in lap data
                min_hr = lap.get('min_heartrate')
                avg_hr = lap.get('average_heartrate')
                max_hr = lap.get('max_heartrate')
                
                # If we don't have min/max from lap data, calculate from streams
                if has_hr and (not min_hr or not max_hr):
                    hr_data = streams['heartrate']['data']
                    lap_start_time = lap_end_times[i-2] if i > 1 else 0
                    lap_end_time = lap_end_times[i-1]
                    
                    # Find HR values within this lap's time range
                    lap_hr_values = []
                    for j, t in enumerate(time_data):
                        if lap_start_time <= t <= lap_end_time and j < len(hr_data):
                            if hr_data[j]:  # Skip None values
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
                
                # Power
                avg_watts = lap.get('average_watts')
                if avg_watts:
                    lap_stats.append(f"⚡ {avg_watts:.0f}W")
                
                # Cadence
                avg_cadence = lap.get('average_cadence')
                if avg_cadence:
                    # Check if running or cycling based on speed (6.0 m/s = ~21.6 km/h)
                    if avg_speed and avg_speed < 6.0:  # Running
                        cadence_value = avg_cadence * 2  # Strava returns strides/min
                        lap_stats.append(f"🔄 {cadence_value:.0f} spm")
                    else:  # Cycling
                        lap_stats.append(f"🔄 {avg_cadence:.0f} rpm")
                
                # Format lap line
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
            
            # Get zone boundaries
            if hr_zones:
                zone_boundaries = [z.get('max', 0) for z in hr_zones[:-1]]  # Exclude last zone (no upper bound)
                
                # Calculate distribution
                zone_dist = calculate_zone_distribution(hr_data, zone_boundaries)
                
                # Total time based on actual data points (streams are sampled, not every second)
                total_points = sum(zone_dist.values())
                
                for zone_num in sorted(zone_dist.keys()):
                    time_in_zone = zone_dist[zone_num]
                    if time_in_zone > 0:
                        percent = (time_in_zone / total_points * 100) if total_points > 0 else 0
                        # Convert to actual time using the sampling rate
                        actual_seconds = int(time_in_zone * (total_time / len(hr_data)))
                        minutes = actual_seconds // 60
                        seconds = actual_seconds % 60
                        
                        # Get zone name and range
                        if zone_num <= len(hr_zones):
                            zone_info = hr_zones[zone_num - 1]
                            zone_min = zone_info.get('min', 0)
                            zone_max = zone_info.get('max', -1)
                            
                            # Handle highest zone (no upper bound)
                            if zone_max == -1:
                                zone_range = f"{zone_min}+ bpm"
                            else:
                                zone_range = f"{zone_min}-{zone_max} bpm"
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
        
        return [TextContent(type="text", text="\n".join(lines))]
    
    except Exception as e:
        print(f"Error analyzing activity: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]
