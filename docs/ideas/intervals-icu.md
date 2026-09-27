# Idea: intervals.icu as a data provider (not scheduled)

Parked. Nothing here is planned for execution; it records what we learned so
it can be picked up later if it becomes worth it.

## Where things stand

- **Personal path (stdio / local HTTP):** already uses intervals.icu via a
  personal API key (`intervalsApiKey` / `INTERVALS_API_KEY`,
  `intervals_client.py`). This includes wellness data (sleep, HRV, resting HR)
  that intervals.icu syncs from Garmin.
- **Remote multi-user path (hosted HTTP):** login with Strava OAuth
  (`strava_oauth.py`, `strava_client.py`), so activities come from Strava.
  After the Strava consent, an optional page asks for the user's personal
  intervals.icu API key (`intervals_connect.py`). If given, the wellness tools
  use it; the key is validated and stored encrypted (`secret_box.py`).

## Why intervals.icu OAuth is parked

Adding intervals.icu as a proper OAuth provider needs an approved OAuth app
(`https://intervals.icu/oauth/apply`). Registration asks for a public website
and privacy policy, and approval is manual. That is too much overhead for a
personal project, so the personal API-key step above is used instead. Personal
keys are meant for personal use and have full account access, so collecting
other people's keys is a gray area; they should know what they hand over.

## Useful facts (verified against the real API)

- Base URL `https://intervals.icu/api/v1`, HTTP Basic auth with username
  `API_KEY` and the personal key as the password; athlete id `0` means "me".
- `GET /athlete/0/activities?oldest=&newest=`: Strava-like field names.
- `GET /activity/{id}?intervals=true`: HR/power zones, precomputed
  time-in-zone (`icu_hr_zone_times`, `icu_zone_times`) and per-lap
  `icu_intervals` with min/max HR. Activity ids are strings (e.g. `"i12345678"`).
- `GET /activity/{id}/streams?types=...`: returns a list of `{type, data}`.
- `GET /athlete/0/wellness?oldest=&newest=`: `restingHR`, `hrv`, `sleepSecs`,
  `sleepScore`, `steps`, `weight` per day.
- Planned workouts: `POST /athlete/0/events/bulk?upsert=true` with
  `category: "WORKOUT"`, `start_date_local`, `type`, `name` and a plain-text
  workout `description`. Per user reports, API-created workouts don't reliably
  sync to Garmin.

## Ideas, if revisited

1. **intervals.icu OAuth instead of API keys.** Scoped, revocable access and
   no key handling. Needs the approved OAuth app above.
2. **intervals.icu as the login itself.** The API key identifies the user
   (`GET /athlete/0`), so the login page could offer "Use intervals.icu" as an
   alternative to Strava, with activities also read from intervals.icu.
3. **Upload training plans** (`save_training_plan` tool) via the bulk events
   endpoint, flagging the no-Garmin-sync caveat in the tool output.
4. **Durable identity mapping in the training-context repo.** Keep
   `profiles/<user_id>.json` (internal id, display name, list of
   `{provider, external_id}` connections) in the shared repo, next to `goals/`
   and `notes/`, so losing the server volume never orphans a user's notes.
   - `store.db` keeps only tokens, OAuth clients and sessions (replaceable;
     users re-authenticate).
   - **Tokens must never be written to the repo**, only non-secret mapping
     metadata.
   - Login resolves `(provider, external_id)` → internal id via the repo first,
     then the DB cache, else creates the user + profile (pull, write, commit,
     push), failing the link if the push fails.
   - Prerequisite: split identity from connections (`users` + `connections`
     tables). Existing users keep their current ids (the Strava athlete id), so no notes
     migration.
   - Only worth it once a second provider is real.
