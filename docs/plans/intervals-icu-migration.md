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
- **Auth**: ~~single shared-secret bearer token~~ **superseded by Milestone 4** — the
  HTTP entrypoint now uses full OAuth (see below) instead of a static `MCP_SHARED_SECRET`.
  Kept a `stdio` entrypoint intact for local dev/testing (`server.py`'s current `main()`,
  untouched by Milestone 4) — the HTTP entrypoint is additive, stdio stays single-user.
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

### Milestone 4 — Multi-user OAuth (supersedes Milestone 2's shared-secret HTTP auth) ✅ DONE

Implemented as designed below and verified live end-to-end: real Dynamic Client
Registration from `mcp-remote`, `/authorize` redirecting to Strava, real Strava login/
consent, `/oauth/strava/callback` resolving and persisting the athlete
(`store.get_user("2706822")` → "Mateusz Kuzmik"), our own code minted and exchanged at
`/token`, and a live `get_activities` tool call returning real Strava activities through
the full chain. `get_sleep_data` correctly returns the no-wellness-data message for the
Strava session. All 93 tests pass (64 from Milestones 1-3 unaffected + 29 new). intervals.icu
as a second provider remains future work, unblocked whenever its OAuth app is approved.

**Why now:** Milestone 2's HTTP entrypoint currently holds one global
`INTERVALS_API_KEY` — every request that reaches it, regardless of who's on the other
end of the bearer token, acts as the one person who ran the server. This milestone
replaces *who's allowed to call it, and as whom* with real per-person identity.

**Provider for this first pass: Strava, not intervals.icu.** intervals.icu's OAuth
requires a manually-submitted app application (`https://intervals.icu/oauth/apply`) that
sits in "Pending" until a human at intervals.icu approves it — real friction for
iterating. Strava's OAuth app registration is instant and self-serve
(`https://www.strava.com/settings/api`, same as the old pre-Milestone-1
`strava_client.py` used), so it unblocks building and testing the whole multi-tenant
mechanism *today*. intervals.icu OAuth can be added as a second provider later, once its
app is approved (submit that application whenever convenient — it doesn't block this).
Decided explicitly: OAuth'd multi-user sessions get real activity data from Strava, with
no wellness data (Strava has none) — matches the limitation already accepted earlier
("return error from health metrics tools" for Strava-only accounts). The existing
personal stdio and local-HTTP paths keep using the intervals_api_key/`IntervalsClient`
exactly as today, untouched by any of this.

**Two nested OAuth relationships**, matching the exact diagram in the `mcp` SDK's own
`OAuthAuthorizationServerProvider.authorize()` docstring
(`mcp/server/auth/provider.py`, installed at `mcp==1.30.0`):

```
Claude  -->  our server (OAuth AS)  -->  Strava (OAuth AS)
  ^                |                            |
  +----redirect----+<-----------redirect---------+
```

1. **Claude ↔ our server**: our server *is* a full OAuth 2.0 Authorization Server for
   Claude, using the SDK's ready-made scaffolding (`mcp.server.auth.routes.create_auth_routes`,
   `mcp.server.auth.provider.OAuthAuthorizationServerProvider`,
   `mcp.server.auth.middleware.bearer_auth`) rather than hand-rolling OAuth endpoints.
   Dynamic Client Registration is enabled (`ClientRegistrationOptions(enabled=True)`) so
   Claude self-registers (`POST /register`) the way the MCP Authorization spec expects.
2. **Our server ↔ Strava**: our server is a single, pre-registered Strava OAuth client
   (same shape the deleted `strava_client.py` already used — recreated below, but
   per-user rather than single-config):
   - App registration: `https://www.strava.com/settings/api`, "Authorization Callback
     Domain" set to `localhost` for now — instant, no approval wait.
   - Authorize URL: `https://www.strava.com/oauth/authorize?client_id=&redirect_uri=&response_type=code&scope=activity:read_all,activity:read,profile:read_all`
   - Token exchange: `POST https://www.strava.com/oauth/token` with
     `client_id`/`client_secret`/`code`/`grant_type=authorization_code`.
   - **Refresh tokens ARE issued and matter here** — unlike intervals.icu, a Strava
     access token expires (~6h). Store `refresh_token` + `expires_at` per user in
     `store.py`; refresh via `grant_type=refresh_token` before/on a 401, reusing the
     refresh logic pattern the old `strava_client.py` already had.
   - Athlete id/name: `GET https://www.strava.com/api/v3/athlete` → `id` (int),
     `firstname`, `lastname`.

