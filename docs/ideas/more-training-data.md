# Idea: expose more training data to the coach (not scheduled)

Parked research. It surveys what else Strava API v3 and intervals.icu API v1
offer, maps that to common coaching use cases, and ranks new tools. Nothing
here is planned yet.

## Coaching use cases

- **Daily readiness checks.** Coaches decide go/no-go for hard sessions from
  HRV, resting HR and sleep relative to the athlete's own baseline, so they
  need a baseline band and trend, not only raw nightly values.
- **Body weight trends.** Athletes who log weight daily want trends (rolling
  average, weekly change) and a view of short-term drops that can point to
  dehydration or under-fuelling.
- **Weekly volume.** Coaches need weekly volume per sport (count, distance,
  time, load) without summing activity lists by hand.
- **Load and fatigue.** Fitness, fatigue and form (CTL/ATL/TSB) put a number
  on accumulated load, which helps with build and taper planning.
- **Race targets.** Best efforts, pace/power curves and current threshold
  settings ground race predictions and "is fitness moving" questions.
- **Gear.** Shoe mileage matters for rotation and race-shoe decisions.
- **Illness and injury.** Structured subjective fields (`soreness`, `fatigue`,
  `injury`, `comments`) and calendar markers for sickness/injury are easier to
  track over time than free text.
- **Conditions.** Temperature and weather help explain HR drifting against
  pace.
- **Plan vs executed.** Comparing planned workouts with what was done shows
  whether prescriptions are being followed.
- **Reliability.** When wellness data can't be read, the tool should say why
  rather than return a misleading message. See recommendation 0.

## What the server exposes today

- Activities: list, per-activity analysis (laps, zones, streams), per-lap.
  Remote mode reads them from Strava even when an intervals.icu key exists.
- Wellness (intervals.icu only): sleep (`sleepSecs`, `sleepScore`), HRV
  (`hrv`), resting HR (`restingHR`). `IntervalsClient.get_wellness` already
  returns the full record; the tools just discard everything else.
- Notes and goals in the training repo.

## API survey

### intervals.icu (verified against the OpenAPI spec at `/api/v1/docs`)

Auth: HTTP Basic `API_KEY:<key>` (the key has full account access, read and
write) or an OAuth bearer token. No published rate limit; the key is per user,
so load is spread across users, but be polite and avoid N+1 loops.

| Data | Endpoint | Useful fields |
|---|---|---|
| Wellness (daily) | `GET /athlete/0/wellness?oldest=&newest=[&fields=]` | `weight`, `bodyFat`, `abdomen`, `restingHR`, `hrv`, `hrvSDNN`, `avgSleepingHR`, `sleepSecs`, `sleepScore`, `sleepQuality`, `readiness`, `vo2max`, `spO2`, `respiration`, `steps`, `kcalConsumed`, `carbohydrates`, `protein`, `fatTotal`, `hydration`, `hydrationVolume`, `soreness`, `fatigue`, `stress`, `mood`, `motivation`, `injury`, `systolic`, `diastolic`, `bloodGlucose`, `lactate`, `menstrualPhase`, `menstrualPhasePredicted`, `comments`, plus **`ctl`, `atl`, `rampRate`, `ctlLoad`, `atlLoad`** |
| Fitness / fatigue / form | same wellness endpoint (`ctl`, `atl`; form = ctl − atl) | one call gives the whole fitness chart |
| Which wellness fields sync from the watch | `GET /athlete/0` → `icu_garmin_wellness_keys`, `icu_wellness_keys` | lets a tool say "not tracked" vs "missing today" |
| Per-activity load | `GET /athlete/0/activities` | `icu_training_load`, `trimp`, `hr_load`, `pace_load`, `power_load`, `icu_intensity`, `icu_atl`/`icu_ctl` at that time, `icu_rpe`, `feel`, `session_rpe`, `decoupling`, `icu_efficiency_factor`, `polarization_index`, `compliance`, `gear`, `calories`, `carbs_used`/`carbs_ingested`, `average_weather_temp`, `average_feels_like`, `average_wind_speed`, `icu_rolling_ftp`, running dynamics (`average_stride`, `average_stance_time`, `average_vertical_oscillation`) |
| Pace / power / HR curves | `GET /athlete/0/pace-curves.json?curves=…&type=Run`, `power-curves`, `hr-curves`; per range `activity-pace-curves.json?oldest=&newest=&distances=` | best pace per distance, best power per duration, for windows like 42d / 1y / all-time; `gap=true` for grade-adjusted |
| Best efforts in one activity | `GET /activity/{id}/best-efforts?stream=&distance=|duration=` | fastest N m / N s inside a session |
| Power vs HR | `GET /athlete/0/power-hr-curve?start=&end=` | aerobic efficiency trend (cyclists) |
| Thresholds and zones | `GET /athlete/0/sport-settings` (or `GET /athlete/0`) | per sport: `ftp`, `indoor_ftp`, `w_prime`, `lthr`, `max_hr`, `threshold_pace`, `hr_zones`, `pace_zones`, `power_zones` |
| eFTP / summaries | `SummaryWithCats` via `athlete-summary` | `eftp`, `eftpPerKg`, `fitness`, `fatigue`, `form`, `rampRate`, `weight`, `training_load`, `timeInZones`, per-category totals. Documented as "for followed athletes"; verify it includes self. Totals can be computed from the activity list anyway |
| Gear | `GET /athlete/0/gear.json` | `name`, `type`, `distance`, `time`, `activities`, `retired`, `reminders` |
| Calendar | `GET /athlete/0/events.json?oldest=&newest=&category=` | planned `WORKOUT` (with `workout_doc`, `load_target`, `time_target`, `distance_target`), `RACE_A/B/C`, `NOTE`, sickness/injury/holiday markers, `icu_training_load` |
| Writes | `PUT /athlete/0/wellness/{date}`, `PUT /athlete/0/wellness-bulk`, `POST /athlete/0/events[/bulk]` | log weight, soreness, injury, comments, nutrition; add notes or planned workouts |

