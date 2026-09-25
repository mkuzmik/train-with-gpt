# Idea: report bugs and improvements from inside a consultation (proposal, for review)

Not implemented. This proposes an MCP tool that lets the athlete, or the coach
on the athlete's behalf, report a bug or suggest an improvement, which opens a
GitHub issue automatically.

## Problem

Problems with the tool show up mid-conversation, on a phone, far from a
laptop: a save that failed, a tool that returned a confusing message, data
that looked wrong, a question the coach couldn't answer because a tool was
missing. Today the only record is the chat itself. By the time the maintainer
is at a computer the details are gone, and other users have no way to report
anything at all.

The model is often the first to notice: it sees tool errors, contradictions
between tools, and requests it can't serve. It has no way to pass that on.

## Constraints

- **This code repo is public.** An issue opened here is public, indexed and
  effectively permanent. Consultations are full of health data, names, dates
  and places. Nothing personal may reach an issue.
- **Several users share the hosted server.** The tool must not become a spam
  channel, and one user's reports must not reveal who they are.
- **Issue text is written by a model** that has read user messages and tool
  output. It must be treated as untrusted input by anything that later reads
  it (people, CI, coding agents).

## Proposed solution

### Tools

1. **`draft_issue(kind, title, summary, details?, related_tool?)`**
   - `kind`: `bug` or `improvement`.
   - The server builds the final issue text: the model's fields plus a
     server-generated diagnostics block (see below). It runs the redaction
     checks, and returns the exact text that would be posted plus a
     short-lived `draft_id`. Nothing is sent to GitHub yet.
2. **`submit_issue(draft_id)`**
   - Posts the stored draft unchanged and returns the issue URL.
   - The tool description tells the model to call it only after showing the
     athlete the exact preview and getting an explicit "yes".

Splitting draft and submit means the text the athlete approved is the text
that gets posted: the model can't change it between preview and submit.

Where the client supports MCP elicitation (a server-initiated confirmation
prompt shown by the client, not the model), `submit_issue` asks the user
directly. Otherwise it relies on the preview-and-confirm instruction.

### When the model should use it

- The athlete asks ("report this", "can you log a bug").
- The model hits a tool error, a clearly wrong result, or a missing
  capability. It then *offers* to report ("Want me to file this as a bug?")
  and never files without the athlete's yes.

### What goes into an issue

- Title, kind, summary and optional steps or expected vs actual behavior,
  written in general terms: "a note saved at the end of a long consultation
  was reported as saved but missing the next day", not the note itself.
- A diagnostics block the **server** fills in, never the model:
  - server version (git SHA), transport (http or stdio);
  - the related tool name and its last error *type and message*, if any,
    after redaction;
  - timestamp to the hour, in UTC.
- Labels: `from-mcp`, `bug` or `enhancement`, `needs-triage`.
- **Never**: user id, athlete name, Strava or intervals.icu ids, note or goal
  text, activity data, wellness values, dates of personal events, free-form
  tool output.

### Redaction and checks (server side)

- Reject or strip: email addresses, URLs other than this repo's, long
  numbers (athlete and activity ids), tokens and key-like strings, anything
  matching the athlete's stored name.
- Length limits on every field.
- Drafts that fail a check come back with the reason, so the model can
  rewrite them in general terms.

Redaction is a safety net, not the main protection. The main protections are
the tool description ("describe the problem in general terms, never include
personal data") and the athlete reading the exact preview.

### Where issues go

Two options. The owner picks one:

- **A. This public repo.** Simplest, and reports are visible to everyone.
  Relies entirely on the checks and the preview.
- **B. A private intake repo** (e.g. `train-with-gpt-feedback`). The
  maintainer triages there and opens a clean public issue when warranted.
  Personal data that slips through stays private. Costs one extra step per
  report.

Recommendation: **B** once anyone other than the owner uses the hosted
server, and until then either is fine.

### GitHub credentials

- A fine-grained personal access token or a GitHub App installation token
  with **Issues: read and write** on the single target repo and nothing
  else.
- Stored as a Fly secret (`GITHUB_ISSUES_TOKEN`) or in `config.json` for the
  stdio path, logged only as SET / NOT SET like the other secrets.
- If it isn't configured, the tools stay listed but return "issue reporting
  isn't configured on this server" (or are hidden).

### Abuse controls

- Per-user limits, e.g. 3 submitted issues per day and 10 per week, stored in
  `store.db` against the user id (the id never leaves the server).
- Deduplication: before creating, search open `from-mcp` issues for a
  similar title and, if one matches, offer to add a 👍 comment with the new
  details instead of a new issue.
- A kill switch: an env var that disables submission without a deploy.

### Follow-up

- `list_my_reports`: the athlete's own submitted issues and their state
  (open, closed, fixed in which release), from ids stored in `store.db`.
- Optionally, when a reported issue is closed as fixed, the next
  `start_consultation` mentions it once.

### Downstream handling

Issues from this tool are untrusted text. Any automation that reads them,
such as a triage bot or a coding agent that proposes fixes, must treat the
issue body as data, never as instructions, and must not run with secrets
that the issue text could steer.

## Alternatives considered

- **One tool that files immediately.** Simpler, but the text posted can
  differ from what the athlete saw, and a model can file without asking.
- **Store reports in `store.db` only** and have the maintainer read them over
  `fly ssh`. Private by default, but invisible and easy to forget.
- **Send to email or a chat webhook.** Faster to notice, but no tracking, no
  link to PRs, and another secret to manage.
- **Automatic reporting of every tool exception** without asking. Useful
  signal, but noisy and risky for privacy. Possible later as opt-in, sending
  only an exception fingerprint and counts.

## Open questions

- Public repo (A) or private intake repo (B)?
- Fine-grained token or GitHub App?
- Default rate limits.
- Should the model be allowed to offer a report unprompted, or only when the
  athlete asks?
- Does any Claude client (claude.ai, Desktop, mobile) support MCP elicitation
  today, so confirmation can come from the client rather than the model?

## Rollout

1. `draft_issue` and `submit_issue` with the diagnostics block, redaction,
   labels and rate limits, targeting the chosen repo.
2. Deduplication and `list_my_reports`.
3. Elicitation-based confirmation where clients support it; opt-in
   exception fingerprints.

## How to verify

- Unit tests: redaction strips or rejects each category above; the diagnostics
  block never includes user data; submit posts the stored draft byte for byte;
  expired or foreign `draft_id`s are refused; rate limits hold.
- Integration test: over HTTP, with GitHub stubbed, a draft and submit create
  exactly one issue with the expected labels, and a second user can't submit
  the first user's draft.
- Manual: file one test issue from Claude on a phone and check the preview
  matches the posted issue exactly.
