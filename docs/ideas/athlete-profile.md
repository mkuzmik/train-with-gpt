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
has and hasn't worked, gear. These end up scattered across daily notes, so
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

- **Stated** sections hold what the athlete told the coach or confirmed.
  They are stored in the training repo and change only through
  `update_athlete_profile`, with the athlete's confirmation.
- **Computed** sections are derived from Strava and intervals.icu by the
  server, with no model involved. They are **not stored in the repo**. The
  server computes them when the profile is read and appends them to the
  output, with a short-lived cache.

Not storing computed data is a change from the first draft. Reasons:

1. **Strava's API terms.** The Strava API Agreement says no Strava Data may
   stay in a cache longer than seven days, and it must be deleted after the
   athlete deauthorizes the app. A git repo keeps every version forever, so
   derived volumes, best efforts and gear mileage written there would break
   both rules.
2. **Freshness.** Computing on read means the computed part is never stale.
   A stored copy would be out of date between refreshes.
3. **Commit noise and write load.** Storing it would mean a commit and push
   on every refresh, possibly on every `start_consultation`: more work on a
   cold start, and more chances to lose a push race under #8.
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
| Tests | stated | performance tests: lab VO2max/thresholds, field tests (see privacy) | 500 |
| Health | stated | current niggles, recent illness, relevant injury history, as coaching status (not raw medical values) | 600 |
| Constraints | stated | available days and hours, equipment, weekly limits, life load | 600 |
| What works | stated | responses to blocks, tapers, fueling, heat. This is also the home for the "response profile" idea (D5) in `science-based-coaching.md` | 800 |
| Preferences | stated | training style, how they like to be coached | 400 |
| Current fitness | computed | 4- and 12-week volume per sport, longest session, race-flagged activities, fitness/fatigue/form if available | - |
| Thresholds and baselines | computed | HR zones, FTP; resting HR, HRV band, sleep, weight trend if available | - |
| Gear | computed | shoes and bikes with distance | - |
| Checks | computed | stale sections, conflicts between data and stated facts, missing sections | - |

"Current block" (phase, focus, key sessions) is left out. It changes weekly,
which would make the profile the busiest file in the repo. It belongs to a
plan (the parked `save_training_plan` idea in `intervals-icu.md`, or the
calendar tool in `more-training-data.md`). Until then it stays in goals.

### What the computed sections can use

Both data paths are covered. On the remote (OAuth) path, activities always
come from Strava, even when an intervals.icu key is connected. intervals.icu
is used there for wellness only (`_get_active_data_client` and
`_get_wellness_client` in `server.py`). The personal path uses intervals.icu
for everything.

