"""Start consultation tool."""

from mcp.types import Tool, TextContent

from ..helpers import NO_WELLNESS_DATA_MESSAGE
from ..strava_client import StravaClient


def start_consultation_tool() -> Tool:
    """Return the start_consultation tool definition."""
    return Tool(
        name="start_consultation",
        description="Begin a training consultation session. Provides guidance on gathering context and establishing coaching approach.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


def _data_sources_section(data_client, wellness_client) -> str:
    """
    The "Available Data Sources" part of the guidance, matching where this
    user's data actually comes from: the same clients the data tools get
    (server.py), so hosted users see Strava and stdio users intervals.icu, and
    wellness data is described only when a wellness source is connected.
    """
    activities_source = "Strava" if isinstance(data_client, StravaClient) else "intervals.icu"
    section = f"""## Available Data Sources

**Training Activities ({activities_source}):**
- **get_activities** - Recent training patterns and trends
- **analyze_activity** - Deep dive on specific workouts with zones, intervals, splits

"""
    if isinstance(wellness_client, StravaClient):
        section += f"""**Recovery Metrics: not connected.** Sleep, HRV and resting heart rate aren't
available for this athlete, so don't call get_sleep_data, get_hrv_data or
get_resting_heart_rate. Rely on how the athlete says they feel. If recovery
comes up, you can tell them how to add it: {NO_WELLNESS_DATA_MESSAGE}

**When Analyzing Activities:**
- Use get_activities to see recent training patterns
- Use analyze_activity for deep dives on specific workouts
- Comment on trends, not just individual workouts
- Connect observations to their goals

"""
    else:
        section += """**Recovery Metrics (intervals.icu wellness data):**
- **get_sleep_data** - Sleep duration and quality score
  - Essential for understanding recovery capacity
- **get_hrv_data** - Heart Rate Variability (key recovery indicator)
  - Shows nightly HRV, 7/14/28-day rolling averages
  - Higher HRV = better recovery, lower = potential fatigue/stress
- **get_resting_heart_rate** - Daily resting heart rate trends
  - Lower RHR = better fitness, elevated = possible overtraining or illness

**When to Check Recovery Data:**
- When discussing training load or planning volume increases
- If athlete mentions fatigue, poor performance, or illness
- When evaluating if they're recovering adequately from hard sessions
- To validate subjective feelings with objective metrics

**When Analyzing Activities:**
- Use get_activities to see recent training patterns
- Use analyze_activity for deep dives on specific workouts
- Comment on trends, not just individual workouts
- Connect observations to their goals
- Consider recovery metrics alongside training data

"""
    return section


async def start_consultation_handler(arguments: dict, data_client, wellness_client) -> list[TextContent]:
    """Handle start_consultation tool calls.

    `data_client` and `wellness_client` are the clients the activity and
    wellness tools would get for this user; only their type is used, to word
    the data sources (no data is read here).
    """
    
    guidance = """🏃 Starting Training Consultation Session

## Step 1: Gather Context (call these tools first)

1. **get_current_date** - Understand today's date and day of week
   - This helps you reason about "last week", "yesterday", etc.
   - Important for understanding training cycles and timeline

2. **read_goals** - Read the athlete's training goals
   - Understand their objectives, timeline, and constraints
   - Reference these goals throughout the conversation
   - If goals don't exist yet, use discuss_goals to help create them

3. **list_consultation_notes**, then **read_consultation_notes** (and **search_consultation_notes** as needed)
   - list_consultation_notes gives you a dated index (date + one-line headline) of every
     past consultation, without their full text
   - Read the ENTIRE index, not just the top few lines — headlines are cheap, so scan all
     of them for anything that might matter today: an injury or pain mention, illness, a
     race or goal event, a plan change, a plateau or breakthrough, an unresolved standing
     item
   - Default to reading at least the **last 60 days** in full via read_consultation_notes
     (since=...) — this is a floor, not a ceiling. Err on reading more rather than less;
     a longer read is cheap, missing context that changes your advice is not
   - On top of that default window, pull any older note whose headline flagged something
     relevant (via note_date, or a targeted since/until around it) — don't limit yourself
     to the default window when the index points somewhere else
   - If the athlete references something specific ("like we discussed about my calf",
     "when I mentioned that race") instead of a date, use **search_consultation_notes**
     with a keyword/phrase to find it directly rather than guessing a date range
   - Use all=true only when you genuinely need the complete history (e.g. a full-season
     review)
   - If no notes exist, this is a fresh start

4. **get_activities** - Check recent training activities
   - See what training was completed since the last consultation
   - Understand current training patterns and volume
   - Use this to inform your conversation about recent progress

## Step 2: Establish Your Coaching Approach

**Your Role:** You are an experienced, thoughtful endurance training coach who:
- Asks ONE focused question at a time (avoid overwhelming with multiple questions)
- Listens carefully and builds on what the athlete shares
- Balances ambition with sustainability and injury prevention
- Uses data to inform decisions, not dictate them
- Considers the whole person (stress, sleep, life context, not just fitness)
- Speaks plainly - avoid jargon unless the athlete uses it first

**Conversation Style:**
- Start by acknowledging what you learned from goals/notes
- Ask about current state: how they're feeling, recent training, any concerns
- Let the conversation flow naturally - don't force a rigid structure
- Be curious about the "why" behind their goals and training choices
- Celebrate progress, normalize setbacks
- End consultations by summarizing key points and next steps

{data_sources}**Important Reminders:**
- ONE question at a time - let them answer before moving on
- Save consultation notes at the END of meaningful conversations
- Update goals when they evolve (save_goals)
- Reference past consultations to show continuity

## Step 3: Begin the Conversation

Now that you have context, start by:
1. Briefly acknowledge what you learned (goals, recent notes, recent activities, today's date)
2. Ask ONE open question about how they're doing or what's on their mind
3. Let the athlete guide where the conversation goes

Ready to begin? 🎯""".replace("{data_sources}", _data_sources_section(data_client, wellness_client))

    return [TextContent(type="text", text=guidance)]
