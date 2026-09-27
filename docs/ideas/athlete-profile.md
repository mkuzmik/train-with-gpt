# Idea: a living athlete profile

This proposes an athlete profile: a short document with the coach's
conclusions about who the athlete is, built from an interview checked
against their data, loaded at the start of every consultation. A small v1
is implemented (below); the rest of this document remains a proposal.

## v1 scope (implemented)

The owner asked for a much smaller first version. v1 ships:

- **`save_athlete_profile(content)`**: saves the whole profile at once, like
  `save_goals` (same `git_save_file`, last writer wins). Only after the
  athlete confirmed the text. Refused over 8,000 characters (target ~5,500)
  with a request to move detail to notes. Path: `athlete/<user_id>.md` for
  OAuth users, `athlete-profile.md` at the repo root on the personal path
  (`user_scoped_profile_file`).
- **`read_athlete_profile()`**: like `read_goals`; when missing, points to
  `build_athlete_profile`.
- **`build_athlete_profile()`**: guidance only, the three phases of
  "Building the profile" below, with the evidence phase using **existing
  tools only** (`get_activities` over 12 months in quarterly chunks, the
  wellness tools when intervals.icu is connected, `search_consultation_notes`
  per topic and the goals). The conflict rules and the health/privacy rules
  apply. The finished profile is shown in full and saved once, after the
  athlete confirms (not per section).
- **`start_consultation`** (#11's single entry point) reports "athlete
  profile: yes/none" and, when one exists, **includes its full text**, so
  every consultation starts from it. New athletes build the profile during
  onboarding, before goal setting (or after it, if they'd rather start with
  goals). Returning athletes without one are offered it, not forced. A
  profile with no goals or notes counts as history (an unfinished
  onboarding), not a new athlete.
- **Goals vs profile:** `save_goals` and the goal-setting guidance are
  goal-focused; background, PBs, constraints and injury history go to the
  profile.

Not in v1 (still proposed below): section-level updates
(`update_athlete_profile`, `mode`, `source`), the `base` check,
`git_update_file`, per-section `as of` lines and staleness checks,
`get_profile_evidence` and its aggregation module, new intervals.icu or
Strava client methods, and the save-time checklist in
`save_consultation_notes`.

Depends on: #8 (notes sync fix) for all writes. Works best with #9
(`consultation-context.md`, assembled `start_consultation`). Shares
aggregation code with #12 (`more-training-data.md`) but does not need its
tools. #11 (`new-user-onboarding.md`) builds on it.

## Problem

The server keeps two kinds of memory today:

- **Goals** (`goals.md` on the personal path, `goals/<user_id>.md` for
  OAuth users; see `user_scoped_goals_file` in `helpers.py`): one document,
  replaced wholesale by `save_goals`.
- **Notes** (`notes/` or `notes/<user_id>/`): one immutable, timestamped file
  per `save_consultation_notes` call, so in effect an append-only log.

Neither holds what a coach needs to know every time: race results and PBs,
test results, injury history and recurring health patterns, weekly
availability and limits, strengths and limiters, what has and hasn't worked.
These end up scattered across daily notes, so
the coach has to rediscover them each consultation and often doesn't (see
`consultation-context.md`).

Goals are not the right place either. They change on a different cadence,
and mixing the two makes both harder to keep current. Today they already
overlap: the `save_goals` description asks for "goals, current state,
constraints, and context", and the `discuss_goals` example summary includes
a current 5k best, an injury history and weekly availability. Once the
profile exists, those facts move there (see "Goals vs profile" below).

## Proposed solution

### What the profile is, and isn't

The profile is the coach's **conclusions about the athlete**: what they said
in interviews, checked against their data, and confirmed. It is written
text, stored in the training repo, and changes only through
`update_athlete_profile` with the athlete's confirmation.

It holds **no stats**. Recent volume, fitness/form (CTL/ATL), resting HR,
HRV, sleep, zones and gear mileage change every week or every session, and
the data tools already recompute them whenever they're needed
(`start_consultation`, `get_activities`, the wellness tools, #12's summary
tools). Copying them into the profile, stored or computed on read, would
only duplicate those tools and go stale.