| Field | Strava-only remote user | Remote user + intervals.icu key | Personal path (intervals.icu) |
|---|---|---|---|
| Volume per sport, longest session | `GET /athlete/activities`: 1–2 requests for 12 weeks (200 per page) | same (Strava) | `GET /athlete/0/activities` |
| Race-flagged activities | `workout_type` on the summary: 1 = run race, 11 = ride race. These values are not officially documented. | same | activity name/type; `RACE_*` calendar events later |
| Best efforts | `best_efforts` is only on `DetailedActivity`: one request per activity, runs only. Fetch only for race-flagged runs, cache the result for 7 days at most | same | `pace-curves` (needs a new client method, #12) |
| Fitness / fatigue / form | **not in the Strava API.** Omit, or estimate from `suffer_score` and label it as an estimate (#12 recommendation 3) | `ctl`, `atl` from wellness | wellness |
| HR zones, FTP | `GET /athlete/zones` (already used), `ftp` on `GET /athlete` | same | `sport-settings` (new client method, #12) |
| Threshold pace | not available | not available from the remote path | `sport-settings` |
| Resting HR, HRV, sleep | not available | wellness (`restingHR`, `hrv`, `sleepSecs`) | wellness |
| Weight | single current `weight` on `GET /athlete` | wellness trend | wellness trend |
| Gear | `shoes[]`, `bikes[]` with `distance` on `GET /athlete` (the `profile:read_all` scope, already granted) | same | `gear.json` (new client method, #12) |

Everything in the Strava-only column uses client methods that already exist
(`get_athlete`, `get_all_activities`, `get_athlete_zones`,
`get_activity_details`, `IntervalsClient.get_wellness`). So the minimal
computed set does not wait for #12. The aggregation code (weekly totals,
longest session, baseline bands) should be one shared module that #12's
`get_training_summary`, `get_fitness_form` and `get_gear` reuse, so the two
proposals don't grow two versions of the same math.

### Rate limits

Strava limits are per application and shared by all users: 100 read requests
per 15 minutes and 1,000 per day (200 and 2,000 overall).

One computed refresh for a Strava-only user costs about 3–5 requests:

- `/athlete`: 1
- the activity list for 12 weeks: 1–2
- `/athlete/zones`: 1, and it is already fetched per client
- detail for new race-flagged runs: 0–2, then cached

That is 20–30 refreshes per 15-minute window if nothing else runs. Rules:

- Cache computed results per user for 6 hours in `store.db`, not in the repo.
  An explicit `refresh_athlete_profile` bypasses the cache.
- Share the activity fetch with `start_consultation` (#9 already fetches 14
  days of activities and 4 weekly totals): fetch 12 weeks once and derive
  both from it.
- Never fetch per-activity detail across a whole range, only for race-flagged
  runs that are not in the cache.
- On a 429, return the stated sections plus "computed data unavailable (rate
  limit)" in Checks, instead of failing the read.
- Clear the cache when the user disconnects (Strava's deletion rule).

intervals.icu has no published rate limit and uses per-user keys. One
wellness call covers ctl/atl, resting HR, HRV, sleep and weight.

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
   - `base`: optional, a short hash of the section body the model read. If
     the section changed since then, the server rejects the update and
     returns the current body so the model can merge. `append` needs no
     `base`.
   - Content over the section's cap is rejected, with a request to move
     detail to notes.
   - An `##` heading inside `content` is demoted to `###`.
   - The tool description says to call it only after the athlete confirms
     the change.
3. **`refresh_athlete_profile`**: recomputes the computed sections, bypassing
   the cache, and returns *suggestions* for stated sections, e.g. "a
   race-flagged run on <date> isn't in Race results; add it?". Suggestions are
   never applied automatically. It writes nothing to the repo.
4. **`profile_interview`**: guidance only, like `discuss_goals`. It tells the
   model to take the "missing" and "stale" items from Checks and ask about
   them one at a time, then confirm and save each section. #11 reuses it.
   (It could also be a paragraph in `start_consultation`'s guidance. It is a
   separate tool only so that #11 and the athlete can call it by name.)
5. **Save-time checklist**: `save_consultation_notes` ends its success output
   with a one-line checklist: "New result, health change, availability
   change, or something that worked? Propose a profile update."
6. **Checks** (in the read output, no separate tool):
   - stale sections, using the thresholds below;
   - conflicts, e.g. a computed best effort faster than the stated PB for
     that distance, or a race-flagged activity missing from Race results;
   - missing sections.

   The coach mentions these, but doesn't have to act on them every day.

Staleness thresholds (days since `as of`):

| Section | Threshold |
|---|---|
| Constraints | 90 |
| Health | 30 when it lists a current issue, otherwise 180 |
| What works | 180 |
| Preferences | 365 |
| Tests | 365 |
| Background | never |
| Race results | never; use the missing-race conflict check instead |

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

What `read_athlete_profile` appends after the stored part (not stored):

```markdown
## Current fitness (computed 2026-09-25 from Strava)
- Run: last 4 wk 42 km/wk (4.4 h), last 12 wk 38 km/wk. Longest run 24 km (2026-09-14).
- Ride: last 4 wk 1.8 h/wk (commutes).
- Fitness/form: not available (no intervals.icu connection).

## Thresholds and baselines (computed)
- Strava HR zones: Z2 128–145, Z4 160–172 bpm. FTP not set.
- Weight (Strava profile): 70 kg. Resting HR/HRV/sleep: connect intervals.icu to see them.

## Gear (computed)
- Shoes: Trainer A 612 km, Racer B 180 km.

## Checks
- Stale: Constraints (as of 2026-01-10, over 90 days).
- Conflict: race-flagged run "Autumn 10k" on 2026-09-07 is not in Race results.
- Conflict: best effort 10 km 44:30 on 2026-09-07 beats the stated 10 km PB 45:05.
```

### Goals vs profile

Goals keep the target: event, date, target time, why it matters, and, until a
plan file exists, the current block. The profile keeps facts about the
athlete. When the profile ships:

- `save_goals` and `discuss_goals` descriptions stop asking for current
  state and constraints, and point to `update_athlete_profile` instead.
- The backfill flow (below) moves those facts out of the existing goals text,
  with the athlete's confirmation.

### Privacy

The training repo is private, but it is not personal on the remote path. It
is one shared repo (`TRAINING_REPO_URL`) holding every user's files, readable
by whoever operates the server and anyone with access to that repo. Git
history keeps every version, so "delete" means rewriting history. Notes
already contain health remarks, but a profile concentrates them into one
dense summary. Health data is also a special category under GDPR.

Rules:

- **Health** holds coaching-relevant status ("calf tightness, reduced hill
  volume"), not diagnoses in clinical detail or raw lab values.
- **Blood work is not stored in the profile.** If the athlete wants it
  recorded, it goes into a note at their explicit request. The profile may
  say "blood work discussed on <date>, see note". Performance tests (lab
  VO2max, thresholds, field tests) are fine in Tests.
- The onboarding landing page (#11) says what is stored and where.
- A way to delete a user's profile (and notes) is needed before more users
  join. It is out of scope here but listed as a dependency. Deleting only the
  latest file is not enough because of git history.

### Backfilling from history

For existing athletes with many notes. This is a guided flow, not a single
model pass over everything:

1. Run `refresh_athlete_profile` for data and suggestions.
2. Build the profile section by section, not note by note. For each section,
   use `search_consultation_notes` with section keywords (race, PB, injury,
   pain, availability, taper, fueling) plus the current goals file, rather
   than reading every note in full. Reading ~100 notes whole would cost tens
   of thousands of tokens and bury the facts.
3. Resolve conflicts with fixed rules and show them to the athlete:
   - **State** (health, constraints, preferences): the newest dated statement
     wins. Older ones are dropped, not merged.
   - **Race results**: one row per event. If notes disagree on the time,
     prefer the activity data (Strava/intervals.icu), then the latest note,
     and show both values to the athlete.
   - **PBs**: a PB is a race result, never an inferred training effort, so
     the best-effort conflict check stays a Check, not an automatic PB.
   - Anything unresolved becomes a question in the interview.
4. The athlete confirms each section. Each confirmed section is saved right
   away with `source: note:<date>` of the winning statement. This makes the
   backfill resumable, as #11 needs for onboarding.

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

## Decisions for the owner (with recommendations)

1. **Keep computed data out of the repo?** Recommended: yes, compute on read
   and cache for 6 hours in `store.db`. The alternative is committing a
   snapshot on explicit refresh only, which accepts the Strava terms risk.
2. **Current block in the profile?** Recommended: no. Keep it in goals until
   a plan file or calendar tool exists.
3. **Blood work?** Recommended: never in the profile, only in notes on
   explicit request. Health holds coaching status only.
4. **File path?** Recommended: `athlete/<user_id>.md` and
   `athlete-profile.md` on the personal path, to avoid clashing with the
   `profiles/` identity-mapping idea.
5. **When are computed sections computed?** Recommended: on every read,
   through the 6-hour cache, and fresh on explicit refresh. Detail fetches
   only for race-flagged runs.
6. **Strava-only fitness/form?** Recommended: omit in v1 and say "connect
   intervals.icu". Add the `suffer_score` estimate later with #12, clearly
   labelled.
7. **Stale thresholds?** Recommended: the table above.
8. **`base` check on `replace`?** Recommended: yes, optional, but the tool
   description asks the model to pass it.
9. **Separate `profile_interview` tool?** Recommended: yes, guidance only,
   since #11 references it by name.

## Rollout

Hard dependency: #8 merged. Phase 1 adds `git_update_file` on top of it.

1. **Format and writes (M, 2–3 days with tests).**
   - `user_scoped_profile_file`, the parser/splicer, `git_update_file`
   - `read_athlete_profile` (stated part and Checks for stale/missing),
     `update_athlete_profile`
   - a line in `start_consultation`'s guidance to call it first
   - updated `save_goals`/`discuss_goals` descriptions
2. **Computed sections (S–M).**
   - a shared aggregation module plus the Strava-only fields, using existing
     client methods
   - intervals.icu wellness fields
   - the 6-hour cache in `store.db`, cleared on disconnect
   - conflict checks and `refresh_athlete_profile`

   Independent of #12. #12 later reuses the module and adds `sport-settings`,
   `gear.json` and `pace-curves` for intervals.icu users.
3. **Habits (S).** `profile_interview`, the save-time checklist.
4. **Backfill guidance (S).** Mostly prompt text; expensive in tokens for the
   one run.
5. **After #9:** `start_consultation` includes the profile output directly.
   **After #11:** onboarding uses phases 1–3.

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
- Computed: with stubbed Strava, a 12-week refresh uses at most 5 requests
  and a second read within 6 hours uses none; a 429 still returns the stated
  sections.
- Integration: the profile is per user, and user A's read never shows user
  B's data.
- Manual: after backfill, a fresh conversation states race results and
  constraints without reading any notes, and the start-of-consultation
  context is under the budget above.
