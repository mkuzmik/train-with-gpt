# Idea: reliable consultation context and daily flow (proposal, for review)

Not implemented. This proposes how a consultation should load what the coach
already knows, and how a daily check-in flow should work, so the coach stops
forgetting earlier discussions.

## Problem

The intended daily flow is to open a new conversation, say "start today's
consultation", talk, and save notes at the end. In practice the coach often
does not know things that were settled in earlier consultations: a race
target set weeks ago, recent race results, a niggle being managed. The data is
saved in goals and notes, so this is a recall problem, not missing data.

Causes, from the code and from how the tools behave:

1. **Context loading depends on the model following instructions.**
   `start_consultation` returns only guidance: "call `get_current_date`, then
   `read_goals`, then `list_consultation_notes`, then read at least 60 days of
   notes, then `get_activities`". Nothing checks that it happened. The model
   can skip `read_goals`, skim the index, or read a short window.
2. **Durable facts are spread across daily notes.** Race results, PBs, test
   values and injury history live in whichever note they came up in. With
   daily check-ins, 60 days is dozens of notes of text. Rebuilding the picture
   every day is slow and lossy, and anything older than the window depends on
   a headline mentioning it.
3. **Failures are silent.**
   - If a tool call fails at the start, for example during a slow cold start,
     the coach carries on without context and does not say so.
   - If saving fails at the end, the note is lost and the next day starts with
     a gap. The only record of the failure is the chat itself.
4. **Cold starts are slow.** The Fly machine stops when idle
   (`auto_stop_machines`), and `docker-entrypoint.sh` re-clones the notes repo
   on every boot because the clone is not on the persistent volume. One boot
   took about 3 minutes, long enough for connector calls to time out.
5. **A misleading wellness message.** In `server.py`, `_get_wellness_client`
   falls back to the Strava client whenever a connected intervals.icu key
   can't be used (secret box not configured, decryption failure). The user is
   then told wellness data is "not available for Strava-connected accounts",
   which reads as a configuration problem rather than a transient failure.
6. **Everything is typed by hand every day.** There are no server-level
   instructions, so a conversation that doesn't start with "start today's
   consultation" doesn't load anything.

## Proposed solution

### 1. `start_consultation` returns the context, not a to-do list

The server assembles one response, deterministically:

- today's date and weekday;
- the athlete profile (see `athlete-profile.md`), if it exists;
- goals;
- the current training block or plan, if kept (see `athlete-profile.md`);
- the last N notes in full (default: last 7 days or last 5 notes, whichever
  is more), plus the dated one-line index of all older notes;
- a summary of recent training: last 14 days of activities, weekly totals for
  the last 4 weeks;
- today's wellness, if available, compared with the athlete's baseline;
- a status block listing each part that loaded or failed and why.

The coaching guidance stays but moves after the data. It shrinks to
conversation style and "when to dig deeper" (search older notes, analyze a
workout).

Size budget: the whole response should stay within a fixed character budget.
Older notes stay reachable with `read_consultation_notes` and
`search_consultation_notes`; the profile is what carries durable facts forward
(see `athlete-profile.md`), which is what makes a short note window safe.

### 2. Read back before coaching

The guidance tells the coach to open with a 3–5 line read-back: "Here's what I
know: goal race and date, target, latest results, open issues, today's
readiness." A wrong or missing fact shows up in the first message, where the
athlete can correct it. If the status block reports a failure, the coach says
so first.

### 3. Saving that doesn't lose work

- **Save during the conversation.** Notes can be saved as soon as a decision
  is made. A second save on the same day appends to that day's note (or
  writes a numbered sibling, depending on how the notes sync fix lands)
  instead of requiring one save at the very end.
- **Confirm or report.** `save_consultation_notes` returns an explicit
  success line including the file name, or an explicit failure with the
  reason. The guidance tells the coach to relay it verbatim.
- **Retry and fallback.** On failure, the coach offers the note text in the
  chat so it can be saved on the next call; the next `start_consultation`
  reminds the athlete if the previous day has no note while activities exist.

### 4. Faster, more predictable server

- **Keep the notes clone on the volume.** Clone into the Fly volume (or a
  second volume) and `git fetch`/reset on boot instead of a full clone, so a
  cold start costs seconds, not minutes.
- **Optionally keep one machine warm** (`min_machines_running = 1`). This
  costs a few dollars a month; decide after measuring cold starts with the
  clone on the volume.

### 5. Honest wellness errors

Split "no intervals.icu key connected" from "key connected but not usable
right now" (decrypt failure, 401, secret box not configured), with different
messages, and log the reason server-side without the key.

### 6. Less typing

- **Server instructions.** The MCP `initialize` response can carry
  `instructions`. Use it to say: "At the start of any training conversation,
  call `start_consultation` before answering." Claude clients include server
  instructions in the model's context, so a plain "how was my run?" also
  loads context.
- **An MCP prompt.** Expose `consult` (and later `onboard`) as MCP prompts, so
  clients that support prompts show it as a menu entry or slash command.
  Client support varies and needs checking per app.
- **Document the Claude Project option.** A Project with the instruction
  "always call start_consultation first" works in every client today, needs
  no code, and is a good fallback.

## Alternatives considered

- **Keep guidance-only `start_consultation` but make it stricter.** Cheapest,
  but it is what fails today: nothing enforces it.
- **Load all notes every time.** Guarantees recall for small histories, but
  grows without bound and buries the relevant facts. The profile is the
  better place for durable facts.
- **Automatic summarization of old notes (weekly/monthly roll-ups).** Useful
  later, but needs an LLM in the server or a scheduled job. The profile gets
  most of the benefit without that.

## Open questions

- Default note window: last 7 days, last 5 notes, or a character budget?
- Should a same-day second save append to the day's note or create a new
  file? This depends on the notes-sync concurrency design.
- Is keeping one machine warm worth the cost, or is the faster boot enough?

## Rollout

1. Cold start (clone on volume) and wellness error messages. Small and
   independent.
2. `start_consultation` returns assembled context with the status block, plus
   the read-back guidance and server instructions.
3. Save confirmation and mid-conversation saves, after the notes sync fix
   merges.
4. MCP prompts, after checking client support.

## How to verify

- Unit tests for the assembled response: all parts present, budget respected,
  a failing part reported in the status block without failing the rest.
- Integration test: `start_consultation` over HTTP with stubbed Strava and
  intervals.icu returns goals and recent notes for the right user only.
- Manual: time a cold start on Fly before and after moving the clone.
- Manual: in a fresh conversation, the first reply states the goal race and
  target without being asked.