Data goes into the profile only as a conclusion drawn from it:

- "10k PB 44:30, Autumn 10k, 2026-09-07": a result that stays true until
  the next PB. It goes in Race results, even when it was first spotted in
  the data.
- "Handles 45–50 km weeks well; above 55 km/week calf problems return
  (2025 and 2026)": a conclusion from 12 months of data plus the interview.
  It goes in What works.
- "Last 4 weeks: 42 km/week, CTL 48": a stat. It is not in the profile;
  `start_consultation` shows it.

Because it holds no Strava data, only the athlete's own facts and the
coach's conclusions, the profile is also clear of Strava's 7-day cache and
deletion rules.

### Sections

Target: at most about 5,500 characters (~1,400 tokens), small enough to
load at the start of every consultation. Details stay in notes.

| Section | Content | Char cap |
|---|---|---|
| Background | years training, sports, history | 600 |
| Race results | table: date, event, distance, time, notes. Keep the best per distance plus the last 12 months; older rows move to notes | 1,200 |
| Tests | performance tests: lab VO2max/thresholds, field tests | 500 |
| Health | current niggles, recent illness, relevant injury history, and recurring health patterns that change coaching, e.g. "ferritin drops below 40 without supplementation" (see Privacy) | 600 |
| Constraints | available days and hours, equipment, weekly limits, life load | 600 |
| Strengths and limiters | the coach's assessment: what the athlete is good at, what holds them back, e.g. "strong aerobic base, fades in the last 5 km of a half; top-end speed is the limiter" | 600 |
| What works | responses to volume, blocks, tapers, fueling, heat. This is also the home for the "response profile" idea (D5) in `science-based-coaching.md` | 800 |
| Preferences | training style, how they like to be coached | 400 |

"Current block" (phase, focus, key sessions) is left out. It changes weekly,
and it stays in goals until a plan file exists (the parked
`save_training_plan` idea in `intervals-icu.md`, or the calendar tool in
`more-training-data.md`). If a long-running pattern emerges from it (e.g.
"responds well to 3:1 blocks"), that goes to What works.

### Data for building and checking the profile

The profile holds no data, but building and reviewing it needs a lot of it.
That comes from `get_profile_evidence(months=12)`, a read-only tool the build
flow calls (see below). It returns a long view, summarized so it fits in one
response:

- weekly volume per sport and its range, the biggest weeks and blocks, and
  training gaps of 7+ days (often injury or illness);
- race-flagged activities with date, distance and time;
- best efforts at standard distances (intervals.icu);
- fitness (CTL) peaks and troughs around races, and resting HR/HRV/sleep
  bands (intervals.icu);
- mismatches with the current profile, e.g. "a race-flagged run on <date>
  isn't in Race results" or "a 10 km best effort of 44:30 beats the stated
  PB". These are raised with the athlete and never applied automatically.

Sources (owner decision: intervals.icu first, no new Strava data):

- **intervals.icu connected** (personal path, or a remote user with a key):
  everything comes from intervals.icu, including activities. This differs
  from today's remote-path rule, where activities always come from Strava
  (`_get_active_data_client` / `_get_wellness_client` in `server.py`). The
  evidence tool prefers intervals.icu when a key is connected.
- **Strava only:** only the activity list the server already fetches for
  `get_activities` (volume, longest sessions, gaps, and race flags from
  `workout_type`: 1 = run race, 11 = ride race, community-documented). No
  `/athlete`, gear, `best_efforts` detail fetches or `suffer_score`. The
  evidence says what is missing, e.g. "connect intervals.icu for best
  efforts and fitness history".

