# Idea: expose more training data to the coach (proposal, for review)

Not implemented. This surveys what else Strava API v3 and intervals.icu API v1
offer, maps it to coaching use cases, and proposes a small set of tools and
shared computations. Other proposals depend on it: `athlete-profile.md` (#10)
for its computed sections, `science-based-coaching.md` (#13) for its load and
recovery checks, `consultation-context.md` (#9) for weekly totals and
wellness vs baseline, and `new-user-onboarding.md` (#11) for the day-one data
baseline. The data-source decision it rests on is analysed in
`data-source-policy.md`.

Checked against public docs on 2026-09-25: the intervals.icu OpenAPI spec
(`https://intervals.icu/api/v1/docs`), the Strava API reference, rate-limit
and authentication pages, and the Strava API Agreement and API Policy (both
effective 2026-06-01). Claims about current code refer to `origin/main`.
Fields the Strava reference does not list but the API returns in practice are
marked *(undocumented)*.

## Data-source policy (read first)

The Strava API Policy effective 2026-06-01 bars operating "any MCP Server
... that exposes ... Strava Data" (§5.16(b)) and using Strava data with an AI
application, including "ingestion into a context window" (§5.3). The only
exception is Strava's own MCP (§3.5). Read literally, today's hosted Strava
path already conflicts with this. The full analysis, with clause quotes, a
comparison of seven options and the owner's decisions, is in
**[`data-source-policy.md`](data-source-policy.md)**. This is not legal
advice.

What this proposal assumes, following that doc's recommendation:

- **This server's data comes from intervals.icu only**, on both stdio and
  hosted. Every tool below is intervals.icu-only. No new Strava reads,
  processing, storage or caching.
- **Strava data reaches Claude through the official Strava MCP**, which the
  user connects alongside this server. This server never calls it, proxies
  it or ingests its output. Tool descriptions say "from intervals.icu" so the
  model can tell the two apart.
- **Hosted login moves off Strava** (intervals.icu API key, later OAuth).
  That work is a separate change, tracked in `data-source-policy.md`. Until
  it lands, hosted users without an intervals.icu key keep today's frozen
  Strava tools and get none of the new ones.
- **Strava-synced activities are stubs on intervals.icu.** The tools must
  handle stubs gracefully, and say how to fix it: sync the device directly
  to intervals.icu, or import the Strava archive.
- **Garmin attribution** (intervals.icu API terms §1.1, Garmin API brand
  guidelines): output that shows Garmin-sourced activity data or data
  derived from it names "Garmin [device model]" (from `device_name`).

## Coaching use cases

- **Daily readiness.** Go/no-go for hard sessions from HRV, resting HR and
  sleep *relative to the athlete's own baseline* (mean and normal range), not
  raw nightly values.
- **Weekly volume.** Per sport and week: count, distance, time, load, longest
  session, without summing activity lists by hand.
- **Load and fatigue.** Fitness, fatigue and form (CTL/ATL/TSB) and ramp rate
  for build and taper planning.
- **Body weight trends.** Rolling average and weekly change; flag short-term
  drops that point to dehydration or under-fuelling.
- **Race targets.** Best efforts, pace/power curves and current thresholds.
- **Gear.** Shoe mileage for rotation and race-shoe decisions.
- **Illness and injury.** Structured subjective fields (`soreness`, `fatigue`,
  `injury`, `comments`) and SICK/INJURED calendar markers.
- **Conditions.** Temperature and feels-like to explain HR drift.
- **Plan vs executed.** Planned workouts next to what was done.
- **Reliability.** When wellness can't be read, say why.

## What the server does today (verified on `origin/main`)

- **17 tools.** Activities: `get_activities`, `analyze_activity`,
  `analyze_lap`. Wellness: `get_sleep_data`, `get_hrv_data`,
  `get_resting_heart_rate` (each capped at 30 days). The rest are notes,
  goals, date and guidance.
- **Data source per mode.** stdio/personal: everything from intervals.icu with
  the configured key. Remote (OAuth): activities always from Strava
  (`_get_active_data_client`), even when the user connected an intervals.icu
  key; wellness from intervals.icu only via `_get_wellness_client`.
- **`IntervalsClient.get_wellness(oldest, newest)`** returns full records (no
  `fields=` parameter yet); the three tools keep one field each and drop the
  rest.
- **`get_activities`** shows type, distance, time, pace/speed, elevation,
  HR, power, cadence and `average_temp` *(undocumented on Strava)*. It does
  not show the activity name, load, RPE or gear.
- **Strava scopes:** `activity:read_all,activity:read,profile:read_all`.
- **Zones cache is ineffective:** `StravaClient.zones_cache` is per instance,
  and a new `StravaClient` is built per request, so it never hits.

### `_get_wellness_client` fallback (corrected)

Two different failure paths, both misleading:

1. **Secret box not configured, or decrypt returns `None`** (e.g. key
   rotated): falls back to the user's `StravaClient`, and the wellness tool
   answers with `NO_WELLNESS_DATA_MESSAGE`: "Strava has no wellness data. To
   add it, connect intervals.icu ...". A user who *did* connect is told to
   connect.
2. **401/403 from intervals.icu** (key revoked or regenerated): this does
   *not* fall back to Strava. The `IntervalsClient` raises, and the handler
   returns "❌ Error: ... Make sure INTERVALS_API_KEY is configured", which
   names an environment variable remote users have never seen.

The earlier draft (and #9) listed the 401 case under the fallback; it's the
second path. Fix both in one change, done once for #9 and this proposal: say
"no key connected", "key stored but unreadable, reconnect", or "intervals.icu
rejected the key, reconnect" and log the reason (never the key).

## API survey

### intervals.icu (checked against the OpenAPI spec)

Auth: HTTP Basic, username `API_KEY`, password the key (full account access,
read and write), or an OAuth bearer token. The spec publishes **no rate
limit**. Load is per user key, so the main concern is politeness: no N+1
loops, use `fields=` to trim payloads.

| Data | Endpoint | Useful fields |
|---|---|---|
| Daily wellness | `GET /athlete/0/wellness?oldest=&newest=&fields=` (`fields` also drops nulls) | `weight`, `bodyFat`, `abdomen`, `restingHR`, `hrv`, `hrvSDNN`, `baevskySI`, `avgSleepingHR`, `sleepSecs`, `sleepScore`, `sleepQuality`, `readiness`, `vo2max`, `spO2`, `respiration`, `steps`, `kcalConsumed`, `carbohydrates`, `protein`, `fatTotal`, `hydration`, `hydrationVolume`, `soreness`, `fatigue`, `stress`, `mood`, `motivation`, `injury`, `systolic`, `diastolic`, `bloodGlucose`, `lactate`, `menstrualPhase`, `menstrualPhasePredicted`, `comments`, `locked`, **`ctl`, `atl`, `rampRate`, `ctlLoad`, `atlLoad`**, `sportInfo[]` (per sport `eftp`, `wPrime`, `pMax`) |
| Which fields are tracked | `GET /athlete/0` | `icu_wellness_keys`, plus per-source lists: `icu_garmin_wellness_keys`, `polar_wellness_keys`, `oura_wellness_keys`, `whoop_wellness_keys`, `google_wellness_keys`; `icu_form_as_percent`, `icu_resting_hr`, `icu_weight` |
| Activities | `GET /athlete/0/activities?oldest=&newest=&fields=&limit=` | `name`, `race`, `icu_training_load`, `hr_load`, `pace_load`, `power_load`, `trimp`, `icu_intensity`, `icu_atl`, `icu_ctl`, `icu_rpe`, `feel`, `session_rpe`, `decoupling`, `icu_efficiency_factor`, `polarization_index`, `compliance`, `gear` (`id`, `name`, `distance`), `calories`, `carbs_used`, `carbs_ingested`, `average_weather_temp`, `average_feels_like`, `average_wind_speed`, `icu_rolling_ftp`, `icu_zone_times`, `icu_hr_zone_times`, `pace_zone_times`, `average_stride`, `average_stance_time`, `average_vertical_oscillation`, `strava_id`, `source` |
| Curves | `GET /athlete/0/pace-curves{ext}?curves=&type=&gap=`, `power-curves{ext}`, `hr-curves{ext}`; per date range `activity-pace-curves{ext}?oldest=&newest=&distances=&gap=` (also `activity-power-curves`, `activity-hr-curves`) | best pace per distance, best power/HR per duration |
| Best efforts in one activity | `GET /activity/{id}/best-efforts?stream=&distance=` or `&duration=` | fastest N m / N s in a session |
| Power vs HR | `GET /athlete/0/power-hr-curve?start=&end=` | aerobic efficiency trend (cyclists) |
| Thresholds and zones | `GET /athlete/0/sport-settings` (also embedded in `GET /athlete/0`) | per sport: `types`, `ftp`, `indoor_ftp`, `w_prime`, `lthr`, `max_hr`, `threshold_pace`, `hr_zones`, `pace_zones`, `power_zones` |
| Gear | `GET /athlete/0/gear{ext}` | `name`, `type`, `distance`, `time`, `activities`, `retired`, `reminders` |
| Calendar | `GET /athlete/0/events{format}?oldest=&newest=&category=&limit=` | `category` one of `WORKOUT`, `RACE_A/B/C`, `NOTE`, `PLAN`, `HOLIDAY`, `SICK`, `INJURED`, `TARGET`, ...; `workout_doc`, `load_target`, `time_target`, `distance_target`, `icu_training_load` |
| Summary | `GET /athlete/0/athlete-summary{ext}?start=&end=` | `SummaryWithCats`: `fitness`, `fatigue`, `form`, `rampRate`, `eftp`, `weight`, `training_load`, `timeInZones`, `byCategory`. **Resolved:** the spec says it is "for followed athletes", and "when called with a bearer token then only the athlete the token is for is returned". With an API key it is not documented whether the caller is included. **Don't use it:** the wellness call already has fitness/fatigue/eFTP, and totals are computed from the activity list. |
| Writes | `PUT /athlete/0/wellness/{date}`, `PUT /athlete/0/wellness-bulk`, `POST /athlete/0/events`, `POST /athlete/0/events/bulk` | see "Writes" below |

**Strava-imported activities are stubs.** The spec says so for the activity
list, single activity, bulk fetch and `activities-around` ("An empty stub
object is returned for Strava activities"). Only activities that reach
intervals.icu directly from a device or upload have fields. Wellness is not
affected. The stub's shape is not documented; check that today's stdio
`get_activities` handles stubs (it reads `start_date` unconditionally).

### Strava API v3 (reference only; not to be built)

Kept as a record of what the current Strava path reads. Per
`data-source-policy.md`, none of the Strava rows below will be built. The
existing hosted Strava reads stay frozen until the login migration removes
them. Strava data comes from the official Strava MCP instead.

Current scopes: `activity:read_all,activity:read,profile:read_all`.

| Data | Endpoint | Scope | Notes |
|---|---|---|---|
| Profile | `GET /athlete` | `profile:read_all` gives the detailed representation (have) | `ftp`, `weight` (current value only), `measurement_preference`, `shoes[]`/`bikes[]` as `SummaryGear` (`id`, `name`, `distance`, `primary`) |
| Zones | `GET /athlete/zones` | `profile:read_all` (have) | already used |
| Gear | `GET /gear/{id}` | not stated | `brand_name`, `model_name`, `distance`, `description`; `retired` *(undocumented)*. Not needed: `/athlete` already lists gear. |
| Activity list | `GET /athlete/activities` | `activity:read`; `read_all` adds Only Me (have) | documented: `name`, `workout_type` (integer, values not documented; race = 1 for runs, 11 for rides in practice), `gear_id`, `kilojoules` (rides), `average_watts`, `weighted_average_watts`, `device_name`. *Undocumented:* `average_heartrate`, `max_heartrate`, `average_cadence`, `average_temp`, `suffer_score`. The code requests `per_page=200`, so 12 weeks is usually one request. |
| Activity detail | `GET /activities/{id}` | as above | `best_efforts`, `splits_metric`, `laps`, `calories`, `description`, `gear`; `perceived_exertion` *(undocumented)* |
| Totals | `GET /athletes/{id}/stats` | **not stated** in the reference or swagger | **Resolved:** "Must match the authenticated athlete" (own data only) and "Only includes data from activities set to Everyone visibility". Fixed windows only (last 4 weeks, YTD, all time) for ride/run/swim. **Don't use:** compute totals from the activity list. |
| Activity zones | `GET /activities/{id}/zones` | as above | "Summit Feature" (subscription) |
| Segments, routes | various | `read` (not requested) | low coaching value |
| Writes | `PUT /athlete`, activity create/update | `profile:write`, `activity:write` | new scopes, every user re-consents. Not recommended. |

Strava has **no wellness data** in its API: no sleep, HRV, resting HR or
weight history. `DetailedAthlete.weight` is a single current value.

### Strava rate limits (corrected; only relevant while the frozen path exists)

Limits are **per application, shared by all users** of the Fly server. From
the rate-limit page:

| App tier | Overall | "Non-upload" (every endpoint except uploads/create) |
|---|---|---|
| Default (single player, athlete capacity 1) | 200 / 15 min, 2,000 / day | 100 / 15 min, 1,000 / day |
| Upgraded from the dashboard (capacity 10) | 400 / 15 min, 4,000 / day | 200 / 15 min, 2,000 / day |
| More than 10 athletes | needs Strava review | per review |

- The 15-minute window resets at :00, :15, :30, :45; the day at midnight UTC.
- Every response carries `X-RateLimit-Limit/Usage` and
  `X-ReadRateLimit-Limit/Usage` ("15-min,daily"); over the limit is 429.
- Everything this server does counts against the non-upload limit, so the
  binding number is 100 (or 200) per 15 minutes across all users.

Cost of today's calls: `get_activities` ≈ 1 request per 200 activities;
`analyze_activity` = 4 (zones, detail, streams, laps); `analyze_lap` = 3. Per-activity fan-out (best efforts,
streams over a block) is what breaks the budget: 12 weeks of daily runs is
~84 requests, most of one 15-minute window for everyone.

## Proposed tools (consolidated)

The earlier draft proposed up to 10 new tools. MCP clients send every tool's
name, description and schema with each request, roughly 150–400 tokens per
tool, and more similar tools make the model pick the wrong one. The table
below consolidates them.

All five tools are **intervals.icu-only**. Strava data is the official Strava
MCP's job (see `data-source-policy.md`). With no intervals.icu connection:

- the new tools return a short "connect intervals.icu" message;
- `get_activities` (and `analyze_activity`/`analyze_lap`) keep today's
  frozen Strava output, with no new fields, until the login migration removes
  the Strava reads.

This is a behaviour change for hosted users who *did* add an intervals.icu
key. Their activity list switches from Strava to intervals.icu, so
Strava-synced activities become stubs (see the stub handling below). This is
intended; the output explains it.

| Tool | Replaces / absorbs | Net |
|---|---|---|
| `get_activities` (enriched, `group_by`) | draft 4 (richer list) and 5 (`get_training_summary`) | 0 |
| `get_wellness` (`metrics`, baseline) | draft 1, 2 (`get_weight_trend`), 3 (`get_fitness_form`), 9 (baselines); later the three wellness tools | +1, then −3 |
| `get_athlete_settings` | draft 7 (`get_athlete_profile`) and 8 (`get_gear`) | +1 |
| `get_best_efforts` | draft 6 | +1 |
| `get_calendar` | draft 10 | +1 |

End state: 17 → 19 tools (21 until the old wellness tools are retired),
instead of ~27. Names avoid `get_athlete_profile`: #10 uses "athlete profile"
for the stored profile, and the official Strava MCP already exposes a tool
with that name, which confuses the model when both connectors are enabled.

**Shared computations, not tool calls.** #10's `refresh_athlete_profile`,
#13's `check_training_load`/recovery check and #9's assembled
`start_consultation` need the same numbers. Put them in one pure module
(e.g. `training_metrics.py`: weekly totals, longest session, baseline mean/SD,
rolling averages, zone shares) that tools and those features call directly.
This is what the other proposals actually depend on.

### 1. `get_activities` (enriched) — M, intervals.icu

- Adds per activity: `name`, race flag (`race`), load
  (`icu_training_load`), RPE/feel, gear name, weather
  (`average_weather_temp`/`average_feels_like`), decoupling and efficiency
  factor.
- **Stubs:** Strava-synced activities come back as stubs. Count them, leave
  them out of totals, and say so once ("N activities synced from Strava
  aren't available through intervals.icu; connect your device directly to
  intervals.icu, or use the Strava connector for those"). Never try to fetch
  them from Strava.
- **Garmin attribution:** activities whose `device_name` is a Garmin device
  show "Garmin <model>". Grouped totals that include Garmin data carry one
  "Includes data from Garmin devices" line (check the exact wording against
  Garmin's API brand guidelines).
- New `group_by`: `activity` (default), `week` (ISO weeks, per sport: count,
  distance, time, elevation, load, longest), `month`. Ranges longer than 14
  days default to `week` with a note, which keeps context small for block
  reviews.
- Range cap: 1 year for `week`/`month` (one or two list requests).

Strava-only users: not served by this tool. The official Strava MCP
(`list_activities`) covers their activity list, and Claude can total it in
the conversation.

Sketch (`group_by: week`, made-up numbers):

```
Activities 2026-01-05 → 2026-02-01, by ISO week (source: intervals.icu)
week      sport  n  dist     time    elev   load  longest
2026-W02  Run    4  38.2 km  3h41m   310 m  182   14.0 km
2026-W02  Ride   1  52.0 km  1h55m   420 m   64   52.0 km
2026-W03  Run    5  44.6 km  4h20m   365 m  215   16.1 km
2026-W04  Run    5  47.9 km  4h38m   402 m  231   18.0 km
2026-W05  Run    3  29.5 km  2h49m   240 m  139   12.0 km   (partial week)
Run change W03→W04: +7% distance, +7% load. Longest run 18.0 km vs 16.1 km
in the prior 30 days (+12%).
```

### 2. `get_wellness` — S–M, intervals.icu

- Inputs: `start_date`, `end_date` (cap 180 days), optional `metrics` list or
  preset: `recovery` (hrv, restingHR, sleepSecs, sleepScore, avgSleepingHR),
  `body` (weight, bodyFat), `load` (ctl, atl, form, rampRate), `subjective`
  (soreness, fatigue, stress, mood, motivation, injury, comments), or any
  wellness field name. Default: `recovery`.
- Fetches with `fields=` for the requested metrics, plus a 60-day look-back
  for baselines.
- Per metric: latest value, 7-day average, 60-day baseline mean ± SD, and
  flags for days outside the band. Weight gets 7-day rolling average and
  7/28-day change. `load` computes form = ctl − atl (as % of ctl when
  `icu_form_as_percent` is set) and flags ramp rate.
- "Not tracked" vs "missing": uses `icu_wellness_keys` and the per-source key
  lists from `GET /athlete/0` (cached).
- Daily rows only on request (`daily: true`) or for ranges ≤ 14 days.
- The three existing tools stay until this ships, then become thin wrappers,
  then are removed after a release.

Strava-only users get the honest "no wellness data without intervals.icu"
message. No weight from Strava's `/athlete`, and no CTL estimate from
Relative Effort (that would be new Strava processing).

Sketch (`metrics: recovery`, made-up numbers):

```
Wellness 2026-01-19 → 2026-02-01 (source: intervals.icu)
metric       latest  7-day   baseline (60d)   flag
HRV (rMSSD)  48 ms   52 ms   55 ± 6 ms        latest below band (−1.2 SD)
Resting HR   51 bpm  49 bpm  48 ± 2 bpm       3 of last 4 days above band
Sleep        6h40    7h05    7h25 ± 35m       —
Sleep score  71      76      79 ± 7           —
Not tracked: avgSleepingHR. Missing: HRV on 2026-01-27.
```

### 3. `get_athlete_settings` — S, intervals.icu

Thresholds, zones and gear in one call; `section` filter
(`thresholds`, `zones`, `gear`), default all.

- intervals.icu: `sport-settings` per sport (`ftp`, `indoor_ftp`, `w_prime`,
  `lthr`, `max_hr`, `threshold_pace`, zones), current eFTP from the latest
  wellness `sportInfo`, gear with distance, retired flag and reminders.
- Strava-only: not served. The Strava MCP has `get_athlete_zones` and
  `get_gear`.

Sketch (made-up numbers):

```
Athlete settings (source: intervals.icu)
Run   threshold pace 4:30/km · LTHR 168 · max HR 188
      HR zones: Z1 <137 · Z2 137–150 · Z3 151–159 · Z4 160–168 · Z5 >168
Ride  FTP 250 W (indoor 240 W) · eFTP 244 W · W′ 18.0 kJ · LTHR 163
Gear  Shoe A 612 km (reminder at 700 km) · Shoe B 188 km · Bike A 4,210 km
      retired: Shoe C 845 km
```

### 4. `get_best_efforts` — M, intervals.icu

- intervals.icu: one `pace-curves` (runs, `gap` option) or `power-curves`
  (rides) call; windows e.g. 42 days, 90 days, 1 year; standard distances
  (400 m … half marathon) or durations (5 s … 60 min), each with date and
  activity id. Whether curves include Strava-imported activities is not
  documented. Verify with a synthetic account, and if they do, pass them
  through only as intervals.icu computed them (no Strava calls on our side).
- Strava-only: not served (the Strava MCP's `get_activity_performance` is
  the alternative).

### 5. `get_calendar` — M, intervals.icu only

Read-only: planned workouts, races (`RACE_A/B/C`), notes and SICK/INJURED
markers for a range, each planned workout paired with the executed activity
(`compliance`). Strava-only users: not available (no calendar in Strava's
public API). Pairs with the parked `save_training_plan` idea in
`intervals-icu.md`.

### Writes (all intervals.icu, all gated, later)

- `log_wellness` via `PUT /athlete/0/wellness/{date}`: only the fields the
  user asked to change; respect `locked`; never overwrite device-synced
  values (HRV, RHR, sleep). Check the UI's value mapping for the ordinal
  fields (`soreness`, `fatigue`, ...).
- SICK/INJURED markers via `POST /athlete/0/events`.
- Every write needs explicit per-call confirmation. The API key has full
  account access (it can delete activities and change settings), so writes
  widen the blast radius of a prompt injection. Prefer intervals.icu OAuth
  with limited scopes, blocked on the OAuth app approval in `intervals-icu.md`.

### Not recommended

- Any new Strava call, including everything below (see
  `data-source-policy.md`).
- Strava `/athletes/{id}/stats`: public activities only, fixed windows.
- intervals.icu `athlete-summary`: self-inclusion with an API key is
  undocumented, and wellness already has the numbers.
- Strava segments, routes, activity zones (new scope or subscription only).
- Strava writes (new scopes, re-consent).
- A Strava-side CTL/ATL estimate.

## Caching — S–M, later

Less urgent now that Strava's shared per-app budget is out of the picture.
intervals.icu publishes no rate limit, and load is per user key.

- **Per-user, in-memory cache** keyed by `(user_id, endpoint, params)`,
  never shared across users. Lost on machine stop, which is fine for a
  cache.
- **Don't persist API responses** in `store.db` or the training repo.
- **TTLs:** activity list and wellness 10 min (today's row changes);
  sport settings, gear and wellness-key lists 24 h. Size cap ~20 MB (the VM
  has 256 MB).
- **Single-flight:** concurrent identical requests share one upstream call.
- **No Strava caching.** Don't add caching to the frozen Strava path (it
  would be new Strava storage). The ineffective `StravaClient.zones_cache`
  is left as it is until the Strava reads are removed.

## Rollout and dependencies

The data-source migration (intervals.icu login, switching hosted data to
intervals.icu, removing Strava reads) comes from `data-source-policy.md`. It
is a separate change with its own owner decisions. The steps below don't wait
for it: they are intervals.icu-only, so they work on stdio and for hosted
users with a key from day one.

| Step | Work | Effort | Unblocks |
|---|---|---|---|
| 0 | Honest wellness errors (both failure paths) | S | #9 step 1 (same change; do it once) |
| 1 | `training_metrics.py` + enriched `get_activities` with `group_by`, stub handling, Garmin attribution | M | #9 weekly totals, #10 current fitness, #13 C2 volume/long-run checks, #11 day-one baseline |
| 2 | `get_wellness` with presets and baselines; fix HRV/RHR descriptions | S–M | #13 C3 recovery check and A3, #10 baselines, #9 wellness vs baseline |
| 3 | `get_athlete_settings` | S | #10 thresholds/zones/gear |
| 4 | `get_best_efforts` | M | #10 race results/best efforts |
| 5 | `get_calendar` | M | plan vs executed |
| 6 | Retire the three wellness tools | S | tool count |
| 7 | Per-user cache | S–M | latency; only if needed |
| 8 | Writes | M | — (needs intervals.icu OAuth) |

Effort changes from the previous draft:
- `get_wellness` S → S–M: baselines, presets, tracked-keys lookup and tests.
- Richer `get_activities` + totals S–M → M: grouping, stub handling,
  attribution.
- The Strava CTL estimate and Strava fan-out are dropped.
- Caching shrinks to S–M and moves late, because there is no Strava budget
  to protect.

Time in zone for #13 C2 comes from intervals.icu (`icu_zone_times`,
`icu_hr_zone_times` in the list). On Strava it is "not available from this
server".

Cross-PR effects of the policy recommendation (not edited here):
- #10 must not persist Strava-derived numbers in the profile.
- #11's day-one Strava backfill and Strava-first onboarding become "connect
  intervals.icu (device synced directly), optionally add the Strava
  connector".
- #9's consultation context uses intervals.icu only.

## Open questions (with recommendations)

1. **Strava policy.** Decided by the owner in `data-source-policy.md`.
   *Recommended there:* freeze, ask Strava, move hosted login and data to
   intervals.icu, and use the official Strava MCP for Strava data.
2. **Remote users with an intervals.icu key: which source for activities?**
   *Recommended:* intervals.icu only. Joining with Strava by `strava_id`
   would be combining Strava data (§5.4) and new Strava processing, so it is
   dropped. Stubs are explained, not rehydrated.
3. **Keep or retire `get_sleep_data`/`get_hrv_data`/`get_resting_heart_rate`?**
   *Recommended:* retire one release after `get_wellness` ships (−3 tools).
4. **Baseline definition.** *Recommended:* 60-day mean ± 1 SD, excluding the
   last 7 days, at least 20 data points, otherwise "baseline not established".
   Matches #13 C3 and D2.
5. **`group_by` default.** *Recommended:* `activity` for ≤ 14 days, `week`
   above.
6. **Garmin attribution wording.** *Recommended:* "Garmin <device model>" per
   activity, plus one line on aggregates. Confirm against Garmin's API brand
   guidelines before shipping step 1.
7. **Cache location.** *Recommended:* in-memory only; revisit only if
   cold-start refetches become a measurable problem.
8. **Writes.** *Recommended:* none until intervals.icu OAuth with limited
   scopes is available.

(The earlier "which Strava app tier" question matters only while the frozen
Strava path runs. See `data-source-policy.md`.)

## How to verify

- Unit tests for `training_metrics.py`: ISO-week bucketing across year
  boundaries, partial weeks, baselines with gaps and too few points.
- Handler tests with recorded (synthetic) intervals.icu payloads, including
  Strava stubs mixed with device activities, and Garmin vs non-Garmin
  `device_name` for attribution.
- An integration test that no new tool triggers a Strava HTTP call
  (`FakeStrava` records zero requests).
- A test that the cache never returns one user's entry to another.
