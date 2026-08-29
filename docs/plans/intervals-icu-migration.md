# Migrate to intervals.icu + remote-host the MCP server

## Context

Two related problems prompted this:

1. **Garmin credential storage blocks remote hosting.** The current `GarminClient`
   (`src/train_with_gpt/garmin_client.py`) authenticates with a stored email/password via
   the unofficial `garminconnect` library, falling back to password login (with MFA
   friction) whenever cached OAuth tokens at `~/.garminconnect` expire. Storing a live
   Garmin password on a server the user wants reachable from the public internet (so it
   also works from their phone) is a real security downgrade from "password lives in a
   config file on my own laptop."
2. **The user wants to use this MCP from both desktop and phone**, which requires an
   always-on remote server rather than a locally-spawned stdio subprocess — this is
   scoped to **personal use only** (single user, not a multi-tenant product: the user
   explicitly chose "just me, multi-device" over building a full OAuth-authorization-server
   + per-user-account system for arbitrary intervals.icu users).

The fix for (1) turned out to also simplify (2): **intervals.icu** already syncs Garmin
data (the user linked Garmin to their intervals.icu account) and Strava-equivalent
activity data, and exposes both through one stable, key-based REST API
(`https://intervals.icu/api/v1`, HTTP Basic auth with the literal username `API_KEY` and
the personal API key as the password — no password storage, no MFA, no browser OAuth
callback). Migrating both `strava_client.py` and `garmin_client.py` onto a single
`intervals_client.py` removes the Garmin-password problem entirely and leaves the server
with exactly one secret (`INTERVALS_API_KEY`) plus one shared secret for the remote HTTP
auth gate — both easy to hand to a remote host.

This was verified live: `curl -u API_KEY:<key> https://intervals.icu/...` against the
user's real (freshly-imported) intervals.icu account confirmed every field the current
tools rely on has an equivalent or better source — see field mapping below.

This work happens on the `intervals-icu-integration` branch, checked out in a separate
git worktree at `/Users/mat/Code/train-with-gpt-intervals-icu`, so the main checkout
keeps running today's Strava/Garmin version for Claude Desktop until the new version is
ready and switched over.

## Approach

### Milestone 1 — Replace Strava + Garmin with intervals.icu (do this first, verify fully before Milestone 2)

**New file `src/train_with_gpt/intervals_client.py`** — same shape as the classes it
replaces (instantiated once in `server.py`), built on `httpx.AsyncClient` with
`auth=("API_KEY", config.intervals_api_key)` and base URL `https://intervals.icu/api/v1`.
Athlete id `0` always means "the authenticated user," so no athlete-id lookup step is
needed (mirrors how `StravaClient` never needed one after its OAuth flow).

Confirmed methods and response shapes (verified via live curl against the real account):
- `get_activities(oldest, newest) -> list[dict]` → `GET /athlete/0/activities?oldest=&newest=`
  (ISO dates). Field names already closely match Strava's (`start_date_local`, `type`,
  `distance`, `moving_time`, `average_heartrate`, `max_heartrate`, `average_cadence`,
  `average_watts`, etc).
- `get_activity(activity_id, intervals=True) -> dict` → `GET /activity/{id}?intervals=true`.
  Returns, in one call: `icu_hr_zones` / `icu_power_zones` (zone upper-bound arrays),
  `icu_hr_zone_times` / `icu_zone_times` (**precomputed** seconds-per-zone — no manual
  bucketing needed for HR), and `icu_intervals` (a list of per-lap dicts with
  `average_heartrate`/`min_heartrate`/`max_heartrate`/`average_cadence`/`average_speed`/
  `distance`/`moving_time`/`elapsed_time`/`start_time`/`end_time` — richer than Strava's
  laps response, since min/max HR per lap comes straight from the API instead of being
  reconstructed from streams).
- `get_activity_streams(activity_id, types) -> dict[str, dict]` → `GET
  /activity/{id}/streams?types=...`. Intervals.icu returns `[{type, data}, ...]`; convert
  this into the `{type: {"data": [...]}}` shape `analyze_activity.py`/`analyze_lap.py`
  already expect, to minimize churn in those handlers.
