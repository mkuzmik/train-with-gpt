# Idea: new-user onboarding (proposal, for review)

**Status:** Phase 0 is implemented, and so is a single entry point
(`start_consultation` reports whether the athlete is new or returning and
carries both paths; `discuss_goals` is gone), which pulls the "detect state"
part of Phase 1 forward. The rest of Phase 1 and Phase 2 are still proposals. This proposes how a new athlete goes from "just added the
connector" to a useful first consultation on the hosted (Strava OAuth) server.
Validated against `main` on 2026-09-25; "What the code does today" describes
the code before Phase 0.

## Problem

### What the code does today

- **Login.** `/authorize` redirects straight to Strava's consent screen
  (`oauth_provider.py`, `strava_oauth.py`). After Strava's callback, and only
  when `TOKEN_ENCRYPTION_KEY` is set, the server shows one page of its own:
  the optional intervals.icu key page (`intervals_connect.py`). Both "Connect"
  and "Skip" end in `complete_authorization` (`authorization.py`), a 303
  redirect to **Claude's** `redirect_uri`. Without the encryption key, the
  Strava callback redirects straight back. The server never shows a "you're
  connected" page; the last page it controls is the intervals.icu page, and
  only when that page is enabled.
- **Server root.** `http_server.py` routes `/health`, the OAuth routes
  (`/authorize`, `/token`, `/register`, `/revoke`,
  `/.well-known/oauth-authorization-server`), the protected-resource
  metadata (`/.well-known/oauth-protected-resource/mcp`),
  `/oauth/strava/callback`, `/oauth/intervals/connect` and `/mcp`. There is
  nothing at `/`: it returns Starlette's plain 404.
- **`start_consultation`** is a fixed prompt string. It takes no arguments,
  reads nothing and is the same for every user. It tells the model to call
  `get_current_date`, `read_goals`, `list_consultation_notes`,
  `get_activities`, and says "If no notes exist, this is a fresh start". It
  also says activities and wellness come from intervals.icu, which is wrong
  for hosted users (activities come from Strava; wellness only with the
  optional key).
- **`discuss_goals`** is a fixed prompt covering goal, current fitness,
  constraints (time, injuries, life, equipment) and secondary priorities, one
  question at a time, ending in `save_goals`. It tells the model to call
  `get_last_week_activities`, **a tool that does not exist** (it should be
  `get_activities`). Also noted in `science-based-coaching.md`.
- **`setup_training_repo`** is listed for every user. For OAuth users the
  handler refuses ("a shared, admin-configured setting"). But `read_goals`,
  `list_consultation_notes` and the other notes tools tell the user to "use
  setup_training_repo first" whenever the server has no training repo
  configured, so a hosted user hitting that case is sent to a tool that
  refuses them.
- **README.** The intro says all data comes from intervals.icu. Its "First
  Time Setup" (create a local git repo, call `setup_training_repo`) is for
  the stdio path only. The hosted connector steps are under "Deploying to
  Fly.io → Connecting clients", and they send Claude Desktop users to
  `mcp-remote` (needs Node) although a connector added on claude.ai also
  shows up in Desktop.

### Where a brand-new user gets stuck

| Step | claude.ai web | Desktop | Mobile |
|---|---|---|---|
| Find the URL | No page explains what to paste; `/` is a 404 | same | same |
| Add the connector | Settings → Connectors → Add custom connector. Free plan: one custom connector | Same (synced from claude.ai); README points to `mcp-remote` instead | **Can't add here.** Custom connectors are added on claude.ai and then sync to the apps |
| Strava login | Works, **if the Strava app has athlete capacity** (below) | same | same, once added on the web |
| After login | Back in Claude with no hint what to type. The connector may also need enabling in the chat's "+" / tools menu | same | same |
| First chat | "hi" does nothing; "start a consultation" gives a generic session with no goals, no notes and the intervals.icu wording | same | same |