| Evidence | Strava only | intervals.icu connected |
|---|---|---|
| Volume, longest sessions, gaps | activity list (already fetched) | `GET /athlete/0/activities` |
| Race-flagged activities | `workout_type` on those summaries | activity type/name; `RACE_*` calendar events later |
| Best efforts | not available | `pace-curves` / `power-curves` (new client method, shared with #12) |
| Fitness history, resting HR, HRV, sleep | not available | wellness |
| Thresholds (to check against Tests) | not available | `sport-settings` (new client method, shared with #12) |

Cost: Strava-only, one call is 3–5 activity-list requests for 12 months (200
per page), with no per-activity fetches. It runs when the profile is built
or reviewed, not on every consultation, so it doesn't matter for Strava's
shared limits (100 reads per 15 minutes, 1,000 per day). intervals.icu uses
per-user keys and has no published limit. No cache is needed; the result is
not stored.

The aggregation code (weekly totals, gaps, bands) should be one module that
#12's summary tools reuse.

### Tools

1. **`read_athlete_profile`**: returns the profile, then Checks (stale and
   missing sections, duplicated headings). Section metadata is shown in
   compact form. Each section's short id (e.g. `health`) is shown so the
   model can pass it to `update_athlete_profile`. It makes no data API
   calls. Until #9 lands, `start_consultation`'s guidance tells the model to
   call it first. After #9, `start_consultation` includes it directly.
2. **`update_athlete_profile(section, content, source, mode, base)`**:
   - `section`: one of the fixed ids.
   - `mode`: `replace` (the new body for that section) or `append` (add
     lines or table rows, e.g. a new race result).
   - `source`: `interview`, `athlete`, `note:<YYYY-MM-DD>` or `data`.
   - `base`: optional, a short hash of the section text the model read (see
     "Keeping it current" below). `append` needs no `base`.
   - Content over the section's cap is rejected, with a request to move
     detail to notes.
   - An `##` heading inside `content` is demoted to `###`.
   - The tool description says to call it only after the athlete confirms
     the change.
3. **`get_profile_evidence(months=12)`**: the data view above. Read-only.
4. **`build_athlete_profile`**: guidance only, like `discuss_goals`. It
   walks the model through the three-phase build below. #11 (onboarding) and
   the backfill for existing athletes both use it, and the athlete can ask
   for it by name ("let's rebuild my profile").
5. **Save-time checklist**: `save_consultation_notes` ends its success output
   with a one-line checklist: "New result, health change, availability
   change, or a new conclusion about what works? Propose a profile update."

### Building the profile

The profile is only useful if it is right, so building it is a
conversation, not a form. Three phases:

1. **Interview.** The coach asks about each section in turn: background,
   races and PBs, tests, health (current issues, history, recurring
   patterns), constraints, strengths and limiters as the athlete sees them,
   what has and hasn't worked, preferences. Open questions first, then
   specifics. Nothing is saved yet; the coach keeps a working list of claims
   ("10k PB ~45:00 last autumn", "usually 5 days a week", "calf issues on
   hills").
2. **Evidence.** The coach calls `get_profile_evidence(months=12)` and, for
   existing athletes, `search_consultation_notes` per section (race, PB,
   injury, pain, availability, taper, fueling) plus the current goals file,
   instead of reading every note. It then sorts each claim:
   - **confirmed**: the data agrees ("10k 45:05 on 2025-10-12");
   - **contradicted**: the data says otherwise ("you said 5 days a week;
     the last 12 months average 3.4, with a 5-week gap in March");
   - **not in the data**: tests, health, preferences.

   It also collects what the data shows that the athlete didn't mention (a
   faster best effort, a race not listed, a big block before a good result)
   and drafts its own conclusions: strengths, limiters, what seems to work.
3. **Discussion.** The coach goes through contradictions, new findings and
   its draft conclusions one at a time, and asks rather than overrules: the
   athlete may know why (a watch left at home, a race run as training, a
   deliberate break). Then it proposes each section's final text, the
   athlete confirms or corrects, and it is saved right away. Saving per
   section makes the build resumable, which #11 needs for onboarding.

Fixed rules for conflicts:

- **State** (health, constraints, preferences): the newest dated statement
  wins, including the athlete's answer in phase 3. Older ones are dropped,
  not merged.
- **Race results**: one row per event. If sources disagree on the time,
  prefer the activity data, then the athlete, then the latest note, and show
  the values to the athlete.
- **PBs** are race results, never inferred from training efforts. A faster
  training best effort is raised in the discussion, not saved as a PB.
- Anything still unresolved is left out and noted in the section ("5k PB:
  athlete unsure, not in the data").

### Keeping it current

Three small mechanisms, so the profile doesn't rot after the build:

- **Staleness thresholds.** Each section has a date (`as of`). When a
  section is older than its threshold, `read_athlete_profile` lists it under
  Checks as stale, so the coach knows to ask "are you still training 5 days
  a week?" at a natural moment, or to re-run the evidence for its
  conclusions. Nothing is changed automatically.

  | Section | Stale after |
  |---|---|
  | Constraints | 90 days |
  | Health | 30 days when it lists a current issue, otherwise 180 |
  | Strengths and limiters, What works | 180 days |
  | Preferences, Tests | 365 days |
  | Background, Race results | never |

- **`base` check.** Protects against two chats editing the same section at
  once. The model passes a short fingerprint of the section as it read it;
  if the section has changed since (another session saved something), the
  update is rejected and the current text is returned so the model can
  merge instead of silently overwriting it.
- **Save-time checklist**, above, prompts small updates during normal
  consultations. A periodic review (e.g. after each race or every few
  months) re-runs phases 2–3 for the stale sections.

### Storage and format

- **Path:** `athlete/<user_id>.md` in the training repo, or
  `athlete-profile.md` at the root on the personal path. This needs a new
  `user_scoped_profile_file` helper next to `user_scoped_goals_file`. On the
  remote path `user_id` is the Strava athlete id (the OAuth token's
  `subject`).

  The name avoids `profiles/`: `intervals-icu.md` already reserves
  `profiles/<user_id>.json` for identity mapping, and `profile/` next to it
  would be confusing. All personal data stays in the private training repo,
  never in this public code repo.
- **Format:** a Markdown file with a fixed set of `##` headings and one
  visible metadata line under each: `_as of 2026-03-02 · interview_`.

  The first draft used an HTML comment for this. A visible line is better:
  the athlete sees the dates on GitHub, the model sees them in the read
  output, and they are just as easy to parse.
- **Parsing rules**, so hand edits on GitHub don't break updates:
  - Split only on the known `##` headings, matched case-insensitively.
  - Keep unknown `##` sections as they are and show them in the read output.
  - A missing or malformed metadata line means "as of unknown", which counts
    as stale.
  - A duplicated heading is reported in Checks, and updates to it are
    refused until it is fixed.
  - Text before the first heading is preserved.
- **Concurrency under #8.** #8's `git_save_file(repo, path, content, msg)`
  writes fixed content. On a lost push race it re-syncs and writes the *same*
  content again. That is fine for goals (last writer wins), but wrong for a
  section update. Content computed from an earlier read would overwrite
  another session's change to a different section.

  So this needs a small addition to #8's helper: `git_update_file(repo, path,
  transform, msg)`. It works like `git_save_file` but calls
  `transform(current_text_or_None) -> new_text` after each sync, under the
  repo lock. The section splice runs inside `transform`, so each retry applies
  the update to the latest file.

  Result: concurrent updates to different sections both land. Concurrent
  `append`s both land. Concurrent `replace`s of the same section are caught
  by `base`, or, without it, the last writer wins for that section only.
  `git_save_file` can then become `git_update_file` with a constant
  transform.
- **One commit per update**, with a message like `Profile: update health
  (interview)`. Git history is the audit log.

### Example (made-up values)

The stored file, `athlete/<user_id>.md`:

```markdown
# Athlete profile

## Background
_as of 2026-01-10 · interview_
- Running since 2019, road races 5k to half marathon. Cycles for commuting.
- Previously played team sports; no structured endurance training before 2019.

## Race results
_as of 2026-03-02 · interview_
| Date | Event | Distance | Time | Notes |
|---|---|---|---|---|
| 2026-03-01 | Spring half marathon | 21.1 km | 1:39:40 | windy, negative split |
| 2025-10-12 | Autumn 10k | 10 km | 45:05 | PB |
| 2025-05-18 | Park 5k | 5 km | 21:20 | PB |

## Tests
_as of 2025-11-20 · athlete_
- Lab test 2025-11: LTHR 172 bpm, VO2max 52 ml/kg/min.

## Health
_as of 2026-02-20 · note:2026-02-20_
- Current: mild calf tightness after hilly runs; hill volume reduced, improving.
- History: shin pain in 2024, resolved with a volume cut.
- Pattern: ferritin drops below 40 without supplementation; takes iron daily since 2025.

## Constraints
_as of 2026-01-10 · interview_
- 5 days/week, about 6 h. Long run on Saturday or Sunday. No training on Wednesdays.
- Gym access twice a week; no treadmill.

## Strengths and limiters
_as of 2026-03-02 · interview_
- Strength: aerobic durability; long runs hold pace to 2 h when fuelled.
- Limiter: top-end speed; 5k is relatively weaker than 10k/half.

## What works
_as of 2026-03-02 · interview_
- Two-week taper with one short sharp session in race week.
- Volume: handles 45–50 km/week; above 55 km/week calf problems returned (2025, 2026).
- Long runs over 2 h need 60 g/h carbohydrate or the last 30 min fall apart.

## Preferences
_as of 2026-01-10 · interview_
- Wants reasons behind sessions; prefers effort (RPE) targets over pace on hills.
```

### Goals vs profile

Goals keep the target: event, date, target time, why it matters, and, until a
plan file exists, the current block. The profile keeps facts about the
athlete. When the profile ships:

- `save_goals` and `discuss_goals` descriptions stop asking for current
  state and constraints, and point to `update_athlete_profile` instead.
- The build flow ("Building the profile") moves those facts out of the goals text,
  with the athlete's confirmation.

### Privacy

The training repo is private, but it is not personal on the remote path. It
is one shared repo (`TRAINING_REPO_URL`) holding every user's files, readable
by whoever operates the server and anyone with access to that repo. Git
history keeps every version, so "delete" means rewriting history. Notes
already contain health remarks, but a profile concentrates them into one
dense summary. Health data is also a special category under GDPR.

Rules:

- **Health** holds what changes coaching: current status ("calf tightness,
  reduced hill volume"), relevant history, and **recurring patterns**,
  including ones from blood work, e.g. "ferritin tends to drop below 40
  without supplementation; supplements daily". Owner decision: such a
  pattern is worth having in the profile because it shapes training and
  recovery advice every time.
- What stays out: full lab panels, dated series of raw values, diagnoses in
  clinical detail, and medication beyond what matters for training. A single
  blood test goes into a note, at the athlete's request; only the pattern it
  shows goes into the profile.
- Health entries need the athlete's explicit OK, like every stated section,
  and the coach says the profile is stored in the training repo when it
  first proposes one.
- The onboarding landing page (#11) says what is stored and where.
- A way to delete a user's profile (and notes) is needed before more users
  join. It is out of scope here but listed as a dependency. Deleting only the
  latest file is not enough because of git history.

## Alternatives considered

- **Put it all in goals.** One file, no new tools, but goals are replaced
  wholesale, and mixing slow facts with changing targets makes both worse.
- **Structured YAML/JSON (a sidecar next to Markdown, or instead of it).**
  - Easier to validate, and fields like race results could be typed.
  - A sidecar means two files to keep consistent under concurrent writes, and
    athletes can't read or fix JSON comfortably on GitHub.
  - Most profile content is prose ("what works"), which a schema doesn't help.
  - Fixed headings, a visible metadata line and tolerant parsing are enough.
    Race results in a Markdown table with an `append` mode cover the only
    real "record" data.
  - Revisit if more structured fields appear.
- **YAML front matter for per-section metadata.** One file, but the metadata
  sits away from its section and goes out of sync when a heading is edited
  by hand.
- **Stats in the profile** (stored, or computed on read like an earlier
  draft of this doc). Duplicates the data tools, goes stale if stored, and
  mixes numbers with conclusions. Dropped by owner decision.
- **Let the model rewrite the whole profile after every consultation.**
  Simple, but it drifts, loses details and races with concurrent sessions.

## Decisions

Owner decisions (2026-09-27):

1. **The profile is conclusions, not stats.** It holds the coach's
   reasoning and conclusions about the athlete from the interview and the
   data, plus durable facts such as PBs and race results. Weekly stats
   (volume, fitness/form, baselines) are not part of it, stored or
   computed; the data tools recompute them when needed.
2. **Current block** stays in goals. Long-running patterns from it can move
   to What works.
3. **Blood work:** recurring patterns that matter for coaching go in Health
   (e.g. low ferritin without supplementation); raw panels and single tests
   go to notes on request.
4. **Path:** one file per user, `athlete/<user_id>.md`
   (`athlete-profile.md` on the personal path).
5. **Data sources** for the evidence: intervals.icu first, including
   activities when a key is connected. No new Strava data: Strava-only users
   get only the activity list already fetched. No `suffer_score`.
6. **No per-session data in the profile:** no gear or anything else that
   changes with every training.
7. **Building the profile** is three phases: interview, evidence from a
   12-month data pass, then discussion of what the data confirms or
   contradicts (`build_athlete_profile`, `get_profile_evidence`).

Adopted as proposed (the owner can still change them): the staleness
thresholds and the optional `base` check (see "Keeping it current").

Still open:

- On the remote path, the evidence would use intervals.icu activities while
  other tools still read Strava, so numbers could differ slightly (e.g. a
  manual Strava entry not synced to intervals.icu). Recommended: accept it
  and name the source in the evidence output; revisit if #12 moves remote
  tools to intervals.icu.

## Rollout

Hard dependency: #8 merged. Phase 1 adds `git_update_file` on top of it.

1. **Format and writes (M, 2–3 days with tests).**
   - `user_scoped_profile_file`, the parser/splicer, `git_update_file`
   - `read_athlete_profile` (stated part and Checks for stale/missing),
     `update_athlete_profile`
   - a line in `start_consultation`'s guidance to call it first
   - updated `save_goals`/`discuss_goals` descriptions
2. **Evidence (M).**
   - a shared aggregation module (weekly totals, longest sessions, gaps,
     bands) that #12 reuses
   - intervals.icu: activities, wellness, and the new `sport-settings` and
     curves client methods (shared with #12, whichever lands first)
   - Strava-only: the existing activity list
   - `get_profile_evidence(months)` with the profile mismatch list

3. **Build flow and habits (S).** `build_athlete_profile` guidance, the
   save-time checklist.
4. **After #9:** `start_consultation` includes the profile output directly.
   **After #11:** onboarding runs `build_athlete_profile`.

A user data deletion path (see Privacy) should exist before the remote server
takes more users. It is tracked separately.

## How to verify

- Unit tests:
  - a section update leaves other sections byte-identical;
  - hand edits survive (unknown sections, missing metadata, text before the
    first heading);
  - an `##` inside content is demoted;
  - the cap is enforced;
  - `base` mismatch is rejected with the current body;
  - the stored file and the read output contain no stats.
- Concurrency (on #8's harness with the `post-commit` race hook):
  - updates to two different sections, where one loses the push race, both
    land;
  - two `append`s to Race results both land.
- Evidence, with stubbed clients:
  - with an intervals.icu key, no Strava request is made;
  - Strava-only: 12 months uses only activity-list requests (at most 5);
  - `read_athlete_profile` makes no data API calls;
  - a rate limit returns a clear "evidence unavailable" message.
- Integration: the profile is per user, and user A's read never shows user
  B's data.
- Manual: run `build_athlete_profile` with a test account and synthetic or
  stubbed data (never a real athlete's data during development); check that the
  evidence phase raises at least the contradictions a human coach would
  spot, and that a fresh conversation afterwards states race results and
  constraints without reading any notes.
