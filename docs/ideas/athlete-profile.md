# Idea: a living athlete profile (proposal, for review)

Not implemented. This proposes an athlete profile: a short, always-current
document about who the athlete is right now, loaded at the start of every
consultation and kept up to date from data, interviews and results.

Depends on: #8 (notes sync fix) for all writes. Works best with #9
(`consultation-context.md`, assembled `start_consultation`). Shares
computation code with #12 (`more-training-data.md`) but does not need its
tools. #11 (`new-user-onboarding.md`) builds on it.

## Problem

The server keeps two kinds of memory today:

- **Goals** (`goals.md` on the personal path, `goals/<user_id>.md` for
  OAuth users; see `user_scoped_goals_file` in `helpers.py`): one document,
  replaced wholesale by `save_goals`.
- **Notes** (`notes/` or `notes/<user_id>/`): one immutable, timestamped file
  per `save_consultation_notes` call, so in effect an append-only log.

Neither holds the durable facts a coach needs every time: race results and
PBs, current fitness, baselines (resting HR, HRV range, usual sleep, weight
trend), test results, injury history, weekly availability and limits, what
has and hasn't worked. These end up scattered across daily notes, so
the coach has to rediscover them each consultation and often doesn't (see
`consultation-context.md`).

Goals are not the right place either. They change on a different cadence,
and mixing the two makes both harder to keep current. Today they already
overlap: the `save_goals` description asks for "goals, current state,
constraints, and context", and the `discuss_goals` example summary includes
a current 5k best, an injury history and weekly availability. Once the
profile exists, those facts move there (see "Goals vs profile" below).

## Proposed solution

### Two kinds of sections

- **Stated** sections hold durable facts about the athlete: what they told
  the coach, or what the coach found in the data and the athlete confirmed.
  They are stored in the training repo and change only through
  `update_athlete_profile`, with the athlete's confirmation.
- **Computed** sections are rolling numbers the server derives from
  intervals.icu (or, without it, from the Strava activity list), with no
  model involved. They are **not stored in the repo**. The server computes
  them when the profile is read and appends them to the output, with a
  short-lived cache.