- `get_wellness(oldest, newest) -> list[dict]` → `GET /athlete/0/wellness?oldest=&newest=`.
  Each day has `restingHR`, `hrv`, `sleepSecs`, `sleepScore`, `steps`, `weight` — covers
  everything `get_sleep_data`/`get_hrv_data`/`get_resting_heart_rate` use today, from one
  endpoint instead of three separate Garmin calls per day.

Note: intervals.icu activity ids are strings like `"i180171555"`, not ints like Strava's
— drop the `int(activity_id)` casts in `analyze_activity.py`/`analyze_lap.py`.

**`config.py`** — replace `client_id`/`client_secret`/`access_token`/`refresh_token`/
`expires_at`/`garmin_email`/`garmin_password` with one `intervals_api_key` field (env var
`INTERVALS_API_KEY`, file key `intervalsApiKey`). Update `load()`/`save()` accordingly.

**Delete:**
- `src/train_with_gpt/strava_client.py`, `src/train_with_gpt/garmin_client.py`
- `src/train_with_gpt/tools/connect_strava.py` (and its tool/handler — no more
  localhost:8111 OAuth callback flow)
- `setup_garmin.py`
- `tests/test_strava_client.py` and any connect_strava/Garmin-auth-specific tests

**Update tools to use `IntervalsClient`:**
- `get_activities.py` — swap `StravaClient` for `IntervalsClient`; field names mostly
  carry over as-is per the mapping above.