**End-to-end flow:**
1. Claude's `/authorize` request hits our server. Our provider's `authorize()` doesn't
   show a consent screen itself — it immediately redirects the browser to Strava's
   `/oauth/authorize`, using our registered Strava `client_id` and a `redirect_uri`
   pointing back at our own server (e.g. `/oauth/strava/callback`). We stash the
   original Claude request (its `client_id`, `redirect_uri`, `code_challenge`) keyed by a
   `state` value we generate, in a new `pending_authorizations` table.
2. User approves on Strava. It redirects to our `/oauth/strava/callback`.
3. Our callback handler exchanges the code with Strava for an access+refresh token,
   calls `GET /athlete` to learn the athlete's stable id (e.g. `12345678`) and name,
   upserts a `users` row (`provider="strava"`), generates our own authorization code
   (`subject=user_id`, per `AuthorizationCode.subject` in the SDK — it propagates
   straight to the issued `AccessToken`), and redirects back to Claude's original
   `redirect_uri`.
4. Claude exchanges that code at our `/token` endpoint. Our `exchange_authorization_code()`
   mints a long-lived `AccessToken` (`subject=user_id`, no refresh token *for Claude* —
   the Strava-side refresh stays internal to us) and returns it.
5. Every later `/mcp` call carries `Authorization: Bearer <our-issued-token>`. The SDK's
   `BearerAuthBackend`/`AuthContextMiddleware` verify it and stash it in a contextvar;
   inside any tool handler, `mcp.server.auth.middleware.auth_context.get_access_token()`
   returns it — `.subject` is the calling user's id, with no extra plumbing needed through
   `call_tool()`'s existing `(name, arguments)` signature.

