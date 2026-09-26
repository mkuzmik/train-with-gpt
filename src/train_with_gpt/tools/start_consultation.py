"""Start consultation tool: the single entry point for every training conversation.

It returns what the server knows about the caller (saved goals, consultation
notes, connected data sources) plus guidance for both paths - onboarding a new
athlete, or a consultation with a returning one - and leaves the choice to the
model, which also sees the athlete's message.
"""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mcp.types import Tool, TextContent

from ..config import config
from ..helpers import (
    NO_WELLNESS_DATA_MESSAGE,
    current_user_id,
    git_pull_and_read,
    user_scoped_goals_file,
    user_scoped_notes_dir,
)
from ..strava_client import StravaClient


def start_consultation_tool() -> Tool:
    """Return the start_consultation tool definition."""
    return Tool(
        name="start_consultation",
        description=(
            "Call this first in any training conversation. It works for a brand-new athlete "
            "(introduces the tool, sets up their goals) and for a returning one (a coaching "
            "consultation). Returns what the server knows about this athlete - whether goals "
            "and consultation notes are saved, which data sources are connected - and guidance "
            "for both paths; decide which one fits from those facts and the athlete's message."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


# --- Facts about the caller ---------------------------------------------------------

@dataclass
class TrainingHistory:
    """What the training repo holds for the current user (our own storage only;
    no activity data). `storage` is "ok", "not_configured", "missing" or "error"."""
    storage: str
    has_goals: bool = False
    notes_count: int = 0
    latest_note: Optional[str] = None  # YYYY-MM-DD
    note: Optional[str] = None  # sync note or error detail for the model
    synced: bool = True  # False: the facts come from a clone that couldn't be synced


def _sync_failed(sync_note: Optional[str]) -> bool:
    """git_pull_and_read reports a failed fetch or rebase as a "(Note: ...)"
    and still reads the local clone. Its other notes (pulled updates, or local
    edits set aside) come after a successful sync."""
    return bool(sync_note) and any(part.startswith("(Note:") for part in sync_note.split("\n\n"))


def _goals_and_note_dates(goals_file: Path, notes_dir: Path) -> tuple[bool, list[str]]:
    """Whether the goals file exists, and the notes' dates (newest first), from
    file names only - no note is read."""
    stems = sorted((p.stem for p in notes_dir.glob("*.md")), reverse=True) if notes_dir.exists() else []
    return goals_file.exists(), [stem[:10] for stem in stems]


def read_training_history(user_id: Optional[str]) -> TrainingHistory:
    """Sync the training repo and look up `user_id`'s goals and notes (blocking)."""
    if not config.training_repo_path:
        return TrainingHistory(storage="not_configured")
    repo_path = Path(config.training_repo_path)
    if not repo_path.exists():
        return TrainingHistory(storage="missing", note=f"Training repository path no longer exists: {repo_path}")
    if not (repo_path / ".git").exists():
        # Same check as setup_training_repo: the save tools need a git repo.
        return TrainingHistory(storage="error", note=f"Not a git repository: {repo_path}")
    try:
        goals_file, _ = user_scoped_goals_file(repo_path, user_id)
        notes_dir, _ = user_scoped_notes_dir(repo_path, user_id)
        sync_note, (has_goals, dates) = git_pull_and_read(
            repo_path, lambda: _goals_and_note_dates(goals_file, notes_dir)
        )
    except Exception as e:  # never let a storage problem block the conversation
        print(f"Error reading training history: {e}", file=sys.stderr)
        return TrainingHistory(storage="error", note=str(e))
    return TrainingHistory(
        storage="ok",
        has_goals=has_goals,
        notes_count=len(dates),
        latest_note=dates[0] if dates else None,
        note=sync_note,
        synced=not _sync_failed(sync_note),
    )


_PULLED_UPDATES = "Pulled updates from the remote"


def _sync_fact(sync_note: Optional[str], hosted: bool) -> Optional[str]:
    """What to say about the repo sync. The "Pulled updates" summary lists every
    changed path in the (shared) repo - other users' goal/note files on the
    hosted server - and isn't needed for the facts, so it's dropped. Warnings
    stay, as a generic line for hosted users (they may name other users'
    commits or paths) and verbatim on the personal path."""
    if not sync_note:
        return None
    warnings = [part for part in sync_note.split("\n\n") if part and not part.startswith(_PULLED_UPDATES)]
    if not warnings:
        return None
    if hosted:
        return "the notes storage couldn't be fully synced just now, so the goals/notes facts may be slightly out of date"
    return " ".join(warnings)


def _facts_section(data_client, wellness_client, history: TrainingHistory, hosted: bool) -> str:
    activities = "Strava" if isinstance(data_client, StravaClient) else "intervals.icu"
    wellness = (
        "not connected" if isinstance(wellness_client, StravaClient)
        else "connected (intervals.icu)"
    )
    lines = [
        f"- **Activities source:** {activities}",
        f"- **Recovery data (sleep, HRV, resting HR):** {wellness}",
    ]
    if history.storage == "ok":
        lines.append("- **Notes storage:** set up")
        lines.append(f"- **Saved goals:** {'yes' if history.has_goals else 'none'}")
        if history.notes_count:
            lines.append(
                f"- **Consultation notes:** {history.notes_count}, most recent {history.latest_note}"
            )
        else:
            lines.append("- **Consultation notes:** none")
        sync = _sync_fact(history.note, hosted)
        if sync:
            lines.append(f"- **Sync:** {sync}")
    else:
        if history.storage == "not_configured":
            status = "not set up on this server"
        else:
            status = f"unavailable ({history.note})"
        if hosted:
            fix = "it's configured by whoever runs the server, so tell the athlete to contact the server's operator if they want their goals and notes kept"
        else:
            fix = "if the athlete wants goals and notes kept between chats, offer to run **setup_training_repo**"
        lines.append(
            f"- **Notes storage:** {status}. Saved goals and notes can't be checked, read or saved "
            f"in this chat, so don't call the goals/notes tools; {fix}."
        )
    return "## What the server knows about this athlete\n\n" + "\n".join(lines) + "\n\n"


def _choose_path_section(history: TrainingHistory) -> str:
    if history.storage != "ok":
        hint = (
            "**Here the server can't tell** (no notes storage), so go by the athlete's message; "
            "if it doesn't say, ask ONE question: is this their first time using this coach, or "
            "have you worked together before? Either way nothing can be saved this chat."
        )
    elif not history.synced:
        hint = (
            "**Here the notes storage couldn't be synced just now**, so the goals/notes facts come "
            "from a possibly out-of-date copy and may miss what was saved from another device. "
            "Don't treat them as final: if they show no history, ask ONE question (first time "
            "with this coach, or worked together before?) before onboarding; if they show "
            "history, it's a returning athlete (Path B)."
        )
    elif not history.has_goals and not history.notes_count:
        hint = "**Here: no goals and no notes, so this looks like a NEW athlete** (Path A)."
    elif history.notes_count and history.has_goals:
        hint = "**Here: goals and notes are saved, so this is a RETURNING athlete** (Path B)."
    elif history.notes_count:
        hint = (
            "**Here: notes exist but no goals, so this is a RETURNING athlete without goals** "
            "(Path B; offer the goal-setting conversation early on)."
        )
    else:
        hint = (
            "**Here: goals are saved but there are no consultation notes yet - ambiguous.** "
            "They may have set goals and never had a consultation, or be picking up an "
            "unfinished first session. Read the goals, then briefly ask the athlete whether "
            "they want to pick up where they left off or first hear what the coach can do; "
            "either way stay in Path B and build on the saved goals."
        )
    return f"""## Step 1: Choose the path

You decide which path fits, from the facts above and what the athlete wrote:

- **Path A - New athlete (onboarding):** only when there are no saved goals and no notes
  (the facts decide this, not the athlete's wording). When storage is unavailable the
  facts can't tell, so an athlete who says they're new ("set me up", "first time")
  goes here.
- **Path B - Returning athlete (consultation):** any saved goals or notes, even if the
  athlete says "set me up" or "I'm new" - greet them as returning and mention what's
  saved. If they want to know what the coach can do, explain it within Path B.
- An athlete with saved history is never onboarded from scratch. If they ask to
  "start over" or set completely new goals, explicitly confirm first that saving new
  goals replaces the old ones, and only then run the goal-setting conversation.
- If the athlete's message clearly asks for something specific (e.g. "update my
  goals", "how was yesterday's run?"), do that within the matching path.
- If it's genuinely unclear, ask ONE short question rather than guessing.

{hint}

"""


# --- Guidance ------------------------------------------------------------------------

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


_COACHING_APPROACH = """## Step 2: Your Coaching Approach (both paths)

**Your Role:** You are an experienced, thoughtful endurance training coach who:
- Asks ONE focused question at a time (avoid overwhelming with multiple questions)
- Listens carefully and builds on what the athlete shares
- Balances ambition with sustainability and injury prevention
- Uses data to inform decisions, not dictate them
- Considers the whole person (stress, sleep, life context, not just fitness)
- Speaks plainly - avoid jargon unless the athlete uses it first

**Conversation Style:**
- Let the conversation flow naturally - don't force a rigid structure
- Be curious about the "why" behind their goals and training choices
- Celebrate progress, normalize setbacks
- End by summarizing key points and next steps

"""


_PATH_A = """## Path A: Onboarding a New Athlete

Only for an athlete with no saved goals or notes (see Step 1).

1. **get_current_date**, then **get_activities** for roughly the last 2-4 weeks, so
   you open with something concrete about their recent training.
2. **Introduce yourself briefly** (a few sentences, not a feature list): you coach
   from their recent activities, you remember their goals and past consultations
   between chats (when notes storage is set up), and you can dig into any single
   workout. Mention recovery data only as connected or not, per the facts above.
3. **Set their goals** with the goal-setting conversation below, one question at a
   time, then **save_goals**.
4. **Close the first session:** summarize, save a short note with
   **save_consultation_notes** (what you learned, and anything still to ask), and
   explain the routine: start each chat with "start a consultation", say "save
   notes" at the end of a useful one, and "update my goals" when things change.

If the athlete stops partway, still save a note listing what's done and what's
pending, so the next session can pick it up.

"""


_GOAL_SETTING = """## Goal-Setting Conversation (Path A, or Path B when goals are missing or changing)

**ASK ONE QUESTION AT A TIME.** This is a conversation, not an interview. Look at
their recent activities first (get_activities) so you can reference them.

**Topics to cover:**
1. **Primary goal** - what they're training for (event, race, milestone, or "no
   event, general fitness" - both are fine), specific target, date, and why it
   matters to them
2. **Current fitness** - recent benchmarks (check their activities first!),
   current volume, training background and experience
3. **Constraints & context** - time per week, injury history or limitations, life
   commitments, training environment/equipment
4. **Secondary priorities** - staying healthy, enjoying the process, balance with
   life, other fitness goals

❌ BAD (multiple questions):
"What race are you training for? What's your target time? When is the race? Do you have any injuries?"

✅ GOOD (one at a time):
Athlete: "I want to set some training goals"
You: "I can see from your recent activities that you're running consistently. What are you training for?"
Athlete: "A 5k race in March"
You: "Great! Do you have a specific time goal in mind?"

**Then** write a clear, natural-language summary - primary goal with specifics,
current starting point (reference the activities you saw), key constraints,
timeline and milestones, what success looks like - {save_goals}. For example:

"The athlete is training for a 5km race on March 15th with a goal of breaking 17
minutes; current best is 18:30. Recent training: consistent running, about
40-50km/week with a couple of quality sessions. History of shin splints, so
intensity progresses carefully. Trains 5-6 days a week, Wednesdays off for work.
Success means hitting the time AND arriving at race day healthy."

"""


_SAVE_GOALS = "and save it with **save_goals** (it replaces any previously saved goals)"
_SHARE_GOALS = "and share it in the chat so the athlete can keep it (it can't be saved in this chat)"


# When notes storage isn't available, the paths skip every goals/notes tool
# (they would only return the same configuration error).
_PATH_A_NO_STORAGE = """## Path A: Onboarding a New Athlete (no notes storage)

Only for an athlete with no saved goals or notes (see Step 1); here the facts can't
tell, so go by what the athlete says.

1. **get_current_date**, then **get_activities** for roughly the last 2-4 weeks, so
   you open with something concrete about their recent training.
2. **Introduce yourself briefly** (a few sentences, not a feature list): you coach
   from their recent activities and can dig into any single workout. Say plainly
   that goals and notes can't be kept between chats right now (see the facts
   above). Mention recovery data only as connected or not.
3. **Talk through their goals** with the goal-setting conversation below, one
   question at a time.
4. **Close:** summarize the goals and next steps in the chat.

"""


_PATH_B_NO_STORAGE = """## Path B: Consultation with a Returning Athlete (no notes storage)

Their saved goals and past notes can't be read in this chat, so:

1. **get_current_date** - today's date and day of week
2. Ask ONE question to recap: what they're training for right now, and anything
   from earlier sessions they want to carry on with
3. **get_activities** - their recent training, patterns and volume

**Then begin:** acknowledge what you learned, ask ONE open question about how
they're doing, and let the athlete guide the conversation.

"""


_PATH_B = """## Path B: Consultation with a Returning Athlete

**Gather context first:**

1. **get_current_date** - today's date and day of week, so you can reason about
   "last week", "yesterday" and training cycles

2. **read_goals** - their objectives, timeline and constraints; reference them
   throughout. If no goals are saved, offer the goal-setting conversation above.

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

4. **get_activities** - what they've done since the last consultation, current
   patterns and volume

**Then begin:**
1. Briefly acknowledge what you learned (goals, recent notes, recent activities, today's date)
2. Ask ONE open question about how they're doing or what's on their mind
3. Let the athlete guide where the conversation goes

"""


_REMINDERS = """## Important Reminders (both paths)
- ONE question at a time - let them answer before moving on
- Save consultation notes at the END of meaningful conversations
- Update goals when they evolve (save_goals)
- Reference past consultations to show continuity

Ready to begin? 🎯"""


_REMINDERS_NO_STORAGE = """## Important Reminders (both paths)
- ONE question at a time - let them answer before moving on
- Nothing is saved this chat: end with a clear summary in the conversation instead

Ready to begin? 🎯"""


async def start_consultation_handler(arguments: dict, data_client, wellness_client) -> list[TextContent]:
    """Handle start_consultation tool calls.

    `data_client` and `wellness_client` are the clients the activity and
    wellness tools would get for this user; only their type is used, to name
    the data sources (no activity or wellness data is read here). The training
    repo is synced and checked for this user's goals file and note file names.
    """
    user_id = current_user_id()
    history = await asyncio.to_thread(read_training_history, user_id)

    storage = history.storage == "ok"
    guidance = (
        "🏃 Training Consultation\n\n"
        + _facts_section(data_client, wellness_client, history, hosted=bool(user_id))
        + _choose_path_section(history)
        + _COACHING_APPROACH
        + _data_sources_section(data_client, wellness_client)
        + (_PATH_A if storage else _PATH_A_NO_STORAGE)
        + _GOAL_SETTING.replace("{save_goals}", _SAVE_GOALS if storage else _SHARE_GOALS)
        + (_PATH_B if storage else _PATH_B_NO_STORAGE)
        + (_REMINDERS if storage else _REMINDERS_NO_STORAGE)
    )
    return [TextContent(type="text", text=guidance)]