Caveat: intervals.icu returns only stubs for activities it imported **from
Strava** (Strava's API terms forbid forwarding). Activity-level endpoints only
work for activities that reach intervals.icu directly from the device (Garmin,
Coros, …). Wellness is unaffected.

### Strava API v3

Current scopes: `activity:read_all,activity:read,profile:read_all`.
Rate limits are **per application, shared by all users**: 200 requests / 15 min
and 2,000 / day overall; 100 / 15 min and 1,000 / day for reads. Anything
that fetches detail per activity (best efforts, gear per activity, calories)
over long ranges will burn this quickly on a multi-user server; cache
`DetailedActivity` responses (they rarely change).

| Data | Endpoint | Scope | Notes |
|---|---|---|---|
| Profile | `GET /athlete` | `profile:read_all` (have) | `weight` (single current value, no history), `ftp`, `shoes[]` and `bikes[]` with `distance`, `measurement_preference` |
| Zones | `GET /athlete/zones` | `profile:read_all` (have) | already used |
| Gear | `GET /gear/{id}` | `profile:read_all` (have) | `distance`, `brand_name`, `model_name`, `retired` |
| Activity summary | `GET /athlete/activities` | have | `suffer_score` (Relative Effort, undocumented but present), `gear_id`, `kilojoules`, `name`, `workout_type` (race / long run / workout) |
| Activity detail | `GET /activities/{id}` | have | `best_efforts` (400 m … marathon, with `pr_rank`), `splits_metric`, `calories`, `perceived_exertion`, `description`, `device_name`, `segment_efforts` |
| Totals | `GET /athletes/{id}/stats` | docs are inconsistent (`read` vs `profile:read_all`) | only counts activities with "Everyone" visibility, so private activities are missing. Prefer computing totals from the activity list |
| Activity zones | `GET /activities/{id}/zones` | have | Strava subscription only |
| Segments | `GET /segments/starred`, `/segment_efforts` | `read` (not requested) | segment efforts need a subscription; low coaching value |
| Writes | `PUT /athlete` (weight), activity create/update | `profile:write`, `activity:write` | new scopes mean every user re-consents; not worth it |

Strava has **no wellness data** (no sleep, HRV, RHR, weight history) in its
API. Strava-only users get only a single current weight from the profile.

Also worth a re-read before adding more Strava-derived features: Strava's
Nov 2024 API agreement update tightened rules on third-party apps and AI use of
Strava data.

## Recommendations (prioritized)

Effort: S = one tool/handler, under a day; M = a few days or new
client methods + formatting; L = new subsystem.

0. **Make the wellness fallback honest (S, both).** When an OAuth user has an
   intervals.icu connection but the key can't be used (secret box not
   configured, decrypt failure, 401 from intervals.icu), the handlers
   currently get a `StravaClient` and say "not available for Strava-connected
   accounts", which is misleading. Distinguish "no key connected" from
   "key connected but failed" (and log the reason) in `_get_wellness_client`.
   Use case: reliability.

1. **`get_wellness` (S, intervals.icu only).** Generic daily wellness over a
   range, with an optional `metrics` list; returns only non-null fields plus a
   per-metric summary (mean, min/max, first-vs-last-7-day average). Reuses
   `IntervalsClient.get_wellness` (pass `fields=` to trim the payload). Covers
   weight, body fat, readiness, VO2max, steps, stress, spO2, respiration,
   nutrition, subjective soreness/fatigue/mood/motivation/injury, comments,
   menstrual phase. Use `icu_garmin_wellness_keys` to say "not tracked" vs
   "missing that day". Keep the three existing tools (they are well known to
   the model) or make them thin wrappers.
   Use case: weight trends; structured illness/injury tracking.

