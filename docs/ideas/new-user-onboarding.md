# Idea: new-user onboarding (proposal, for review)

Not implemented. This proposes how a new athlete goes from "just added the
connector" to a useful first consultation.

## Problem

A new remote user today:

1. adds the connector URL in Claude and logs in with Strava;
2. optionally pastes an intervals.icu API key on the interstitial page;
3. lands in an empty conversation with no guidance on what to type.

If they then call `start_consultation`, it finds no goals and no notes and
says "this is a fresh start", and the coach improvises. Nothing captures the
athlete's background, recent results, constraints or targets in a structured
way, and nothing uses the training history the server can already read from
Strava. `setup_training_repo` belongs to the personal stdio path and means
nothing to a remote user. The first days are exactly when the coach knows
least, and there is no flow for them.

## Proposed solution

### Flow

1. **Connect** (exists): Strava login, then the optional intervals.icu key
   page. The final page of that flow (or a landing page at the server root)
   says what to type first, e.g. "Start my onboarding".
2. **Detect a new athlete.** `start_consultation` sees no profile and no goals
   for this user and returns onboarding context instead of the daily
   context. Server instructions (see `consultation-context.md`) make this work
   even if the user just says "hi".
3. **Data baseline first.** The server runs `refresh_athlete_profile` (see
   `athlete-profile.md`) over the last 8–12 weeks: weekly volume per sport,
   longest session, best efforts, rough thresholds, and resting HR/HRV/sleep
   baselines when intervals.icu is connected. It also reports what data is
   *missing* (no HR, few activities, no wellness) so the coach knows what it
   can't see.
4. **Interview, one question at a time,** starting from the baseline: "I see
   about X per week and a recent 5k effort around Y. What are you training
   toward?" The server supplies the list of profile gaps, so the interview
   covers:
   - goal event, date and target;
   - training background and recent race results;
   - injuries and health issues;
   - available days and hours, equipment, other sports;
   - coaching preferences.

   Health red flags (see `science-based-coaching.md`) are screened here and
   lead to a referral message rather than a plan.
5. **Save** the profile's stated sections, goals, and a first training block,
   then a first note summarizing onboarding.
6. **Explain the routine.** A short closing message: how daily check-ins work,
   when to save, how to update goals, how to disconnect or revoke access.

### Resumable

Onboarding can be long. It saves progress per section as it goes, so a
dropped conversation resumes at the next gap instead of starting over.
`start_consultation` keeps returning onboarding context until the minimum
profile is complete (goal, background, constraints).

### Tools

- `onboarding` guidance, or `start_consultation` in onboarding mode, whichever
  reads better to the model. Reuses `profile_interview` and `discuss_goals`
  rather than duplicating them.
- An MCP prompt `onboard` for clients that show prompts.
- `setup_training_repo` is hidden from remote users (it only applies to the
  stdio path).

### Landing page

A small page at the server root: what the tool is, how to add it as a custom
connector in Claude (desktop, web, mobile), what data it reads, how to
revoke access, and the first thing to type. Generic content only.

## Alternatives considered

- **Keep improvising.** No work, but new users get a weak first experience
  and nothing is saved in a structured way.
- **A web form instead of an interview.** Faster to fill, but it duplicates
  the profile outside Claude, needs its own UI and auth, and loses the
  follow-up questions an interview gets.

## Open questions

- Minimum profile before daily consultations take over.
- How much history to pull on day one given Strava rate limits (100 requests
  per 15 minutes per application, shared across all users).
- Whether the existing personal/stdio user also goes through a lighter version
  (backfill from notes, see `athlete-profile.md`) instead.

## Rollout

Depends on `athlete-profile.md` (profile storage, refresh, interview) and
`consultation-context.md` (assembled `start_consultation`, server
instructions).

1. New-athlete detection and onboarding context in `start_consultation`.
2. Resumable interview and first-block save.
3. Landing page, `onboard` prompt, hiding `setup_training_repo` remotely.

## How to verify

- Integration test: a brand-new user (stubbed Strava with a few weeks of
  activities) gets onboarding context; after saving goals and the minimum
  profile, the next call returns daily context.
- Integration test: interrupted onboarding resumes at the next gap.
- Manual: a second Strava account goes through onboarding end to end on Fly.