**New files:**
- `src/train_with_gpt/store.py` — SQLite (stdlib `sqlite3`, one local `.db` file — no
  extra infra to run or provision, matches the project's existing low-infra style).
  Tables: `oauth_clients` (Claude's DCR-registered clients), `auth_codes`,
  `access_tokens`, `pending_authorizations` (bridges steps 1→3 above, keyed by our own
  `state`), `users` (`user_id` PK, `provider`, `name`, `access_token`, `refresh_token`
  nullable, `token_expires_at` nullable — generic enough to hold an intervals.icu row
  later too).
- `src/train_with_gpt/oauth_provider.py` — `TrainWithGptOAuthProvider`, implementing
  `OAuthAuthorizationServerProvider`'s `get_client`/`register_client`/`authorize`/
  `load_authorization_code`/`exchange_authorization_code`/`load_access_token` against
  `store.py`, plus a thin `verify_token()` (calls `load_access_token()`) so the same
  object also satisfies `TokenVerifier`.
- `src/train_with_gpt/strava_oauth.py` — the Strava side: builds the Strava authorize
  URL, and the `/oauth/strava/callback` Starlette route (step 2-3 above).
- `src/train_with_gpt/strava_client.py` — **recreated**, adapted from the version deleted
  in Milestone 1: same methods (`get_activities`, `get_activity_details`,
  `get_athlete_zones`, `get_activity_streams`, `get_activity_laps`), but constructed
  per-request with `(access_token, refresh_token, expires_at, on_refresh: Callable)`
  instead of reading a single global `config`; `on_refresh` writes the rotated
  token/expiry back to `store.py` so a refresh persists.

**Modified files:**
- `src/train_with_gpt/http_server.py` — drop `BearerAuthMiddleware`/`MCP_SHARED_SECRET`
  entirely; wire `create_auth_routes(provider, issuer_url=...)` plus the SDK's
  `RequireAuthMiddleware`/`AuthContextMiddleware` in front of `/mcp`; mount the new
  `/oauth/strava/callback` route from `strava_oauth.py`.
- `src/train_with_gpt/server.py` — `call_tool()` keeps its existing `(name, arguments)`
  signature. Add `get_active_data_client()`: when `get_access_token()` is set (HTTP/OAuth
  path), look up that user's row in `store.py` and return a `StravaClient` bound to their
  tokens; otherwise (stdio/local-HTTP path, unchanged) return the existing module-level
  `intervals` `IntervalsClient`. Same pattern for notes/goals: user-scoped
  `notes/{user_id}/`, `goals/{user_id}.md` when a user id is present, today's root-level
  paths otherwise.
- `get_activities.py`, `analyze_activity.py`, `analyze_lap.py` — call
  `get_active_data_client()` instead of receiving `intervals` as a parameter; since it
  can now return either an `IntervalsClient` or a `StravaClient`, branch on the type:
  `analyze_activity`/`analyze_lap` need Strava's original multi-call reconstruction (zones
  + streams + laps, manually cross-referenced — the exact logic the pre-Milestone-1
  version had) alongside intervals.icu's precomputed-zone path already in place. This is
  the "two analysis code paths per provider" case flagged when this was still a
  speculative Future Direction.
- `get_sleep_data.py`, `get_hrv_data.py`, `get_resting_heart_rate.py` — when
  `get_active_data_client()` returns a `StravaClient`, return the existing
  not-configured-style error response (Strava has no wellness data) instead of calling
  anything.
- `save_consultation_notes.py`, `read_consultation_notes.py`, `list_consultation_notes.py`,
  `search_consultation_notes.py`, `save_goals.py`, `read_goals.py` — thread the resolved
  user-scoped subpath into their existing `git_pull`/`git_add_commit_push` (`helpers.py`,
  unchanged) calls.
- `pyproject.toml` — no new dependency; `sqlite3` is stdlib, `mcp.server.auth.*` and
  `httpx` (for `strava_client.py`) already ship/are pinned.

**Local testing without a public deployment:** Strava's "Authorization Callback Domain"
being `localhost` plus `mcp-remote` (already proven working for the Milestone 2 test)
handling full OAuth flows natively — opening a browser, running its own local callback
listener — means pointing plain `mcp-remote http://localhost:8123/mcp` at the server
(no `--header-file`) should trigger the whole OAuth dance automatically once this is
built, no tunnel/ngrok needed for development.

## Verification

**Milestone 4:**
- Unit tests: mock Strava's `/oauth/authorize`/`/oauth/token`/`/athlete` calls; cover
  `store.py`'s CRUD, the provider's `authorize`→`exchange_authorization_code` path with a
  fake nested-callback, `load_access_token` rejecting expired/unknown tokens, and
  `StravaClient`'s refresh-on-401 behavior persisting the new token via `on_refresh`.
- End-to-end locally: run `train-with-gpt-http`, point `npx mcp-remote
  http://localhost:8123/mcp` at it with no `--header-file`, and confirm it opens a
  browser, completes the Strava consent, and lands back at a working MCP session —
  `tools/list` and a live `tools/call` (e.g. `get_activities`, `analyze_activity`)
  against a real Strava account should succeed, matching the manual `curl` checks
  already done for Milestone 2's transport. Confirm `get_sleep_data` returns the
  no-wellness-data message rather than erroring.
- Confirm a second identity works independently: authorize once, note the `user_id`
  `store.py` recorded, then (if a second Strava account is available) authorize again
  and confirm the two sessions get distinct `user_id`s and distinct `notes/{user_id}/`
  directories in the training-notes repo.
- Confirm the existing stdio and local-HTTP personal paths are completely unaffected
  (still using `INTERVALS_API_KEY` directly, no OAuth involved) — re-run Milestone 1/2's
  manual checks against the real intervals.icu account.