2. **`get_weight_trend` (S, intervals.icu; Strava-only gets current weight).**
   Focused view of `weight` (and `bodyFat` if present): 7-day rolling average,
   change over 7/28 days, day-to-day deltas flagged beyond ~1 kg (likely
   hydration, not tissue), optionally next to daily training load so
   post-session drops are visible. Could be a mode of `get_wellness`, but a
   named tool is easier for the model to find.
   Use case: weight trends.

3. **`get_fitness_form` (S, intervals.icu).** CTL (fitness), ATL (fatigue),
   form (CTL − ATL, also as % if `icu_form_as_percent`), ramp rate, per day,
   from the same wellness call. Add a short read-out: peak CTL in range,
   current form band, ramp-rate warnings. For Strava-only users, optionally
   approximate from `suffer_score` with the standard 42/7-day exponential
   model (M, clearly labelled as an estimate).
   Use case: load and fatigue.

4. **Richer `get_activities` + weekly totals (S–M, both).** Add activity
   `name` (Strava workout names say "race", "long run"), load
   (`icu_training_load` / Strava `suffer_score`), RPE/feel
   (`icu_rpe`, `feel` / `perceived_exertion` from detail only), calories, gear,
   weather temperature/feels-like, decoupling, efficiency factor. End the
   output with per-ISO-week totals by sport (count, km, time, elevation,
   load). When an intervals.icu key is connected, consider reading activities
   from intervals.icu for the richer fields (note the Strava-stub caveat and
   the different id format).
   Use case: weekly volume; conditions.

5. **`get_training_summary` (S, both).** Weekly or monthly totals over a long
   range (e.g. 12 weeks) without listing every activity: per sport count,
   distance, time, load, longest session, time in zones. Computed from the
   activity list, not Strava `/stats` (visibility gap). Keeps context small
   for block reviews.
   Use case: weekly volume and block reviews.

6. **`get_best_efforts` / pace and power curves (M, both with differences).**
   intervals.icu: `pace-curves` for runs (400 m … half marathon, over 42 d /
   90 d / 1 y windows, GAP option), `power-curves` for rides, `hr-curves`.
   Strava: `best_efforts` from `DetailedActivity`, one request per run, so
   limit to races or a short range and cache. Use for race prediction and
   "is fitness moving" checks.
   Use case: race targets.

7. **`get_athlete_profile` (S, both).** Thresholds and zones per sport
   (intervals.icu `sport-settings`: `threshold_pace`, `lthr`, `max_hr`, `ftp`,
   `w_prime`, zones; latest eFTP) or Strava `/athlete` (`ftp`, `weight`) plus
   `/athlete/zones`. Lets the coach check that zone-based analysis matches
   what the athlete believes their thresholds are.
   Use case: race targets; zone-based analysis.

8. **`get_gear` (S, both).** Shoes and bikes with total distance, retired
   flag, and (intervals.icu) reminders. Strava already returns this in
   `GET /athlete` under the existing scope.
   Use case: gear.

9. **Recovery baseline in HRV/RHR output (S, intervals.icu).** Add a personal
   baseline band (e.g. 60-day mean ± SD, or Garmin's "balanced" style) and
   flag nights outside it; show `hrvSDNN` and `avgSleepingHR` when present.
   Use case: daily readiness checks.

10. **`get_calendar` (M, intervals.icu).** Read planned workouts, races
    (`RACE_A/B/C`) and notes; pair each planned workout with the executed
    activity (`compliance`). Read-only first. Pairs with the parked
    `save_training_plan` idea in `intervals-icu.md`.
    Use case: plan vs executed; race dates kept next to training data.

### Writes worth considering (all intervals.icu, all gated)

- **`log_wellness`** via `PUT /athlete/0/wellness/{date}`: weight,
  soreness/fatigue/injury (small ordinal scales; check the UI's value mapping), `comments`, nutrition. Lets the coach
  store the subjective part of a gate read in structured form. Must only send
  the fields the user asked to change, respect `locked`, and never overwrite
  device-synced values (HRV, RHR, sleep).
- **Sickness / injury markers** as calendar events, so load charts show gaps
  for a reason.
- Every write needs explicit per-call user confirmation in the tool
  description. **The intervals.icu API key has full account access** (it can
  also delete activities and change settings), so write tools widen the blast
  radius of a prompt-injection or model error. Prefer intervals.icu OAuth with
  write scopes limited to wellness/calendar if writes become real (blocked on
  the OAuth app approval described in `intervals-icu.md`).
- Strava writes (weight via `profile:write`, activity edits via
  `activity:write`) need new scopes and re-consent from every user. Not
  recommended.

### Not recommended now

- Strava segments and routes (new `read` scope, subscription-only efforts,
  little coaching value).
- Strava `/athletes/{id}/stats` (misses private activities).
- Activity zones from Strava (subscription only; zones are already computed
  from streams).

## Order of work, if picked up

0 → 1/2/3 (one wellness call feeds all three) → 4/5 → 7/8 → 9 → 6 → 10 →
writes.