- `analyze_activity.py` — pull `icu_hr_zones`/`icu_power_zones` and `icu_hr_zone_times`
  straight off the activity-detail response instead of a separate `get_athlete_zones()`
  call; use `icu_intervals` for the laps section (the manual "reconstruct min/max HR from
  streams" fallback becomes dead code and can be dropped); keep `calculate_zone_distribution`
  (`helpers.py`, unchanged) as the power-zone fallback path when `icu_zone_times` isn't
  populated.
- `analyze_lap.py` — use `icu_intervals[lap_number - 1]`'s `start_time`/`end_time`
  directly as the lap boundary (removes the manual cumulative-elapsed-time summation
  loop), then keep the existing equal-time-window splitting logic against
  `get_activity_streams`.
- `get_sleep_data.py`, `get_hrv_data.py`, `get_resting_heart_rate.py` — each becomes a
  thin formatter over `intervals.get_wellness(oldest, newest)`, reading `sleepSecs`/
  `sleepScore`, `hrv`, and `restingHR` respectively instead of one Garmin call per day per
  tool. Keep them as three separate MCP tools (same external interface, different
  question each answers) — just swap the data source.

**`server.py` / `tools/__init__.py`** — replace the `strava`/`garmin` client instances
with one `intervals = IntervalsClient()`; update imports, `list_tools()`, and
`call_tool()`; remove the `connect_strava` tool entirely.

**`pyproject.toml`** — drop the `garminconnect` dependency; `httpx` stays (already used
by `strava_client.py` today).

**`README.md`** — replace the Strava OAuth app + Garmin email/password/MFA setup section
with: generate an intervals.icu API key (Settings → Developer Settings on intervals.icu),
put it in config/env as `intervalsApiKey` / `INTERVALS_API_KEY`. Remove the
`connect_strava`/`setup_garmin.py`/port-8111 instructions.

**Tests** — update the mocking pattern from `patch('httpx.AsyncClient.get', ...)` (already
used for Strava calls, see `tests/test_strava_client.py` for the existing convention) to
mock `IntervalsClient`'s methods directly; keep one success + one error-path test per tool
matching the existing per-tool test file convention.

### Milestone 2 — Remote hosting (only after Milestone 1 is verified working locally)

- **Transport**: new ASGI entrypoint (e.g. `src/train_with_gpt/http_server.py`) using
  `mcp.server.streamable_http_manager.StreamableHTTPSessionManager` (already available in
  the installed `mcp==1.26.0`, no dependency bump needed) wrapping the existing
  `app = Server("train-with-gpt")` unchanged — no migration to `FastMCP`, the low-level
  `Server`/`Tool`/`TextContent` pattern this codebase already uses stays as-is. Mount it
  in a small Starlette app run by `uvicorn`.
- **Auth**: single shared-secret bearer token (env var `MCP_SHARED_SECRET`), checked in
  ASGI middleware on every request, 401 on missing/mismatched — sufficient for
  single-user personal access; explicitly *not* building a full OAuth Authorization
  Server, since that's SaaS-multi-tenant-sized scope the user opted out of.
  a `stdio` entrypoint intact for local dev/testing (`server.py`'s current `main()`) —
  the HTTP entrypoint is additive.
- **Hosting**: a small always-on host with a public HTTPS URL (Fly.io is the concrete
  recommendation — cheap/free tier, simple `fly deploy`, supports a persistent volume for
  the notes-repo clone) rather than self-hosted hardware + a tunnel, since phone access
  shouldn't depend on home-network/machine uptime. The host needs three things
  provisioned: `INTERVALS_API_KEY`, `MCP_SHARED_SECRET`, and git push access for the
  notes repo (an SSH deploy key or HTTPS token — notes/goals already `git pull`/`git push`
  via `helpers.git_pull`/`helpers.git_add_commit_push`, unchanged).
- Register the deployed URL + shared secret as a Custom Connector in Claude (Desktop,
  mobile, web).

### Security (all three secrets — `INTERVALS_API_KEY`, `MCP_SHARED_SECRET`, git push
credential — get the same treatment)

- **Storage**: platform-managed secrets only (`fly secrets set ...` / host's encrypted
  env store), never in the repo, never baked into the Docker image, never in a config
  file checked into the notes repo. `config.py` already reads env vars first — the
  remote deployment relies on that path exclusively and skips the JSON-file path.
- **Transport**: HTTPS only, terminated by the host (Fly.io provides this by default) —
  no plaintext HTTP listener exposed publicly.
- **Bearer-token check**: generate `MCP_SHARED_SECRET` with a proper random generator
  (e.g. `openssl rand -hex 32`), compare it with `hmac.compare_digest` (constant-time) in
  the auth middleware rather than `==`, to avoid timing side-channels.
- **Least privilege on the intervals.icu key**: check whether intervals.icu supports
  scoped/read-only API keys when generating it — this server only ever reads activities
  and wellness data, so a read-only scope (if available) caps the damage if the key
  leaks.
- **Least privilege on the git credential**: use a deploy key or fine-grained token
  scoped to only the training-notes repo, not a broad personal-access token.
- **No secrets in logs**: keep the existing pattern from `config.py` (logs only
  "SET"/"NOT SET", never the value) — extend this to the HTTP layer too; never log the
  `Authorization` header or request bodies containing the shared secret.
- **Rotation/revocation plan**: document (in the README) how to rotate each secret if it
  leaks — regenerate the intervals.icu key from its settings page, redeploy with a new
  `MCP_SHARED_SECRET` and update the Custom Connector config in Claude, and issue a new
  git deploy key. This should be a five-minute operation, not a redesign.
- **Host hardening**: rely on the PaaS's managed OS/patching (Fly.io/Railway) rather than
  a self-managed VPS, so there's no separate OS-security surface to maintain.

### Milestone 3 — Upload training plans to intervals.icu (after Milestones 1 & 2 land)

Confirmed via intervals.icu's forum docs: planned workouts can be created through
`POST /api/v1/athlete/0/events/bulk?upsert=true`. Each event needs `category: "WORKOUT"`,
`start_date_local` (ISO 8601), `type` (`Ride`/`Run`/etc.), `name`, and workout content —
simplest path is a `description` field in intervals.icu's own plain-text workout format
(e.g. `"- 15m 55% Warmup\n\n3x\n- 1m 150%\n- 1m 50%"`), avoiding the undocumented
structured-JSON/ZWO-file routes. Uploaded events appear on the athlete's calendar in
intervals.icu; per user reports these do **not** reliably auto-sync to Garmin as a
scheduled workout the way UI-created ones do — the plan lands on intervals.icu, but
"see it on the watch" isn't guaranteed through the API. Flag this caveat to the user in
the tool's output rather than promising Garmin sync.

- **New client method**: `IntervalsClient.upload_workout(date, type, name, description) ->
  dict` (or a small list for multi-day plans) wrapping the bulk events POST.
- **New tool**: `save_training_plan` (or `schedule_workout`) — takes a date (or date
  range for multiple sessions), activity type, name, and a description of the workout
  (structured as intervals.icu's plain-text format, or passed through from a natural
  -language description Claude turns into that format during the conversation), calls
  `upload_workout`, and reports back what was scheduled plus the no-Garmin-sync caveat.
- Wire into `tools/__init__.py` and `server.py` following the existing tool pattern.
- Tests: mock the bulk-events POST call, cover a single-workout upload and a
  multi-workout/date-range upload, plus an error case (e.g. intervals.icu API failure).

## Verification

**Milestone 1:**
- `pytest tests/ -q` — full suite green.
- Run the server locally via stdio (Claude Desktop pointed at the worktree) and exercise
  `get_activities`, `analyze_activity`, `analyze_lap`, `get_sleep_data`, `get_hrv_data`,
  `get_resting_heart_rate` against the real intervals.icu account; compare output shape/
  values to what Strava/Garmin produced before, to confirm no regression in data quality.

**Milestone 2:**
- Run the HTTP server locally with `uvicorn`; `curl` it with and without the bearer token
  to confirm the auth gate rejects/accepts correctly.
- Deploy, add it as a Custom Connector in Claude Desktop and the Claude mobile app, and
  run a full consultation flow from both to confirm end-to-end tool calls work
  remotely.

**Milestone 3:**
- `pytest tests/ -q` green with the new tests.
- Manually call `save_training_plan` against the real intervals.icu account and confirm
  the workout appears on the intervals.icu calendar with the expected date/type/
  description.

## Future Direction — Multi-user, multi-provider (not scheduled yet)

Not part of Milestones 1–3, which stay scoped to personal/single-user use. Captured here
so the north star isn't lost, to be revisited only after Milestones 1–3 are done and
validated. High-level shape, as discussed:

- **Multi-tenant auth**: any user adds the Claude connector and authorizes via OAuth.
  This server becomes an OAuth Authorization Server for Claude (using the `mcp` SDK's
  `OAuthAuthorizationServerProvider`/`TokenVerifier` scaffolding) — at the `/authorize`
  step it redirects to the chosen provider's (intervals.icu's, or Strava's) own OAuth
  consent screen, collapsing "sign in" and "connect your data" into one step. The server
  then mints its **own** token for Claude rather than passing through the provider's
  token directly (audience-binding: Claude should only ever hold a token good for talking
  to this server, never the provider's own token).
- **Per-user identity**: use the stable athlete/account id from the provider's profile
  endpoint as the internal key (e.g. intervals.icu's `i691158`), not email — email is
  mutable and shouldn't end up baked into directory names or git history.
- **Notes/goals storage**: stays git-backed (keeps the free win of durable history +
  backups), just with a per-user subdirectory in one shared repo (`notes/{user_id}/`,
  `goals/{user_id}.md`) rather than one repo per user. Existing `git_pull`/
  `git_add_commit_push` helpers (`helpers.py`) barely change — just take a user-scoped
  subpath instead of the repo root.
- **Token storage**: a small persistent store (e.g. Postgres) mapping this server's
  issued token → user id → each connected provider's access/refresh tokens, encrypted at
  rest. Tokens are a different durability tier than notes: if this store is lost, it's
  recoverable (every user just re-authorizes) — unlike notes, which are irreplaceable
  user-authored content and need real backups.
- **Multi-provider (intervals.icu + Strava, interchangeably)**: a thin `DataProvider`
  interface both `IntervalsClient` and a (now multi-tenant) `StravaClient` implement;
  tool handlers call through the interface instead of a concrete client. Two concrete
  pieces of new work this implies:
  - Strava's OAuth flow has to become multi-tenant too — today's `strava_client.py` uses
    a `localhost:8111` callback meant for one desktop user; it needs the same
    hosted-callback-as-OAuth-client treatment intervals.icu gets, with per-user token
    storage.
  - `analyze_activity`/`analyze_lap` need two analysis code paths, not just two data
    sources behind one interface: intervals.icu hands back precomputed zone-times and
    per-lap stats in one call, while Strava requires the original multi-call
    reconstruction (zones + streams + laps, manually cross-referenced) that
    `analyze_activity.py`/`analyze_lap.py` use today.
- **Accepted limitation — decided, not to be revisited**: Strava has no sleep/HRV/
  resting-HR data at all (it's activity-only). Tool interface stays exactly as it is
  today — no new tools, no degraded/partial output. `get_sleep_data`/`get_hrv_data`/
  `get_resting_heart_rate` simply return their existing error-response shape when the
  user's connected provider(s) don't include a wellness-capable source.