The line between them: a fact that stays true until something happens is
stated; a number that moves every week is computed. Anything that changes
with every session (gear mileage, last run, today's form) is neither: it
belongs to the data tools, not the profile.

- "10k PB 44:30, Autumn 10k, 2026-09-07" is **stated**. It is a result, it
  stays true until the next PB, and it is stored in Race results even when it
  was first spotted in the activity data. Strava's cache rules don't apply to
  it: it is the athlete's own fact, confirmed by them, not a copy of API data.
- "Last 4 weeks: 42 km/week, fitness (CTL) 48, resting HR 49" is
  **computed**. It is out of date a few days later, so storing it would only
  create stale copies.

Not storing computed numbers:

1. **Freshness.** Computing on read means the computed part is never stale.
   A stored copy would be out of date between refreshes.
2. **Commit noise and write load.** Storing it would mean a commit and push
   on every refresh, possibly on every `start_consultation`: more work on a
   cold start, and more chances to lose a push race under #8.
3. **Strava's API terms**, where Strava is the source: raw Strava data may
   not stay in a cache longer than seven days and must be deleted after the
   athlete deauthorizes. A git repo keeps every version forever.
4. **Simpler format.** The stored file holds only stated sections, so there
   is no "never hand-edit this block" rule to enforce.

The cost is that the profile on GitHub shows only stated sections.

### Sections

Target: stated part at most about 5,000 characters (~1,300 tokens), computed
part at most about 1,500 characters (~400 tokens). Details stay in notes.

| Section | Kind | Content | Char cap |
|---|---|---|---|
| Background | stated | years training, sports, history | 600 |
| Race results | stated | table: date, event, distance, time, notes. Keep the best per distance plus the last 12 months; older rows move to notes | 1,200 |
| Tests | stated | performance tests: lab VO2max/thresholds, field tests | 500 |
| Health | stated | current niggles, recent illness, relevant injury history, and recurring health patterns that change coaching, e.g. "ferritin drops below 40 without supplementation" (see Privacy) | 600 |
| Constraints | stated | available days and hours, equipment, weekly limits, life load | 600 |
| What works | stated | responses to blocks, tapers, fueling, heat. This is also the home for the "response profile" idea (D5) in `science-based-coaching.md` | 800 |
| Preferences | stated | training style, how they like to be coached | 400 |
| Current fitness | computed | 4- and 12-week volume per sport, longest session, race-flagged activities, fitness/fatigue/form (intervals.icu) | - |
| Thresholds and baselines | computed | intervals.icu only: HR zones, threshold pace, FTP, resting HR, HRV band, sleep, weight trend | - |
| Checks | computed | stale sections, conflicts between data and stated facts, missing sections | - |

"Current block" (phase, focus, key sessions) is left out. It changes weekly,
which would make the profile the busiest file in the repo. It stays in goals
until a plan file exists (the parked `save_training_plan` idea in
`intervals-icu.md`, or the calendar tool in `more-training-data.md`). If a
long-running pattern emerges from it (e.g. "responds well to 3:1 blocks"),
that goes to What works.

Gear is left out entirely, stored or computed. Its mileage changes with
every session, and the profile holds nothing that changes that often. Gear
questions go to a gear tool (#12's `get_gear`), not the profile.

### Data sources: intervals.icu first, no new Strava calls

Owner decision: base the profile on intervals.icu as much as possible, and
pull no Strava data beyond what the server already fetches (privacy policy
concerns; Strava's derived metrics such as `suffer_score` are not
meaningful enough to coach on).

So:

- **intervals.icu connected** (personal path, or a remote user with a key):
  everything computed comes from intervals.icu, **including activities**.
  This changes today's remote-path rule, where activities always come from
  Strava and intervals.icu is used for wellness only
  (`_get_active_data_client` / `_get_wellness_client` in `server.py`). For
  the profile only, the server prefers intervals.icu when a key is connected.
- **Strava only**: the computed part uses only the activity list the server
  already fetches for `get_activities`. No `/athlete`, no gear, no
  `best_efforts` detail fetches, no `suffer_score`. Fitness/form and
  baselines show "connect intervals.icu to see this".

| Field | Strava-only remote user | intervals.icu connected (either path) |
|---|---|---|
| Volume per sport, longest session | activity list (already fetched) | `GET /athlete/0/activities` |
| Race-flagged activities | `workout_type` on the summaries in that list (1 = run race, 11 = ride race; community-documented) | activity type/name; `RACE_*` calendar events later |
| Best efforts at standard distances | not available | `pace-curves` / `power-curves` (new client method, shared with #12) |
| Fitness / fatigue / form | not available | `ctl`, `atl` from wellness |
| HR zones, threshold pace, FTP | not available in the profile | `sport-settings` (new client method, shared with #12) |
| Resting HR, HRV, sleep, weight | not available | wellness (`restingHR`, `hrv`, `sleepSecs`, `weight`) |

### Request costs and caching

- **Strava only:** one read uses 1–2 list requests for 12 weeks (200 per
  page), and shares them with `start_consultation` (#9 already fetches 14
  days and 4 weekly totals: fetch 12 weeks once and derive both). The build
  flow's 12-month evidence pass is 3–5 list requests, once per athlete.
  Strava limits are per application and shared by all users (100 reads per
  15 minutes, 1,000 per day), so there are still no per-activity fetches.
- **intervals.icu:** per-user keys and no published limit. A read is about
  3–4 calls (activities, wellness, sport-settings, curves).
- Cache computed results per user for 6 hours in `store.db`, not in the repo.
  An explicit `refresh_athlete_profile` bypasses the cache.
- On a rate limit or API error, return the stated sections plus "computed
  data unavailable" in Checks instead of failing the read.
- Clear the cache when the user disconnects.

### Tools

1. **`read_athlete_profile`**: returns stated sections, then computed
   sections, then Checks. Section metadata is shown in compact form. Each
   section's short id (e.g. `health`) is shown so the model can pass it to
   `update_athlete_profile`. Until #9 lands, `start_consultation`'s guidance
   tells the model to call it first. After #9, `start_consultation` includes
   the output directly.
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
3. **`refresh_athlete_profile(months=3)`**: recomputes the computed sections,
   bypassing the cache, and returns *evidence* the model can check stated
   facts against. With `months=12` (the build flow) it returns a longer view:
   - weekly volume per sport and its range, the biggest weeks, and training
     gaps of 7+ days (often injury or illness);
   - race-flagged activities with date, distance and time;
   - best efforts at standard distances (intervals.icu);
   - fitness (CTL) peaks and troughs, and resting HR/HRV/sleep bands
     (intervals.icu);
   - *suggestions* for stated sections, e.g. "a race-flagged run on <date>
     isn't in Race results; add it?". Suggestions are never applied
     automatically. It writes nothing to the repo.
4. **`build_athlete_profile`**: guidance only, like `discuss_goals`. It
   walks the model through the three-phase build below. #11 (onboarding) and
   the backfill for existing athletes both use it, and the athlete can ask
   for it by name ("let's rebuild my profile").
5. **Save-time checklist**: `save_consultation_notes` ends its success output
   with a one-line checklist: "New result, health change, availability
   change, or something that worked? Propose a profile update."
6. **Checks** (in the read output, no separate tool): stale sections,
   conflicts (e.g. an intervals.icu best effort faster than the stated PB for
   that distance, or a race-flagged activity missing from Race results) and
   missing sections. The coach mentions these, but doesn't have to act on
   them every day.

### Building the profile

The profile is only useful if it is right, so building it is a
conversation, not a form. Three phases:

1. **Interview.** The coach asks about each stated section in turn:
   background, races and PBs, tests, health (current issues, history,
   recurring patterns), constraints, what has and hasn't worked,
   preferences. Open questions first, then specifics. Nothing is saved yet;
   the coach keeps a working list of claims ("10k PB ~45:00 last autumn",
   "usually 5 days a week", "calf issues on hills").
2. **Evidence.** The coach calls `refresh_athlete_profile(months=12)` and,
   for existing athletes, `search_consultation_notes` per section (race, PB,
   injury, pain, availability, taper, fueling) plus the current goals file,
   instead of reading every note. It then sorts each claim:
   - **confirmed**: the data agrees ("10k 45:05 on 2025-10-12");
   - **contradicted**: the data says otherwise ("you said 5 days a week;
     the last 12 months average 3.4, with a 5-week gap in March");
   - **not in the data**: tests, health, preferences.
   It also collects what the data shows that the athlete didn't mention: a
   faster best effort, a race not listed, a big block before a good result.
3. **Discussion.** The coach goes through contradictions and new findings
   one at a time and asks, rather than overrules: the athlete may know why
   (a watch left at home, a race run as training, a deliberate break). Then
   it proposes each section's final text, the athlete confirms or corrects,
   and it is saved right away. Saving per section makes the build
   resumable, which #11 needs for onboarding.

Fixed rules for conflicts:

- **State** (health, constraints, preferences): the newest dated statement
  wins, including the athlete's answer in phase 3. Older ones are dropped,
  not merged.
- **Race results**: one row per event. If sources disagree on the time,
  prefer the activity data, then the athlete, then the latest note, and show
  the values to the athlete.
- **PBs** are race results, never inferred from training efforts. A faster
  training best effort is raised in the discussion and later as a Check, not
  saved as a PB.
- Anything still unresolved is left out and noted in the section ("5k PB:
  athlete unsure, not in the data").

### Keeping it current

Three small mechanisms, so the profile doesn't rot after the build:

- **Staleness thresholds.** Each section has a date (`as of`). When a
  section is older than its threshold, `read_athlete_profile` lists it under
  Checks as stale, so the coach knows to ask "are you still training 5 days
  a week?" at a natural moment. Nothing is changed automatically.

  | Section | Stale after |
  |---|---|
  | Constraints | 90 days |
  | Health | 30 days when it lists a current issue, otherwise 180 |
  | What works | 180 days |
  | Preferences, Tests | 365 days |
  | Background | never |
  | Race results | never; the missing-race Check covers it |

- **`base` check.** Protects against two chats editing the same section at
  once. The model passes a short fingerprint of the section as it read it;
  if the section has changed since (another session saved something), the
  update is rejected and the current text is returned so the model can
  merge instead of silently overwriting it.
- **Save-time checklist and Checks**, above, prompt small updates during
  normal consultations.

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

## What works
_as of 2026-03-02 · interview_
- Two-week taper with one short sharp session in race week.
- Long runs over 2 h need 60 g/h carbohydrate or the last 30 min fall apart.

## Preferences
_as of 2026-01-10 · interview_
- Wants reasons behind sessions; prefers effort (RPE) targets over pace on hills.
```

What `read_athlete_profile` appends after the stored part (not stored), for
a user with intervals.icu connected:

```markdown
## Current fitness (computed 2026-09-25 from intervals.icu)
- Run: last 4 wk 42 km/wk (4.4 h), last 12 wk 38 km/wk. Longest run 24 km (2026-09-14).
- Ride: last 4 wk 1.8 h/wk (commutes).
- Fitness (CTL) 48, fatigue (ATL) 55, form -7.

## Thresholds and baselines (computed)
- Run: LTHR 172 bpm, threshold pace 4:25/km. Z2 128–145 bpm.
- Resting HR 48–51 (30-day band), HRV 62–74 ms, sleep 7.1 h avg. Weight 70.2 kg, stable.

## Checks
- Stale: Constraints (as of 2026-01-10, over 90 days).
- Conflict: race-flagged run "Autumn 10k" on 2026-09-07 is not in Race results.
- Conflict: best effort 10 km 44:30 on 2026-09-07 beats the stated 10 km PB 45:05.
```

For a Strava-only user, Current fitness shows volume, longest session and
race-flagged activities; the rest says "connect intervals.icu to see this".

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
- **Store computed sections in the repo.** Readable on GitHub, but it
  conflicts with Strava's 7-day cache and deletion rules, adds a commit per
  refresh, and goes stale (see above).
- **Let the model rewrite the whole profile after every consultation.**
  Simple, but it drifts, loses details and races with concurrent sessions.

## Decisions

Owner decisions (2026-09-27):

1. **Stated vs computed.** Durable facts, including PBs and race results,
   are stored (stated), even when first found in the data. Rolling numbers
   (recent volume, fitness/form, baselines) are computed on read with a
   6-hour cache in `store.db` and never stored.
2. **Current block** stays in goals. Long-running patterns from it can move
   to What works.
3. **Blood work:** recurring patterns that matter for coaching go in Health
   (e.g. low ferritin without supplementation); raw panels and single tests
   go to notes on request.
4. **Path:** one file per user, `athlete/<user_id>.md`
   (`athlete-profile.md` on the personal path).
5. **Data sources:** intervals.icu first, including activities when a key is
   connected. No new Strava data: the Strava-only profile uses only the
   activity list already fetched. No `suffer_score`.
6. **No per-session data in the profile:** no gear or anything else that
   changes with every training.
7. **Building the profile** is three phases: interview, evidence from a
   12-month data pass, then discussion of what the data confirms or
   contradicts (`build_athlete_profile`).

Adopted as proposed (the owner can still change them): the staleness
thresholds and the optional `base` check (see "Keeping it current").

Still open:

- Using intervals.icu activities for the profile on the remote path while
  other tools keep using Strava could show slightly different numbers in
  the same consultation (e.g. a manual Strava entry not synced to
  intervals.icu). Recommended: accept it for v1 and say the source in each
  computed heading; revisit if #12 moves all remote tools to intervals.icu.

## Rollout

Hard dependency: #8 merged. Phase 1 adds `git_update_file` on top of it.

1. **Format and writes (M, 2–3 days with tests).**
   - `user_scoped_profile_file`, the parser/splicer, `git_update_file`
   - `read_athlete_profile` (stated part and Checks for stale/missing),
     `update_athlete_profile`
   - a line in `start_consultation`'s guidance to call it first
   - updated `save_goals`/`discuss_goals` descriptions
2. **Computed sections and evidence (M).**
   - a shared aggregation module (weekly totals, longest session, gaps,
     baseline bands) that #12 reuses
   - intervals.icu: activities, wellness, and the new `sport-settings` and
     curves client methods (shared with #12, whichever lands first)
   - Strava-only: volume and race flags from the existing activity list
   - the 6-hour cache in `store.db`, cleared on disconnect
   - conflict checks and `refresh_athlete_profile(months)`
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
  - the stored file never contains computed sections.
- Concurrency (on #8's harness with the `post-commit` race hook):
  - updates to two different sections, where one loses the push race, both
    land;
  - two `append`s to Race results both land.
- Computed, with stubbed clients:
  - with an intervals.icu key, no Strava request is made for the profile;
  - Strava-only: a read makes only activity-list requests (at most 2 for 12
    weeks, at most 5 for `months=12`), and a second read within 6 hours
    makes none;
  - a rate limit still returns the stated sections.
- Integration: the profile is per user, and user A's read never shows user
  B's data.
- Manual: run `build_athlete_profile` with a real athlete; check that the
  evidence phase raises at least the contradictions a human coach would
  spot, and that a fresh conversation afterwards states race results and
  constraints without reading any notes.
