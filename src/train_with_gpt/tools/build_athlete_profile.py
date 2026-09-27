"""Build athlete profile tool: guidance only, no data is read or written here."""

from mcp.types import Tool, TextContent

from .save_athlete_profile import PROFILE_MAX_CHARS, PROFILE_SECTIONS, PROFILE_TARGET_CHARS


def build_athlete_profile_tool() -> Tool:
    """Return the build_athlete_profile tool definition."""
    return Tool(
        name="build_athlete_profile",
        description=(
            "Guidance for building (or rebuilding) the athlete profile with the athlete: an "
            "interview, a check of what they said against their last 12 months of data, then "
            "a discussion and their confirmation before anything is saved. Call it when "
            "start_consultation's onboarding says so, when a returning athlete agrees to build "
            "a profile, or when they ask to rebuild it. Returns instructions only."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    )


_SECTIONS = "\n".join(f"   - `## {name}`" for name in PROFILE_SECTIONS)

BUILD_GUIDANCE = f"""🧭 Building the Athlete Profile

The profile is the coach's **conclusions about the athlete**, drawn from an interview,
checked against their data and confirmed by them. It is loaded at the start of every
consultation, so it must be right and short.

**It holds:** background, race results and PBs, tests, health (current issues, relevant
history, recurring patterns), constraints, strengths and limiters, what works, preferences.
**It never holds stats** (weekly volume, fitness/form, resting HR, HRV or sleep numbers)
or gear: the data tools recompute those whenever they're needed. Data enters the profile
only as a conclusion ("handles 45-50 km weeks; above 55 km calf problems return") or a
durable fact (a race result). Goals, targets and the current training block stay in the
goals (save_goals).

If the athlete already has a profile (it's in start_consultation's output, or use
**read_athlete_profile**), start from it: ask what changed rather than re-asking everything.

Tell the athlete up front that this takes a while (roughly 10-20 minutes of back and forth)
and can be stopped any time; if they stop, save a consultation note with the claims and
findings so far, and nothing to the profile.

## Phase 1: Interview (save nothing yet)

Go section by section, **ONE question at a time**, open questions first, then specifics:

1. Background - years training, sports, how they got here
2. Race results and PBs - event, date, distance, time
3. Tests - lab or field tests (thresholds, VO2max), if any
4. Health - current niggles or illness, relevant injury history, recurring patterns
5. Constraints - days and hours available, fixed days off, equipment, life load
6. Strengths and limiters - as the athlete sees them
7. What works - and what hasn't: volume, blocks, tapers, fuelling, heat
8. Preferences - training style, how they like to be coached

Keep a working list of their **claims** ("10k PB ~45:00 last autumn", "usually 5 days a
week", "calf issues on hills"). Don't argue or check yet.

**Health:** before the first health question, tell the athlete where the profile is
stored: in the training notes repository this server uses (on a hosted server, a private
repository that its operator can read). Keep patterns that change coaching (e.g. "ferritin
drops below 40 without supplementation; supplements daily"), never raw lab panels, dated
series of values or clinical detail. A single blood test belongs in a consultation note, if
the athlete wants it kept at all.

## Phase 2: Evidence (existing tools only)

1. **get_current_date**, then **get_activities** over the last 12 months, in chunks (e.g.
   one call per quarter) to keep each response manageable. Look at volume and its range,
   the biggest weeks and blocks, gaps of a week or more (often injury or illness), longest
   sessions, and activities that look like races.
2. If recovery data is connected (see start_consultation's facts): **get_resting_heart_rate**,
   **get_hrv_data** and **get_sleep_data** over the same period, for bands and trends
   around races, gaps and hard blocks.
3. For an athlete with history: **read_goals**, and **search_consultation_notes** per topic
   (race, PB, injury, pain, illness, availability, taper, fuelling) instead of reading
   every note.

Then sort every claim:
- **confirmed** - the data agrees ("10k 45:05 on <date>");
- **contradicted** - the data says otherwise ("you said 5 days a week; the last 12 months
  average about 3.5, with a 5-week gap in spring");
- **not in the data** - tests, health, preferences.

Also collect what the data shows that the athlete didn't mention (a race not listed, a
faster effort, a big block before a good result), and draft your own conclusions:
strengths, limiters, what seems to work.

## Phase 3: Discussion, then save

1. Go through the contradictions, the new findings and your draft conclusions **one at a
   time**. Ask, don't overrule: the athlete may know why (watch left at home, a race run as
   training, a deliberate break).
2. Then show the **complete profile text** in the chat, using these sections:
{_SECTIONS}
   Short bullets; a table for race results (date, event, distance, time, notes: the best
   per distance plus the last 12 months). About {PROFILE_TARGET_CHARS:,} characters in total
   (the save is refused over {PROFILE_MAX_CHARS:,}); details go to consultation notes.
3. Save it with **save_athlete_profile** only after the athlete confirms the text (apply
   their corrections first). It replaces the whole profile, so always send all sections.

**Conflict rules:**
- **State** (health, constraints, preferences): the newest statement wins, including the
  athlete's answer in this discussion. Older ones are dropped, not merged.
- **PBs are race results**, never inferred from training efforts. A faster training effort
  is raised in the discussion, not saved as a PB.
- **Unresolved** items are left out or noted as such ("5k PB: athlete unsure, not in the
  data"), never guessed.

If notes storage isn't available in this chat, do the same but share the final text in the
chat instead of saving it, and say it can't be kept between chats yet.
"""


async def build_athlete_profile_handler(arguments: dict) -> list[TextContent]:
    """Handle build_athlete_profile tool calls."""
    return [TextContent(type="text", text=BUILD_GUIDANCE)]
