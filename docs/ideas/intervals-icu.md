# Idea: intervals.icu as a data provider (not scheduled)

Parked. Nothing here is planned for execution; it records what we learned so
it can be picked up later if it becomes worth it.

## Where things stand

- **Personal path (stdio / local HTTP):** already uses intervals.icu via a
  personal API key (`intervalsApiKey` / `INTERVALS_API_KEY`,
  `intervals_client.py`). This includes wellness data (sleep, HRV, resting HR)
  that intervals.icu syncs from Garmin.
- **Remote multi-user path (Fly.io):** Strava OAuth only (`strava_oauth.py`,
  `strava_client.py`). Activities work; wellness tools return
  "not available", since Strava has no wellness data.

## Why it is parked

Adding intervals.icu as a second OAuth provider for the remote server needs an
approved OAuth app (`https://intervals.icu/oauth/apply`). Registration asks for a
public website and privacy policy, and approval is manual. That is too much
overhead for a personal project, so the remote path has no wellness data for now.
Other ways to get Garmin sleep/HRV/resting HR are being explored instead.

## Useful facts (verified against the real API)

- Base URL `https://intervals.icu/api/v1`, HTTP Basic auth with username
  `API_KEY` and the personal key as the password; athlete id `0` means "me".
- `GET /athlete/0/activities?oldest=&newest=`: Strava-like field names.
- `GET /activity/{id}?intervals=true`: HR/power zones, precomputed
  time-in-zone (`icu_hr_zone_times`, `icu_zone_times`) and per-lap
  `icu_intervals` with min/max HR. Activity ids are strings (`"i180171555"`).
- `GET /activity/{id}/streams?types=...`: returns a list of `{type, data}`.
- `GET /athlete/0/wellness?oldest=&newest=`: `restingHR`, `hrv`, `sleepSecs`,
  `sleepScore`, `steps`, `weight` per day.
- Planned workouts: `POST /athlete/0/events/bulk?upsert=true` with
  `category: "WORKOUT"`, `start_date_local`, `type`, `name` and a plain-text
  workout `description`. Per user reports, API-created workouts don't reliably
  sync to Garmin.

## Ideas, if revisited

1. **intervals.icu OAuth as a second provider.** Users log in with Strava or
   intervals.icu. The latter would give remote users wellness data. Needs the
   approved OAuth app above.
2. **Owner-only bridge.** A simpler alternative: on the remote server, map just
   the owner's Strava id to the personal intervals.icu API key (a Fly secret),
   so wellness tools work for the owner only. No OAuth app needed.
3. **Upload training plans** (`save_training_plan` tool) via the bulk events
   endpoint, flagging the no-Garmin-sync caveat in the tool output.
4. **Durable identity mapping in the training-context repo.** Keep
   `profiles/<user_id>.json` (internal id, display name, list of
   `{provider, external_id}` connections) in the shared repo, next to `goals/`
   and `notes/`, so losing the Fly volume never orphans a user's notes.
   - `store.db` keeps only tokens, OAuth clients and sessions (replaceable;
     users re-authenticate).
   - **Tokens must never be written to the repo**, only non-secret mapping
     metadata.
   - Login resolves `(provider, external_id)` → internal id via the repo first,
     then the DB cache, else creates the user + profile (pull, write, commit,
     push), failing the link if the push fails.
   - Prerequisite: split identity from connections (`users` + `connections`
     tables). The owner's existing id `2706822` stays, so no notes migration.
   - Only worth it once a second provider is real.
