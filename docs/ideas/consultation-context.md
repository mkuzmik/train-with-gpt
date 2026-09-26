# Idea: reliable consultation context and daily flow (proposal, for review)

Not implemented. This proposes how a consultation should load what the coach
already knows, and how the daily check-in should work, so the coach stops
forgetting earlier discussions. Claims about the code refer to `main` at
`99edcb9` and to the open notes-sync fix (PR #8). Claims about Claude clients
and Fly.io were checked against their docs on 2026-09-25 (sources at the end).

## Problem

The intended daily flow is: open a new conversation, say "start today's
consultation", talk, and save notes at the end. In practice the coach often
does not know things settled in earlier consultations, such as a target set
weeks ago, a recent race result or a niggle being managed. The data is saved
in goals and notes, so this is a recall problem, not missing data.

Causes, from the code:

1. **Context loading depends on the model following instructions.**
   `start_consultation` takes no arguments, reads nothing and returns a fixed
   ~5 KB guidance string: call `get_current_date`, `read_goals`,
   `list_consultation_notes`, read at least 60 days of notes, then
   `get_activities`. Nothing checks that this happened, so the model can skip
   `read_goals`, skim the index or read a short window.
2. **Durable facts are spread across daily notes.** Results, test values and
   injury history live in whichever note they came up in. With daily
   check-ins, 60 days is dozens of notes. Rebuilding the picture every day is
   slow and lossy, and anything older depends on a headline mentioning it.
3. **Failures are easy to miss.**
   - If a call fails at the start, for example during a slow cold start, the
     coach can carry on without context, and nothing tells it to say so.
   - Saves do report errors (`❌ Error: ...`), and PR #8 adds an explicit "was
     NOT saved" when the push keeps losing races. But when a push fails for
     another reason (remote unreachable), PR #8 keeps the commit in the local
     clone for the next save to push. On Fly that clone is on the ephemeral
     root filesystem (cause 4), so the commit is lost if the machine stops
     first. The user was told the note was saved.
4. **Cold starts are slow, and the clone is not durable.** The Fly machine
   stops when idle (`auto_stop_machines = "stop"`, `min_machines_running = 0`).
   `docker-entrypoint.sh` clones the notes repo only if `.git` is missing, but
   the clone lives at `/data/training-context`, which is not on the volume (the
   only volume is mounted at `/home/app/.config/train-with-gpt`). Fly root
   filesystems are ephemeral, so in practice every boot is a full clone. One
   boot was observed to take about 3 minutes; this has not been measured
   systematically.
5. **Misleading wellness messages.** In `server.py`, `_get_wellness_client`
   returns the Strava client, whose wellness tools answer "Strava has no
   wellness data, connect intervals.icu", in three different cases: no key
   connected, a key connected but the secret box not configured, and a key
   that fails to decrypt (e.g. rotated encryption key). Only the first
   message is accurate. Separately, a key that intervals.icu rejects (401) is
   not a fallback: the handler's generic error says "Make sure
   INTERVALS_API_KEY is configured", an env var remote users don't have.
6. **Nothing loads context unless asked.** `Server("train-with-gpt")` is
   created without `instructions`, and the server exposes no MCP prompts. A
   conversation that doesn't start with "start today's consultation" loads
   nothing.
7. **"Today" is the server's day, not the athlete's.** `get_current_date` and
   note filenames use `datetime.now()` in the container (UTC on Fly). Late
   evening in Europe, or anywhere in the Americas, can be a different date.

## Proposed solution

### 1. `start_consultation` returns the context, not a to-do list

The server assembles one response, in this order:

1. **Status block**: each part below with `ok`, `empty`, `failed: <reason>` or
   `skipped`, plus the time of the last note and the number of local commits
   not yet pushed (PR #8's `_unpushed_count`). If anything failed, the first
   line says so.
2. **Today**: date and weekday in the athlete's time zone (see Risks).
3. **Athlete profile**, if it exists (`athlete-profile.md`).
4. **Goals.**
5. **Current training block**, if kept (profile section or separate file; an
   open question in `athlete-profile.md`).
6. **Recent notes in full**: newest first until the notes budget is used, and
   never fewer than the last 3 notes (the oldest one is cut with a
   "truncated, read it with `read_consultation_notes`" marker if needed).
7. **Older notes index**: date plus a headline shortened to ~120 characters,
   for the last 90 days only, then one line: "N older notes from X to Y; use
   `list_consultation_notes` or `search_consultation_notes`". A full index
   does not fit: at 200 characters per headline and one note a day, it passes
   20 KB in about three months.
8. **Recent training**: activities from the last 14 days, one line each, and
   weekly totals per sport for the last 4 weeks. One activity-list request
   covers both. The weekly totals should reuse the helper from
   `more-training-data.md` (recommendations 4 and 5), not a second
   implementation.
9. **Wellness** (intervals.icu only): the last 7 nights of sleep, HRV and
   resting HR, one request. The comparison with a personal baseline comes
   later, from the profile's computed baselines (`athlete-profile.md`,
   `more-training-data.md` recommendation 9).
10. **Guidance**, after the data: the read-back rule (section 2), conversation
    style, when to dig deeper (search older notes, analyze a workout), and the
    save rules (section 3). The coaching-principles and safety blocks from
    `science-based-coaching.md` (A1, C1, C4) go here too and share its budget.

**How it runs.**
- The git-backed parts (profile, goals, notes, block) are read with one
  PR #8 `git_pull_and_read` call: one sync and one lock, not one `fetch` per
  part.
- The data parts (activities, wellness) run concurrently with the git read.
  Each part has its own timeout (proposed: 20 s), and a failed or slow part
  becomes a `failed` line in the status block. The call never fails as a
  whole.
- The handler needs the request's data and wellness clients, as the other
  data tools already get them in `server.py`. On the stdio and personal paths
  it uses the personal `IntervalsClient`, as today.
- It reads only the calling user's paths (`helpers.user_scoped_*`).

**Size budget.** claude.ai and Claude Desktop accept tool results of about
150,000 characters, and Claude Code 25,000 tokens by default. The context is
loaded every day, so it should be much smaller than either. Proposed budget:
**32,000 characters in total** (roughly 8,000 tokens, safe for Claude Code),
split as:

| Part | Budget |
|---|---|
| Status, today | 1,000 |
| Profile | 6,000 |
| Goals | 3,000 |
| Current block | 2,000 |
| Recent notes in full | 10,000 |
| Older notes index | 3,000 |
| Recent training | 3,000 |
| Wellness | 1,000 |
| Guidance (including science principles) | 3,000 |

A part that has budget left over gives it to recent notes. A part over its
budget is cut with an explicit marker, never silently. Older notes stay
reachable through `read_consultation_notes` and `search_consultation_notes`.
The profile is what carries durable facts forward, and that is what makes a
short note window safe. Until the profile exists, the notes window is the
only memory, so step 2 of the rollout should come with the profile, or the
notes budget should temporarily take the profile's share.

**New athletes.** When there is no profile and no goals,
`start_consultation` returns onboarding context instead (see
`new-user-onboarding.md`). This proposal only provides the hook: the status
block and the assembly code are shared.

### 2. Read back before coaching

The guidance tells the coach to open with a 3–5 line read-back: goal event
and date, target, latest result, open issues, today's readiness. A wrong or
missing fact shows up in the first message, where the athlete can correct it.
If the status block has a failure, the read-back starts with it ("I couldn't
load your notes today: <reason>").

### 3. Saving that doesn't lose work

- **Save as you go.** Each `save_consultation_notes` call already writes a new
  file (`YYYY-MM-DD-HH-MM-SS.md` today, plus a random suffix after PR #8), so
  several saves a day already work and never overwrite each other. No append
  mode is needed. The guidance changes from "save at the END" to "save when a
  decision is made, and at the end", and each save records only what is new
  since the previous save in the same conversation.
- **Three outcomes, stated plainly.** The save result starts with one of:
  - `Saved and pushed: <relative file name>`
  - `Saved on the server but not yet pushed: <reason>`
  - `NOT saved: <reason>` (PR #8's `GitSyncError`)

  It should show the repo-relative name, not the server's absolute path. The
  guidance tells the coach to relay the outcome, and on anything but the first
  one to paste the note text into the chat so nothing is lost.
- **Durable local commits.** "Not yet pushed" is only safe once the clone is
  on the volume (section 4). Until then, the server should treat a failed
  push as `NOT saved` on hosts with an ephemeral clone.
- **Gap reminder** (later, optional): the status block shows the date of the
  last note, so the coach can see a missing day without extra logic.

### 4. Faster, durable clone

- **Put the clone on the existing volume.** A Fly Machine can mount only one
  volume, so a second volume is not an option. Set
  `TRAINING_REPO_PATH=/home/app/.config/train-with-gpt/training-context` in
  `fly.toml`. The entrypoint already clones only when `.git` is missing, so a
  restart then does no git work at all.
- **No sync or reset in the entrypoint.** The first tool call syncs through
  PR #8's `fetch` + `rebase --autostash`, which keeps unpushed commits (they
  are user content) and parks conflicts on an `unsynced-*` branch. A hard
  reset at boot would destroy exactly the commits PR #8 is careful to keep.
- **Entrypoint hardening.** Clone into a temporary directory and rename it
  into place, so an interrupted clone doesn't leave a `.git` that blocks every
  later boot. If `origin` differs from `TRAINING_REPO_URL`, update it with
  `git remote set-url`. Migration: the first boot after the change is a normal
  clone, and the old `/data` path simply disappears.
- **Consequences.** Volume snapshots (kept 5 days by default) now also hold
  the notes. They are already on GitHub, but snapshots have to be considered
  when a user asks for their data to be deleted. The existing `chown -R` on
  the repo runs on every boot; this is fine at the current size.
- **Keeping one machine warm** (`min_machines_running = 1`) costs about
  $2/month for this machine size (Fly price list; regional markup applies).
  Decide after measuring the boot time with the clone on the volume.

### 5. Honest wellness errors

This is the same item as recommendation 0 in `more-training-data.md`. It is
implemented once, and whichever proposal lands first owns it.

- `_get_wellness_client` returns a reason with the client: `no_key`,
  `secret_box_not_configured` or `key_undecryptable`.
- Only `no_key` gets today's "connect intervals.icu" message. The other two
  say that the key is stored but can't be used right now, and to reconnect or
  contact the operator.
- A 401 or 403 from intervals.icu says "intervals.icu rejected the API key;
  reconnect to update it" instead of pointing at `INTERVALS_API_KEY`.
- The reason is logged server-side, without the key.

### 6. Less typing

Options, from most to least reliable on claude.ai today:

- **Tool description** (works everywhere, S). Start `start_consultation`'s
  description with "Call this first in any training conversation, before
  answering, to load the athlete's goals, notes and recent training." Put it
  in the first sentence: descriptions are reported to be cut at about 500
  characters on claude.ai (unconfirmed, see issue #93 in Sources).
- **User-side instructions** (works in every Claude client, no code). Set
  "In training conversations, call `start_consultation` first" as a Project
  instruction, or in the account-wide instructions under Settings > General.
  Document both in the README and on the onboarding landing page.
- **Server `instructions`** (cheap, S). The installed SDK (`mcp` 1.30.0)
  supports `Server(name, instructions=...)`, and `create_initialization_options()`
  sends it in `initialize`, also in the stateless HTTP mode used here. Claude
  Code documents that it loads server instructions. For claude.ai it is **not
  documented**, and an open, triaged enhancement request reports claude.ai
  ignoring the field. Add it (it costs a few lines) but don't depend on it.
- **MCP prompts** `consult` (and later `onboard`) (S–M). Claude's connector
  docs list prompts as supported, and Claude Code shows them as
  `/train-with-gpt:consult`. How claude.ai, Desktop and mobile surface them
  is not documented, and an open bug from May 2026 reports custom-connector
  prompts disappearing from the Desktop UI. Build this last and check it by
  hand in each app.

## Alternatives considered

- **Keep the guidance-only `start_consultation` and make it stricter.**
  Cheapest, but this is what fails today: nothing enforces it.
- **Smaller first step: return only the git-backed context.** Goals, profile
  and recent notes inline, with activities and wellness still left to the
  model. This covers the recall failures (they are about saved facts), makes
  no Strava or intervals.icu calls, and is small. It is proposed as rollout
  step 2a below, not as the end state.
- **Load all notes every time.** Guarantees recall for small histories, but
  grows without bound and buries the relevant facts. The profile is the better
  place for durable facts.
- **Roll old notes up into weekly or monthly summaries.** Useful later, but
  it needs a model in the server or a scheduled job. The profile gets most of
  the benefit without either.

## Decisions needed (with recommendations)

1. **Size budget.** Recommended: 32,000 characters in total, split as in the
   table above, with at least the last 3 notes in full.
2. **Older notes index.** Recommended: the last 90 days, headlines cut to
   ~120 characters, plus a count and date range for older notes.
3. **Several saves a day.** Recommended: keep one new file per save (today's
   behavior and PR #8's design), with no append mode. Each save records only
   what is new.
4. **Time zone for "today".** Recommended: use the athlete's time zone from
   the Strava athlete profile or the latest activity's `timezone`, cached per
   user, falling back to UTC with a note in the status block. Note filenames
   keep the server's clock, so sorting stays stable. Recommended in addition:
   put the local date in the note header.
5. **Warm machine.** Recommended: no for now. Move the clone first, measure
   boot time from `fly logs`, and add `min_machines_running = 1` only if a
   cold start still takes more than ~10 s.
6. **Order against the profile.** Recommended: ship step 2a now with the
   notes budget taking the profile's share, and switch when
   `read_athlete_profile` lands.
7. **Unpushed saves before the volume move.** Recommended: report them as
   `NOT saved` on Fly until step 1 has shipped (a config flag, or detect that
   the repo is outside the volume).

## Dependencies

- **PR #8 (notes sync)**: required before steps 2 and 3. Assembly reads
  through `git_pull_and_read`, saves use `git_save_file` and `GitSyncError`,
  and the status block uses the unpushed-commit count.
- **`athlete-profile.md`**: `read_athlete_profile` and the "current block"
  decision feed parts 3 and 5. Computed baselines feed the wellness
  comparison later. Not a blocker for step 2a.
- **`more-training-data.md`**: weekly totals helper (recommendations 4 and 5)
  and baselines (recommendation 9). The wellness error fix is shared
  (recommendation 0).
- **`science-based-coaching.md`**: its principles and safety text go into the
  guidance part and share its 3,000-character budget.
- **`new-user-onboarding.md`**: uses this proposal's assembly and status
  block for its onboarding mode. Its step 2 assumes server instructions work
  on claude.ai. Per the findings above they may not, so onboarding needs the
  tool description and user-instruction fallbacks too.

## Rollout

Effort: S = under a day, M = a few days.

1. **Clone on the volume, entrypoint hardening, wellness messages** (S).
   Independent of the other proposals. Can ship before PR #8, but the
   no-reset-at-boot rule assumes PR #8's sync.
2. **Assembled context.**
   - 2a (S–M, after PR #8): status block, today, goals, recent notes, older
     index, read-back guidance, a stronger tool description and server
     `instructions`.
   - 2b (M): recent training and wellness parts, with per-part timeouts.
   - 2c (S, when the profile lands): profile and current block parts.
3. **Save outcomes and save-as-you-go guidance** (S, after PR #8).
4. **Time zone for "today"** (S).
5. **MCP prompts** (S–M), after checking by hand how each Claude app shows
   them.

## How to verify

- Unit tests for assembly:
  - all parts present, in order;
  - total and per-part budgets respected, with truncation markers;
  - at least 3 notes even when one is huge;
  - a failing or slow part (stubbed timeout) is reported in the status block
    and the rest still loads.
- A unit test that the git parts cost one sync (one `fetch`) per call.
- An integration test: `start_consultation` over HTTP with stubbed Strava and
  intervals.icu returns only the calling user's goals and notes.
- Unit tests for the wellness reasons: no key, secret box not configured, key
  undecryptable, 401.
- An entrypoint test (container or shell): an existing clone on the volume
  survives a restart without being re-cloned, and an interrupted clone is
  retried.
- Manual: time a cold start on Fly before and after moving the clone.
- Manual: in a fresh conversation, the first reply states the goal event and
  target without being asked, in each of claude.ai web, Desktop and mobile.
  Record whether that happened without a Project instruction (the server
  `instructions` check).

## Sources (checked 2026-09-25)

- Claude connector docs, "Build an MCP server for Claude": prompts and
  resources supported, tool results limited to about 150,000 characters on
  claude.ai and Desktop and 25,000 tokens in Claude Code, and a 240 s tool
  call timeout. https://claude.com/docs/connectors/building/index
- Claude Code MCP docs: server instructions load at session start, and MCP
  prompts run as commands. https://code.claude.com/docs/en/mcp
- anthropics/claude-ai-mcp#93 (open, triaged enhancement): claude.ai ignores
  the server `instructions` field.
  https://github.com/anthropics/claude-ai-mcp/issues/93
- anthropics/claude-ai-mcp#333 (open bug, May 2026): custom-connector prompts
  disappeared from the UI. https://github.com/anthropics/claude-ai-mcp/issues/333
- Claude Help Center, personalization features: account-wide and Project
  instructions.
  https://support.claude.com/en/articles/10185728-understanding-claude-s-personalization-features
- Fly.io volumes: one volume per Machine, ephemeral root filesystem, 5-day
  default snapshot retention. https://docs.fly.io/volumes/overview/
- Fly.io pricing: shared-cpu-1x with 256 MB is about $1.94/month before
  regional markup. https://docs.fly.io/about/pricing/
