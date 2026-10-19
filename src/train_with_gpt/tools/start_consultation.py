"""Start consultation tool: the single entry point for every training conversation.

It returns what the server knows about the caller (saved goals and athlete
profile, consultation notes, connected data sources, today's date), and the
saved context itself - the athlete profile, the goals, the most recent notes in
full and an index of older ones, within a fixed size budget - so a consultation
never depends on the model remembering to read them. Then guidance for both
paths - onboarding a new athlete, or a consultation with a returning one - and
leaves the choice to the model, which also sees the athlete's message.
"""

import asyncio
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from mcp.types import Tool, TextContent

from .. import secret_box
from ..config import config
from ..helpers import (
    HOSTED_SYNC_WARNING,
    NO_WELLNESS_DATA_MESSAGE,
    PULLED_UPDATES_PREFIX,
    current_user_id,
    extract_note_headline,
    git_pull_and_read,
    read_file_if_exists,
    read_note_files,
    user_scoped_goals_file,
    user_scoped_notes_dir,
    user_scoped_profile_file,
)
from ..intervals_client import IntervalsClient
from ..strava_client import StravaClient


def start_consultation_tool() -> Tool:
    """Return the start_consultation tool definition."""
    return Tool(
        name="start_consultation",
        description=(
            "Call this first in any training conversation, before answering: it loads what's "
            "saved about the athlete (profile, goals, recent consultation notes in full and an "
            "index of older ones), today's date and which data sources are connected. Works for "
            "a brand-new athlete (onboarding: profile and goals) and a returning one (a coaching "
            "consultation); the guidance it returns covers both, so decide which fits from those "
            "facts and the athlete's message."
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
    goals: Optional[str] = None  # the saved goals' full text
    profile: Optional[str] = None  # the saved athlete profile's full text
    notes: list[tuple[str, str]] = field(default_factory=list)  # (file stem, text), newest first
    note: Optional[str] = None  # sync note or error detail for the model
    synced: bool = True  # False: the facts come from a clone that couldn't be synced

    @property
    def has_goals(self) -> bool:
        return self.goals is not None

    @property
    def has_profile(self) -> bool:
        return self.profile is not None

    @property
    def notes_count(self) -> int:
        return len(self.notes)

    @property
    def latest_note(self) -> Optional[str]:
        """The newest note's date (YYYY-MM-DD), if any."""
        return self.notes[0][0][:10] if self.notes else None


def _sync_failed(sync_note: Optional[str]) -> bool:
    """git_pull_and_read reports a failed fetch or rebase as a "(Note: ...)"
    and still reads the local clone. Its other notes (pulled updates, or local
    edits set aside) come after a successful sync."""
    return bool(sync_note) and any(part.startswith("(Note:") for part in sync_note.split("\n\n"))


def _saved_history(goals_file: Path, profile_file: Path, notes_dir: Path) -> tuple[Optional[str], Optional[str], list[tuple[str, str]]]:
    """The goals' and athlete profile's text (None if not saved) and every note
    (newest first). Read in one go, under one sync: what goes into the reply is
    chosen later (see _notes_sections)."""
    return read_file_if_exists(goals_file), read_file_if_exists(profile_file), read_note_files(notes_dir)


def read_training_history(user_id: Optional[str]) -> TrainingHistory:
    """Sync the training repo and read `user_id`'s goals, profile and notes (blocking)."""
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
        profile_file, _ = user_scoped_profile_file(repo_path, user_id)
        notes_dir, _ = user_scoped_notes_dir(repo_path, user_id)
        sync_note, (goals, profile, notes) = git_pull_and_read(
            repo_path, lambda: _saved_history(goals_file, profile_file, notes_dir)
        )
    except Exception as e:  # never let a storage problem block the conversation
        print(f"Error reading training history: {e}", file=sys.stderr)
        return TrainingHistory(storage="error", note=str(e))
    return TrainingHistory(
        storage="ok",
        goals=goals,
        profile=profile,
        notes=notes,
        note=sync_note,
        synced=not _sync_failed(sync_note),
    )


def _sync_fact(sync_note: Optional[str], hosted: bool) -> Optional[str]:
    """What to say about the repo sync. The "Pulled updates" summary lists every
    changed path in the (shared) repo - other users' goal/note files on the
    hosted server - and isn't needed for the facts, so it's dropped. Warnings
    stay, as a generic line for hosted users (they may name other users'
    commits or paths) and verbatim on the personal path."""
    if not sync_note:
        return None
    warnings = [part for part in sync_note.split("\n\n") if part and not part.startswith(PULLED_UPDATES_PREFIX)]
    if not warnings:
        return None
    if hosted:
        return HOSTED_SYNC_WARNING
    return " ".join(warnings)


def _intervals_key_missing(data_client) -> bool:
    """A local install without INTERVALS_API_KEY: every intervals.icu call would fail."""
    return isinstance(data_client, IntervalsClient) and not data_client.api_key


def _today_fact(today: date) -> str:
    # The server's clock (UTC on most hosts), not the athlete's time zone yet.
    return (
        f"- **Today:** {today.strftime(f'%A, %B {today.day}, %Y (%Y-%m-%d)')}, by the server's "
        "clock; if the athlete's local date is different, go by theirs"
    )


def _facts_section(data_client, wellness_client, history: TrainingHistory, hosted: bool,
                   today: date, full_notes: int = 0) -> str:
    activities = "Strava" if isinstance(data_client, StravaClient) else "intervals.icu"
    wellness = (
        "not connected" if isinstance(wellness_client, StravaClient)
        else "connected (intervals.icu)"
    )
    lines = [
        _today_fact(today),
        f"- **Activities source:** {activities}",
        f"- **Recovery data (sleep, HRV, resting HR, body weight):** {wellness}",
    ]
    if _intervals_key_missing(data_client):
        lines = [
            _today_fact(today),
            "- **Activities and recovery data (intervals.icu):** no API key is configured, so "
            "get_activities, analyze_activity and the sleep/HRV/resting-HR/weight tools will fail. Tell "
            "the athlete to set INTERVALS_API_KEY (see the README's Quick Start) and restart; "
            "meanwhile coach from what they tell you.",
        ]
    if history.storage == "ok":
        lines.append("- **Notes storage:** set up")
        lines.append(f"- **Saved goals:** {'yes (below)' if history.has_goals else 'none'}")
        lines.append(
            f"- **Athlete profile:** {'yes (full text below)' if history.has_profile else 'none'}"
        )
        if history.notes_count:
            lines.append(
                f"- **Consultation notes:** {history.notes_count}, most recent {history.latest_note} "
                f"(the latest {full_notes} in full below, then an index of older ones)"
            )
        else:
            lines.append("- **Consultation notes:** none")
        sync = _sync_fact(history.note, hosted)
        if sync:
            lines.append(f"- **Sync:** {sync}")
    else:
        if history.storage == "not_configured":
            status = "not set up on this server"
        elif hosted:
            # The detail (server paths, git output that may name other users'
            # files in the shared repo) stays in the server log.
            print(f"[start_consultation] notes storage unavailable: {history.note}", file=sys.stderr)
            status = "unavailable (a problem on the server's side)"
        else:
            status = f"unavailable ({history.note})"
        if hosted:
            fix = "it's configured by whoever runs the server, so tell the athlete to contact the server's operator if they want their goals and notes kept"
        else:
            fix = "if the athlete wants goals and notes kept between chats, offer to run **setup_training_repo**"
        lines.append(
            f"- **Notes storage:** {status}. Saved goals, profile and notes can't be checked, read "
            f"or saved in this chat, so don't call the goals/profile/notes tools; {fix}."
        )
    return "## What the server knows about this athlete\n\n" + "\n".join(lines) + "\n\n"


def _profile_section(history: TrainingHistory) -> str:
    """The saved athlete profile, verbatim: including it here means every
    consultation starts from it, without relying on a separate read."""
    if history.storage != "ok" or not history.has_profile:
        return ""
    return f"""## Athlete profile (saved)

This is the athlete's confirmed profile: use it as the baseline for this conversation.
Don't re-ask what it already answers. If the athlete says something that changes it (a new
race result, an injury, different availability), propose the updated text and save the
whole profile with **save_athlete_profile** once they confirm.

----- athlete profile -----
{history.profile.strip()}
----- end of athlete profile -----

"""


# --- Saved context: goals and notes ---------------------------------------------------
#
# Loaded into every consultation, so it's kept well under what clients accept
# from one tool result (about 25,000 tokens in Claude Code, ~150,000 characters
# on claude.ai). The profile has its own limit when it's saved
# (save_athlete_profile); room it doesn't use goes to the notes, as does room
# the goals don't use. Whatever is cut is marked, never dropped silently.

GOALS_BUDGET = 3_000
PROFILE_SHARE = 6_000
NOTES_BUDGET = 10_000
MIN_FULL_NOTES = 3
INDEX_BUDGET = 3_000
INDEX_DAYS = 90
INDEX_HEADLINE_CHARS = 120


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """`text` cut to at most `limit` characters at a line or word break, and whether it was cut."""
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    for separator in ("\n", " "):
        at = cut.rfind(separator)
        if at > limit // 2:
            return cut[:at].rstrip(), True
    return cut, True


def _fair_shares(lengths: list[int], budget: int) -> list[int]:
    """Split `budget` over items of these lengths: short ones are kept whole,
    long ones share what's left equally."""
    shares = [0] * len(lengths)
    left = budget
    by_length = sorted(range(len(lengths)), key=lambda i: lengths[i])
    for done, i in enumerate(by_length):
        shares[i] = min(lengths[i], left // (len(by_length) - done))
        left -= shares[i]
    return shares


def _notes_budget(history: TrainingHistory) -> int:
    unused_goals = GOALS_BUDGET - min(len((history.goals or "").strip()), GOALS_BUDGET)
    unused_profile = PROFILE_SHARE - min(len((history.profile or "").strip()), PROFILE_SHARE)
    return NOTES_BUDGET + unused_goals + unused_profile


def _full_notes(notes: list[tuple[str, str]], budget: int) -> list[tuple[str, str, bool]]:
    """The newest notes to include in full, as (stem, text, was_cut): always the
    last MIN_FULL_NOTES (cut to share the budget if together they don't fit),
    then older ones while they fit whole. Stops at the first that doesn't, so
    the full notes are always the most recent ones."""
    texts = [(stem, text.strip()) for stem, text in notes]
    first = texts[:MIN_FULL_NOTES]
    if sum(len(text) for _, text in first) > budget:
        shares = _fair_shares([len(text) for _, text in first], budget)
        return [(stem, *_clip(text, share)) for (stem, text), share in zip(first, shares)]
    full = [(stem, text, False) for stem, text in first]
    used = sum(len(text) for _, text in first)
    for stem, text in texts[MIN_FULL_NOTES:]:
        if used + len(text) > budget:
            break
        full.append((stem, text, False))
        used += len(text)
    return full


def _goals_section(history: TrainingHistory) -> str:
    if history.storage != "ok" or not history.has_goals:
        return ""
    goals, cut = _clip(history.goals.strip(), GOALS_BUDGET)
    if cut:
        goals += "\n[... the goals are cut here to keep this short: read them in full with **read_goals**]"
    return f"""## Goals (saved)

----- goals -----
{goals}
----- end of goals -----

"""


def _notes_sections(history: TrainingHistory, today: date) -> tuple[str, int]:
    """The recent notes in full and an index of the older ones, and how many
    notes are in full."""
    if history.storage != "ok" or not history.notes:
        return "", 0
    full = _full_notes(history.notes, _notes_budget(history))
    parts = [
        f"## Recent consultation notes (the latest {len(full)} of {history.notes_count}, newest first)\n\n"
        "These are your memory of the last consultations: use them, and don't re-read them.\n\n"
    ]
    for stem, text, cut in full:
        marker = (
            f"\n[... this note is cut here to keep this short: read it in full with "
            f"**read_consultation_notes** (note_date={stem[:10]})]" if cut else ""
        )
        parts.append(f"----- note {stem[:10]} -----\n{text}{marker}\n----- end of note -----\n\n")

    older = history.notes[len(full):]
    if older:
        cutoff = (today - timedelta(days=INDEX_DAYS)).isoformat()
        lines, used = [], 0
        for stem, text in older:
            line = f"- {stem[:10]} — {extract_note_headline(text, max_length=INDEX_HEADLINE_CHARS)}"
            if stem[:10] < cutoff or used + len(line) > INDEX_BUDGET:
                break
            lines.append(line)
            used += len(line) + 1
        rest = older[len(lines):]
        parts.append("## Older consultation notes (index: date and headline)\n\n")
        if lines:
            parts.append("\n".join(lines) + "\n\n")
        if rest:
            parts.append(
                f"{'Not listed' if lines else 'Not listed here'}: {len(rest)} older note(s), from "
                f"{rest[-1][0][:10]} to {rest[0][0][:10]}. "
            )
        parts.append(
            "Read a note in full with **read_consultation_notes** (note_date=...), find a topic "
            "with **search_consultation_notes**, or see the whole index with "
            "**list_consultation_notes**.\n\n"
        )
    return "".join(parts), len(full)


def _choose_path_section(history: TrainingHistory) -> str:
    if history.storage != "ok":
        hint = (
            "**Here the server can't tell** (no notes storage), so go by the athlete's message; "
            "if it doesn't say, ask ONE question: is this their first time using this coach, or "
            "have you worked together before? Either way nothing can be saved this chat."
        )
    elif not history.synced:
        hint = (
            "**Here the notes storage couldn't be synced just now**, so the goals/profile/notes facts "
            "(and the profile, goals and notes above) come from a possibly out-of-date copy and may miss what "
            "was saved from another device. Don't build or save an athlete profile in this chat "
            "(it could overwrite one saved elsewhere); that overrides the profile steps below. "
            "Don't treat them as final: if they show no history, ask ONE question (first time "
            "with this coach, or worked together before?) before onboarding; if they show "
            "history, it's a returning athlete (Path B)."
        )
    elif not history.has_goals and not history.notes_count and not history.has_profile:
        hint = "**Here: no goals, no profile and no notes, so this looks like a NEW athlete** (Path A)."
    elif history.notes_count and history.has_goals:
        hint = "**Here: goals and notes are saved, so this is a RETURNING athlete** (Path B)."
    elif history.notes_count:
        hint = (
            "**Here: notes exist but no goals, so this is a RETURNING athlete without goals** "
            "(Path B; offer the goal-setting conversation early on)."
        )
    elif not history.has_goals:
        hint = (
            "**Here: an athlete profile is saved but no goals or notes, so onboarding was "
            "probably cut short.** Treat them as returning (Path B): build on the profile "
            "above, and continue with the goal-setting conversation."
        )
    else:
        hint = (
            "**Here: goals are saved but there are no consultation notes yet - ambiguous.** "
            "They may have set goals and never had a consultation, or be picking up an "
            "unfinished first session. Go over the goals, then briefly ask the athlete whether "
            "they want to pick up where they left off or first hear what the coach can do; "
            "either way stay in Path B and build on the saved goals."
        )
    if (history.storage == "ok" and history.synced and not history.has_profile
            and (history.has_goals or history.notes_count)):
        hint += (
            " **No athlete profile yet:** once the athlete's first question is dealt with, "
            "offer to build one (**build_athlete_profile**). Offer, don't force it; if they "
            "decline, carry on."
        )
    return f"""## Step 1: Choose the path

You decide which path fits, from the facts above and what the athlete wrote:

- **Path A - New athlete (onboarding):** only when there are no saved goals, no profile and
  no notes (the facts decide this, not the athlete's wording). When storage is unavailable the
  facts can't tell, so an athlete who says they're new ("set me up", "first time")
  goes here.
- **Path B - Returning athlete (consultation):** any saved goals, profile or notes, even if the
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
    if _intervals_key_missing(data_client):
        return """## Available Data Sources

**None right now:** intervals.icu has no API key on this install (see the facts
above), so skip every get_activities, analyze_activity, analyze_lap, get_sleep_data,
get_hrv_data, get_resting_heart_rate and get_weight_data step in the paths below. Ask the athlete
about their recent training instead, and remind them to set INTERVALS_API_KEY.

"""
    activities_source = "Strava" if isinstance(data_client, StravaClient) else "intervals.icu"
    section = f"""## Available Data Sources

**Training Activities ({activities_source}):**
- **get_activities** - Recent training patterns and trends
- **analyze_activity** - Deep dive on specific workouts with zones, intervals, splits

"""
    if isinstance(wellness_client, StravaClient):
        if secret_box.is_configured():
            how_to_add = f"you can tell them how to add it: {NO_WELLNESS_DATA_MESSAGE}"
        else:
            # Without TOKEN_ENCRYPTION_KEY the login has no intervals.icu page.
            how_to_add = (
                "tell them this server doesn't offer connecting intervals.icu right now; "
                "they can ask the server's operator about it."
            )
        section += f"""**Recovery Metrics: not connected.** Sleep, HRV, resting heart rate and body
weight aren't available for this athlete, so don't call get_sleep_data,
get_hrv_data, get_resting_heart_rate or get_weight_data. Rely on how the athlete says they feel. If recovery
comes up, {how_to_add}

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
  - Read it against the athlete's own baseline and normal range, not as
    "higher = better"; single nights are noisy, look at the trend
- **get_resting_heart_rate** - Daily resting heart rate trends
  - A sustained rise above the athlete's own baseline can mean fatigue or
    illness; compare with their normal range, not other people's values
- **get_weight_data** - Body weight history: every weigh-in, or only the average, range and
  first-to-last change (mode='summary')

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

**Your Role:** You are an experienced, thoughtful endurance training coach who bases
everything on sport science and stays up to date with it:
- Grounds every recommendation in current evidence: research it on the web rather than
  relying on memory (call **get_training_science** for how to find, check and cite it),
  say where it comes from and how sure the evidence is
- Says so when the evidence is thin or contested, and suggests deeper research or a
  professional instead of guessing
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

Only for an athlete with no saved goals, profile or notes (see Step 1).

1. **get_activities** for roughly the last 2-4 weeks (today's date is in the facts
   above), so you open with something concrete about their recent training.
2. **Introduce yourself briefly** (a few sentences, not a feature list): you coach
   from their recent activities, you remember their profile, goals and past
   consultations between chats (when notes storage is set up), and you can dig into
   any single workout. Mention recovery data only as connected or not, per the facts
   above.
3. **Build their athlete profile first:** call **build_athlete_profile** and follow it
   (interview, check against their data, confirm, **save_athlete_profile**). It is the
   longest step, so say roughly how long it takes; if the athlete would rather start
   with their goals, do step 4 first and build the profile next session.
4. **Set their goals** with the goal-setting conversation below, one question at a
   time, building on the profile (don't re-ask what it covers), then **save_goals**.
5. **Close the first session:** summarize, save a short note with
   **save_consultation_notes** (what you learned, and anything still to ask), and
   explain the routine: start each chat with "start a consultation", say "save
   notes" at the end of a useful one, and "update my goals" or "update my profile"
   when things change.

If the athlete stops partway, still save a note listing what's done and what's
pending (e.g. "profile: interview done, not yet saved"), so the next session can
pick it up.

"""


_GOAL_SETTING = """## Goal-Setting Conversation (Path A, or Path B when goals are missing or changing)

**ASK ONE QUESTION AT A TIME.** This is a conversation, not an interview. Look at
their recent activities first (get_activities) so you can reference them.

**Topics to cover:**
1. **Primary goal** - what they're training for (event, race, milestone, or "no
   event, general fitness" - both are fine), specific target, date, and why it
   matters to them
2. **Starting point for this goal** - how far they are from the target (check their
   activities first!){starting_point}
3. **Timeline** - milestones on the way, and the current training block (phase, focus)
4. **Secondary priorities** - staying healthy, enjoying the process, balance with
   life, other fitness goals

❌ BAD (multiple questions):
"What race are you training for? What's your target time? When is the race? Do you have any injuries?"

✅ GOOD (one at a time):
Athlete: "I want to set some training goals"
You: "I can see from your recent activities that you're running consistently. What are you training for?"
Athlete: "A 5k race in March"
You: "Great! Do you have a specific time goal in mind?"

**Then** write a clear, natural-language summary of the goal - primary goal with
specifics, why it matters, timeline and milestones, the current block, what success
looks like (the starting point shapes the plan but stays out of this summary) -
{save_goals}. For example:

"The athlete is training for a 5km race on March 15th with a goal of breaking 17
minutes. It matters because it's a club championship. Milestone:
sub-17:45 at a parkrun by mid-February. Current block: base building until mid-January,
then threshold work. Success means hitting the time AND arriving at race day healthy."

"""


_SAVE_GOALS = "and save it with **save_goals** (it replaces any previously saved goals)"
_STARTING_POINT_PROFILE = (
    ". Background, PBs, constraints and injury history belong in the athlete profile, "
    "not the goals: take them from the profile, and if it's missing, ask only what this "
    "goal needs and keep those facts for the profile"
)
_STARTING_POINT_NO_STORAGE = (
    ", plus what shapes the plan: time per week, injuries or limitations, life commitments"
)
_SHARE_GOALS = "and share it in the chat so the athlete can keep it (it can't be saved in this chat)"


# When notes storage isn't available, the paths skip every goals/notes tool
# (they would only return the same configuration error).
_PATH_A_NO_STORAGE = """## Path A: Onboarding a New Athlete (no notes storage)

Only for an athlete with no saved goals or notes (see Step 1); here the facts can't
tell, so go by what the athlete says.

1. **get_activities** for roughly the last 2-4 weeks (today's date is in the facts
   above), so you open with something concrete about their recent training.
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

1. Ask ONE question to recap: what they're training for right now, and anything
   from earlier sessions they want to carry on with
2. **get_activities** - their recent training, patterns and volume

**Then begin:** acknowledge what you learned, ask ONE open question about how
they're doing, and let the athlete guide the conversation.

"""


_PATH_B = """## Path B: Consultation with a Returning Athlete

**You already have the saved context above:** today's date, the athlete profile, the
goals, the latest consultation notes in full and an index of older ones. That is
your memory of this athlete: don't call read_goals or read_consultation_notes to
read it again. Use the tools only to go further:
- **search_consultation_notes** when the athlete refers to something by topic ("the
  calf thing", "that race") and it isn't in the notes above
- **read_consultation_notes** (note_date=...) for an older note whose headline matters
  today, or a note above that was cut
- **list_consultation_notes** for the index beyond what's listed above
- **read_goals** only if the goals above were cut
- No goals saved: offer the goal-setting conversation above. No profile saved: offer
  to build one (**build_athlete_profile**) at a natural moment, without forcing it.

**Then check what's new:** **get_activities** - what they've done since the last
consultation, current patterns and volume.

**Then open with a read-back** (3-5 short lines), before any advice:
- the goal event and date, and the target
- the latest result or key session
- open issues: an injury or niggle, illness, a plan change, anything the notes left
  pending
- what stands out in their training since the last consultation

If something couldn't be loaded (notes storage unavailable or not synced, activities
failing), say that first. Ask the athlete to correct anything wrong or out of date;
a confirmed change to a durable fact goes into the profile or goals.

**Then begin:** ask ONE open question about how they're doing or what's on their
mind, and let the athlete guide where the conversation goes.

"""


_REMINDERS = """## Important Reminders (both paths)
- ONE question at a time - let them answer before moving on
- Save consultation notes at the END of meaningful conversations
- Update goals when they evolve (save_goals)
- When a durable fact about the athlete changes (a race result, an injury, availability,
  a new conclusion about what works), propose the updated profile and save it after they
  confirm (save_athlete_profile)
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
    repo is synced once, and this user's profile, goals and notes are read and
    included within the budget above.
    """
    user_id = current_user_id()
    history = await asyncio.to_thread(read_training_history, user_id)
    today = date.today()
    notes, full_notes = _notes_sections(history, today)

    storage = history.storage == "ok"
    guidance = (
        "🏃 Training Consultation\n\n"
        + _facts_section(data_client, wellness_client, history, hosted=bool(user_id),
                         today=today, full_notes=full_notes)
        + _profile_section(history)
        + _goals_section(history)
        + notes
        + _choose_path_section(history)
        + _COACHING_APPROACH
        + _data_sources_section(data_client, wellness_client)
        + (_PATH_A if storage else _PATH_A_NO_STORAGE)
        + _GOAL_SETTING.replace("{save_goals}", _SAVE_GOALS if storage else _SHARE_GOALS)
        .replace("{starting_point}", _STARTING_POINT_PROFILE if storage else _STARTING_POINT_NO_STORAGE)
        + (_PATH_B if storage else _PATH_B_NO_STORAGE)
        + (_REMINDERS if storage else _REMINDERS_NO_STORAGE)
    )
    return [TextContent(type="text", text=guidance)]