**The hard blocker is Strava, not this server.** New Strava API apps start
in "Single Player Mode" with an athlete capacity of 1 (the owner). A
self-serve upgrade raises it to 10 athletes; beyond 10, the app must pass
Strava's review, and until then no additional athlete can authenticate
([Strava rate limits](https://developers.strava.com/docs/rate-limits/)).
Onboarding flow design doesn't matter until the owner has checked the app's
capacity on the Strava API settings page.

Once in, nothing captures the athlete's background, recent results,
constraints or health screening in a structured way, and the Strava history
the server can already read goes unused in the first conversation.

## Proposed solution

The design has two phases. Phase 1 needs neither `consultation-context.md`
(#9) nor `athlete-profile.md` (#10) and fixes most of the first-day
experience. Phase 2 moves the same flow onto the athlete profile when #10
lands.

### Phase 0: remove the dead ends (S, no dependencies)

- Fix `discuss_goals`: `get_last_week_activities` → `get_activities`. (The
  tool has since been folded into `start_consultation`; see "Single entry point".)
- Make `start_consultation`'s data-source wording match the transport
  (Strava for hosted users, intervals.icu for stdio; wellness "only if
  connected").
- Hide `setup_training_repo` from OAuth sessions. `list_tools` can check
  `current_user_id()` just as the tool handlers do, because the bearer token
  is in context for every `/mcp` request, including `tools/list`. Keep the
  handler's refusal as a fallback for clients with a cached tool list.
- For OAuth users, the "training repository not configured" message should say
  "this server's notes storage isn't set up; contact the operator", not point
  to `setup_training_repo`.
- README: a short "Using the hosted server" section at the top (add on
  claude.ai, syncs to Desktop and mobile, what to type first). Keep
  `mcp-remote` as the fallback for clients without custom connectors.

**Implemented.** Notes on how it was done:

- `start_consultation` takes the same data and wellness clients the data tools
  get in `server.py` and words its "Available Data Sources" from their type:
  Strava or intervals.icu for activities; the wellness tools are described only
  when the wellness client is intervals.icu. Otherwise the guidance says
  wellness isn't connected, tells the model not to call those tools, and gives
  the "how to add intervals.icu" text.
- The OAuth "not configured" text lives in
  `helpers.training_repo_not_configured_message()`, shared by all six
  goals/notes tools.
- The README's first message is "Start a training consultation"; see the
  single entry point below for how it handles new athletes.

### Single entry point (implemented; pulled forward from Phase 1)

There used to be two entry points: `start_consultation` for a returning
athlete and `discuss_goals` for goal setting, and the model had to pick one
before knowing anything about the athlete. Now there is one,
`start_consultation`, and the model decides the path.

**Facts it returns** (cheap, server-side, our own storage only):

- activities source (Strava or intervals.icu) and whether recovery data is
  connected, from the type of the clients `server.py` resolves (no data read);
- whether notes storage is set up;
- whether this user's goals file exists, and how many consultation notes they
  have plus the most recent note's date (from file names; no note is read).

The repo is synced first (`git_pull_and_read`, under the per-repo lock), so
goals or notes written from another device count. No Strava data is read,
processed or stored. If storage isn't configured, the path no longer exists
or the read fails, the facts say so and the rest of the guidance still comes
back: for stdio it offers `setup_training_repo`, for OAuth users it points to
the operator. In that case both paths are replaced by variants that never
call a goals/notes tool (they'd only return the same error): goals are
talked through and summarized in the chat instead of saved. The git sync's
"pulled updates" file list is never shown (on the hosted server it would
name other users' files); a sync warning is shown verbatim on stdio and as a
generic "may be out of date" line to OAuth users.

**How the path is chosen.** The guidance gives both paths and says the model
chooses from the facts and the athlete's message, asking one short question
when it's unclear. It also states the server's reading of the facts:

| Facts | Server's hint |
|---|---|
| no goals, no notes | new athlete → Path A (onboarding) |
| goals and notes | returning → Path B (consultation) |
| notes, no goals | returning without goals → Path B, offer goal setting early |
| goals, no notes | ambiguous → read goals, ask whether to pick up or start with an introduction |
| storage unavailable | can't tell → go by the message, or ask whether they've used the coach before |

An athlete with saved history is never onboarded from scratch; "start over"
is confirmed first, because `save_goals` replaces the old goals.

- **Path A (onboarding):** date and the last 2–4 weeks of activities, a short
  introduction of what the coach does (recovery data only as connected or not),
  the goal-setting conversation, `save_goals`, a first note with
  `save_consultation_notes` (including anything still to ask, so an
  interrupted onboarding resumes as "notes, no goals"), and the routine.
- **Goal-setting conversation:** the old `discuss_goals` framework (goal,
  current fitness, constraints, secondary priorities; one question at a time;
  summary; `save_goals`), shortened. Used by Path A and by Path B when goals
  are missing or changing.
- **Path B (consultation):** unchanged from the old `start_consultation`
  (date, goals, notes index and last 60 days, activities, then one open
  question).

What this does **not** do from Phase 1 yet: the landing page, the
in-progress onboarding note with a checklist, the health screen and the
12-week baseline. Those still need the owner's decisions below.

### Phase 1: onboarding on today's storage (M)

**1. Say what to type, where the user can actually see it.** The last page
the server controls comes before the redirect back to Claude, and not
everyone sees it, so a "what to type first" page after login isn't possible
without an extra click on every login. Instead:

- **Landing page at `GET /`** (a plain Starlette `Route("/", ..., methods=["GET"])`).
  Routes match exact paths, so it doesn't collide with `/mcp`, `/authorize`
  or `/.well-known/*`. It says what the tool is, the connector URL to paste
  (`<PUBLIC_URL>/mcp`, shown in full as selectable text), how to add it on
  claude.ai and that it then syncs to Desktop and mobile, what data it reads
  and stores, how to revoke access, and the first thing to type: **"Set me up
  as a new athlete"**. Generic content only, static HTML with the same
  security headers as the intervals.icu page (its CSP allows no scripts, so
  no copy button).
- **One line on the intervals.icu page:** "Next: open a new chat in Claude
  and type 'Set me up as a new athlete'."
- **The server does the rest:** `start_consultation` detects a new athlete
  (below), so a user who types "start a consultation" also gets onboarding.
  Its tool description says "call this first in any training conversation;
  it also handles first-time setup". Once #9 adds server instructions, a plain
  "hi" works too.

**2. Detect the athlete's state.** The new / existing part of this is already
implemented (see "Single entry point"); Phase 1 adds the in-progress state.
`start_consultation` (stays argument-free) looks at the current user's goals file, notes directory and, in Phase 1, an
onboarding note:

| State | Condition | Response |
|---|---|---|
| New | no goals, no notes | onboarding guidance (steps 3–7) |
| Onboarding in progress | an `Onboarding (in progress)` note exists, no goals | onboarding guidance, starting from the first pending item listed in that note |
| Existing, no goals | notes exist (none of them an onboarding note), no goals | today's daily guidance plus "no goals saved yet; offer the goal-setting conversation" |
| Onboarded | goals exist | today's daily guidance (Phase 2: plus a one-time offer to run the #10 backfill if there is no profile yet) |

An existing user with months of notes is never treated as new: any saved
goal or note means they are existing. The personal stdio user is in the same
position; they get the backfill offer in Phase 2, not onboarding.

**3. Data baseline first, within a fixed request budget.** Before the first
question, the guidance has the coach pull:

- the last 12 weeks of activities (`get_activities`, one Strava list call:
  a page holds 200 activities) for weekly volume per sport, longest session
  and consistency;
- the athlete's HR zones if set (one call);
- wellness baselines if intervals.icu is connected (not Strava);
- **what's missing**: no HR data, fewer than ~3 activities a week, no
  wellness source, and private activities missing if the athlete unticked
  `activity:read_all` on Strava's consent screen. Strava returns the granted
  `scope` on the callback; the server doesn't record it today, so Phase 1
  stores it with the user.

Don't fetch per-activity detail or streams on day one. Strava's best efforts
are only in the per-activity detail (one request per run), so ask for recent
results in the interview instead. The budget is about 2–4 Strava read
requests per onboarding, against a per-application read limit of 100 per 15
minutes and 1,000 per day (200 and 2,000 after the self-serve upgrade),
shared by all users. Even ten athletes onboarding in the same window stay far
below the limit. A longer look-back (52 weeks, about 2 list pages, to find
races) can come later, once responses are cached.

**4. Interview, one question at a time,** opening from the baseline. Order:

1. Goal: event, date and target, or "no event, general fitness". Both are
   valid answers.
2. Health screen (below). It comes second so red flags surface before any
   plan talk.
3. Background: years training, sports, recent results and PBs.
4. Constraints: available days and hours, equipment, other sports, life
   load.
5. Coaching preferences (optional).

The athlete can skip any question except the health screen. Skipped items
are recorded as "skipped" and asked about later, in normal consultations.

**5. Health screen and referral wording.** Three short yes/no questions plus
one conditional one, in
the spirit of the PAR-Q+ general health questions
([eparmedx.com](https://eparmedx.com/)) and the cardiac and REDs red flags
in `science-based-coaching.md`:

- Has a doctor ever told you that you have a heart condition or high blood
  pressure, or do you get chest pain, fainting or unusual breathlessness when
  exercising?
- Any current injury, or pain that gets worse as you train?
- Any other condition or medication a coach should know about, or are you
  pregnant or recently postpartum?
- (Only if relevant to their answers so far, asked gently) any recent
  unexplained fatigue, frequent illness, missed periods or rapid weight loss?

On a yes, the coach doesn't diagnose, doesn't build intensity into a plan,
and uses wording along these lines:

> "Thanks for telling me. That's something to check with a doctor (or a
> physio, for the injury) before we add hard training. I'm not able to
> assess it myself. Until you've been cleared, I can help with easy, low-risk
> activity and we can set up your goals so we're ready to go."

Current symptoms (chest pain or fainting right now or today) get "stop
exercising and contact emergency services or a doctor now", with nothing
else in that reply. The flag, but not medical detail beyond what the athlete
chose to say, is saved in the onboarding note so later consultations see it.

**6. Save as you go.** After each answered item, the coach calls
`save_consultation_notes` with an onboarding note headed
`Onboarding (in progress)`, with a checklist of items answered, skipped and
pending. It rewrites the note in place if the notes-sync fix (#8) supports
same-day updates, and otherwise saves a new note. When the minimum profile is
complete:
`save_goals` writes goal + background + constraints + health status (the
goals format already has room for all of these, see the goal-setting
conversation in `start_consultation`), a final
note marks onboarding done, and `start_consultation` switches to daily
guidance.

**Minimum profile** (the definition used for "done"):

- a goal, or an explicit "no specific goal";
- the health screen answered (all "no", or a flag with the referral given);
- training background in one or two sentences;
- weekly availability (days and rough hours).

Everything else (results, equipment, preferences) is optional and asked about
later.

**7. Explain the routine** in the closing message: start each chat with
"start today's consultation", say "save notes" at the end, "update my goals"
when things change, how to add intervals.icu later (disconnect and reconnect
the connector), and how to revoke access (remove the connector in Claude,
and revoke the app at strava.com/settings/apps).

**8. Resumability** comes from step 6: the onboarding note is the progress
record. A dropped conversation, or a switch from phone to laptop, resumes at
the first pending item. Nothing is kept in the conversation or in server
memory.

### Phase 2: move onto the athlete profile (after #10, #9)

- Answers go to profile sections with `update_athlete_profile` instead of
  the onboarding note. The "minimum profile" becomes a check on the Background,
  Health and Constraints sections, plus goals.
- The baseline comes from `refresh_athlete_profile`, and the interview from
  `profile_interview`, which already asks only about missing sections.
  Onboarding is then just "baseline + `profile_interview` + health screen +
  first block", not a separate tool.
- `start_consultation` returns assembled context (#9). The onboarding states
  above become one more part of that response.
- Migration: existing onboarding notes go through the #10 backfill like any
  other notes.
- An `onboard` MCP prompt for clients that show prompts (check support on
  each client first, as for `consult` in #9).
- Save a first training block (the #10 "current block" section).

### Example (made-up data)

> **Athlete:** Set me up as a new athlete
>
> *(Coach calls `start_consultation` → new-athlete guidance, then
> `get_activities` for 12 weeks.)*
>
> **Coach:** Welcome! I've looked at your last 12 weeks on Strava: mostly
> running, about 25–30 km a week over 3–4 runs, with a longest run of 16 km
> three weeks ago. Most runs have heart rate, and I can't see sleep or HRV
> (that's optional, we can add it later). What are you training toward, a
> specific race or more general fitness?
>
> **Athlete:** A half marathon in about 14 weeks. I'd like to go under 1:50.
>
> **Coach:** Got it: half marathon in ~14 weeks, target under 1:50. Before we
> talk training, a quick health check I ask everyone: has a doctor ever told
> you that you have a heart condition or high blood pressure, or do you get
> chest pain, fainting or unusual breathlessness when you exercise?
>
> **Athlete:** No, none of that.
>
> *(Coach saves the `Onboarding (in progress)` note: goal ✔, health 1/3,
> background, availability pending.)*
>
> **Coach:** Good. Any current injury, or pain that gets worse when you run?

## Alternatives considered

- **Keep improvising.** No work, but the first experience stays weak and
  nothing is saved in a structured way.
- **A web form instead of an interview.** Faster to fill in, but it
  duplicates the profile outside Claude, needs its own UI and auth, and loses
  the follow-up questions.
- **A "you're connected, type X" page after every login.** It's the only
  place the server could show it, but it adds a click to every re-login and
  device, and the user still has to type in Claude. The landing page and
  server-side detection cover the same need.
- **A separate `onboarding` tool.** One more tool the model has to choose
  correctly. Routing through `start_consultation` means the user's usual
  words trigger it.
- **Wait for #9 and #10.** Cleaner end state, but new users stay stuck until
  then. Phase 1 reuses the goal-setting guidance, goals and notes, and
  migrates later.

## Open questions (with recommended answers)

1. **Strava athlete capacity: stay at 10 or apply for review?**
   Recommended: do the self-serve upgrade to 10 now; apply for review only
   when real demand appears. The landing page says access is limited while in
   beta. Also re-read Strava's API agreement (updated 2026-06-01) on AI use
   of Strava data before opening to people beyond friends (flagged in #12).
2. **Minimum profile.** Recommended: goal (or "none"), health screen,
   background, availability, as above. Results, equipment and preferences
   stay optional.
3. **How much history on day one?** Recommended: 12 weeks of activity
   summaries only (1 list call, plus zones); no detail or streams. 52 weeks
   for race detection later, once cached.
4. **Existing users with many notes.** Recommended: never onboard them. Any
   goal or note means existing; in Phase 2 offer the #10 backfill once, and
   let them decline.
5. **Health screen: how many questions, and mandatory?** Recommended: the
   three core questions are mandatory and can't be skipped; the REDs question
   is asked only when the context calls for it. Store only the flag and the
   athlete's own words, no inferred diagnoses.
6. **Where does "what to type first" live?** Recommended: landing page +
   one line on the intervals.icu page + `start_consultation` detection. No
   new post-login page.
7. **Hide `setup_training_repo` per transport?** Recommended: yes, in
   `list_tools` via `current_user_id()`, keeping the handler's refusal.
8. **Data deletion.** There is no self-serve way to delete stored notes,
   goals or tokens. Recommended: the landing page names a contact for
   deletion requests now; a `delete_my_data` tool is a separate proposal.

## Rollout, effort and dependencies

| Step | Effort | Depends on |
|---|---|---|
| 0. Dead ends: `discuss_goals` tool name, transport-aware wording, hide `setup_training_repo`, OAuth "repo not configured" message, README hosted section | S | none |
| Strava capacity upgrade (operator action, no code) | – | none; blocks real users |
| 1a. Landing page at `/`, intervals.icu page hint | S | none |
| 1b. State detection + onboarding guidance in `start_consultation`, health screen, onboarding note, resumability | M | #8 only for in-place note updates (works without it by saving new notes) |
| 2. Profile-backed onboarding, `onboard` prompt, first block | M | #10 (profile, refresh, interview), #9 (assembled context, server instructions) |

## How to verify

- Unit: `start_consultation` returns onboarding guidance for a user with no
  goals and no notes, resume guidance with an in-progress onboarding note,
  and daily guidance once goals exist, all for the right user only.
- Unit: `list_tools` omits `setup_training_repo` with an OAuth token in
  context and includes it without one.
- Integration: `GET /` returns the landing page (200, no auth), `/mcp` still
  401s without a token, and the `.well-known` routes are unchanged.
- Integration: brand-new user via `login()` with stubbed Strava → onboarding
  guidance; after `save_goals` → daily guidance. Count Strava requests made
  during onboarding (budget ≤ 4).
- Manual: a second Strava account (within the app's capacity) goes through
  onboarding end to end on Fly, from the web, then continues on mobile.
