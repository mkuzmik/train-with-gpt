# Idea: report bugs and improvements from inside a consultation (proposal, for review)

Not implemented. This proposes an MCP tool that lets the athlete, or the coach
on the athlete's behalf, report a bug or suggest an improvement, which ends up
as a GitHub issue. Claims about the code refer to `main` at `99edcb9`. Claims
about GitHub, MCP, Claude clients and Fly.io were checked against their docs
on 2026-09-25 (sources at the end).

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
- **Several users share the hosted server.** Anyone with a Strava account who
  completes the OAuth login can use it (there is no allowlist in
  `oauth_provider.py`). The tool must not become a spam channel, and one
  user's reports must not reveal who they are or what others reported.
- **The token would belong to the owner's GitHub account.** Abuse through it
  (secondary rate limits, spam) lands on that account.
- **Issue text is written by a model** that has read user messages and tool
  output. It is untrusted input for anything that later reads it (people, CI,
  coding agents), and for the coach model if it is ever read back.
- **Strava data must never reach an issue.** The Strava API Policy (effective
  2026-06-01, see #12) forbids showing a user's Strava data to anyone else and
  restricts AI use of it. A public (or even private) issue quoting activity
  names, values, ids or Strava error payloads would breach it. The same rule
  applies to intervals.icu data, as a matter of privacy.

## How the server works today (verified on `main`)

- **Tool registration** is a static list in `server.py` (`list_tools`) and an
  `if/elif` chain in `call_tool`. A new tool means a module in `tools/`, an
  export in `tools/__init__.py`, and two entries in `server.py`. `list_tools`
  can include a tool conditionally.
- **The current user** is not passed to tools. Handlers call
  `helpers.current_user_id()`, which reads `get_access_token().subject` from
  the SDK's auth context (set by `AuthContextMiddleware` in `http_server.py`).
  On HTTP it is the **Strava athlete id**, so the user id itself is Strava
  data and must never leave the server. On stdio (and the personal local
  path) it is `None`.
- **HTTP is stateless**: `StreamableHTTPSessionManager(app=..., stateless=True)`.
  Each request gets a fresh transport and session. This matters for
  elicitation (below) and for keeping drafts: in-memory state doesn't survive
  a Fly machine auto-stop, so drafts go in `store.db`.
- **`store.db`** (SQLite, mode 0600, on the Fly volume) already has
  TTL-pruned tables (`pending_authorizations`, `pending_connect_steps`). An
  `issue_drafts` table can follow the same pattern. `users.name` (Strava) and
  `intervals_connections.athlete_name` hold the athlete's name, which
  redaction can match against.
- **Secrets**: `config.py` reads env vars first, then `config.json`, and logs
  secrets only as `SET` / `NOT SET` (Strava client id is logged in full, as it
  isn't secret). A `GITHUB_ISSUES_TOKEN` fits that pattern. Fly secrets are
  documented in `fly.toml`'s comment and the README.
- **Errors**: tool handlers catch exceptions and return
  `❌ Error: {str(e)}` as text, so `call_tool` never sees an exception. Those
  strings can contain personal data: `httpx` status errors include the
  request URL (for Strava, `/activities/<id>`), and `_get_active_data_client`
  raises `"No stored Strava credentials for user {user_id}"`. So the server
  can't just forward "the last error message".
- **Version**: `__version__ = "0.1.0"` never changes, and the Docker image has
  no git metadata (`.dockerignore` excludes `.git`). A git SHA needs a build
  arg (`fly deploy --build-arg GIT_SHA=$(git rev-parse --short HEAD)`), or
  Fly's `FLY_MACHINE_VERSION` / `FLY_IMAGE_REF` as a fallback identifier.

## Proposed solution

### One tool, and the human submits

The first draft had `draft_issue` (build the text) and `submit_issue(draft_id)`
(post it), with the tool description telling the model to submit only after
the athlete said yes. That split guarantees that the text posted is the text
the model received, but **not** that the athlete saw it: the model can
paraphrase or truncate the preview, or call `submit_issue` in the same turn
without asking. The server can't tell the difference. Elicitation would fix
that, but claude.ai doesn't support it yet and the HTTP server is stateless
(see Feasibility).

So the refined design removes the model's ability to submit at all:

**`draft_issue(kind, title, summary, steps?, expected?, actual?, related_tool?)`**

- `kind`: `bug` or `improvement`. `related_tool`: one of this server's tool
  names (validated against the list).
- The server validates and redacts the fields, adds the diagnostics block,
  stores the draft, and returns the exact final text plus a **confirmation
  link**. Nothing is sent to GitHub.
- **HTTP (hosted)**: the link is `https://<server>/report/<token>`, where
  `<token>` is a random, single-use, 128-bit value bound to the draft and
  expiring after 24 hours. The page shows the exact issue text and a
  **Send report** button (an HTML form POST) and a **Discard** button. Only
  the POST files the issue, with the server's token. The page never shows the
  user id, and `GET` never changes anything, so a model's web fetch of the
  link can't submit it.
- **stdio (self-hosted)**: the link is GitHub's own new-issue URL with
  `title` and `body` prefilled (not `labels`: GitHub answers 404 when the
  user isn't allowed to label, which is anyone but a collaborator)
  (`https://github.com/mkuzmik/train-with-gpt/issues/new?...`). The user
  reviews it on GitHub and submits it under their own account. No token,
  config or rate limit is needed, and the stdio user is someone who runs the
  code themselves and has a GitHub account anyway.

Either way a human looks at the exact text outside the chat and presses the
button. The tool description asks the model to show the preview and the link,
but the guarantee no longer depends on it.

A capability link is acceptable here: whoever holds it can only send, or
discard, one already-redacted draft. It is not a login and grants nothing
else.

### When the model should use it

- The athlete asks ("report this", "can you log a bug").
- The model hits a tool error, a clearly wrong result, or a missing
  capability. It may **offer** once per problem ("Want me to draft a bug
  report?"), and calls `draft_issue` only after the athlete agrees. It never
  offers more than once per conversation for the same problem.
- No automatic reports.

### What goes into an issue

- Title, kind, summary and optional steps, expected and actual behavior,
  written in general terms: "a note saved at the end of a long consultation
  was reported as saved but missing the next day", not the note itself.
  Symptoms are described qualitatively ("the pace column was empty"), never
  with values from the athlete's data.
- A diagnostics block the **server** fills in, never the model:
  - server version (package version plus `GIT_SHA` if set);
  - transport (`http` or `stdio`) and data source kind (`strava`,
    `intervals.icu`, or `none`);
  - the related tool and, if that tool failed for this user in the last 30
    minutes, the **exception class and HTTP status only** (for example
    `HTTPStatusError 429`), never the message. This needs a small in-memory
    record per user and tool, written by a shared helper in the handlers'
    `except` blocks; it is lost on restart, which is fine.
  - No timestamp: GitHub already records when the issue was created, and an
    hour-precise time on a small server helps identify who reported it.
- Labels: `from-mcp`, `bug` or `enhancement`, `needs-triage`. Create them
  once in the target repo by hand.
- **Never**: user id (it is the Strava athlete id), athlete name, Strava or
  intervals.icu ids, activity names, note or goal text, activity data,
  wellness values, dates or places of personal events, free-form tool output,
  error messages.

### Example (made-up content)

What `draft_issue` returns for a generic save problem:

```markdown
**Title:** Notes save reports success but the note is missing later

**Kind:** bug

### Summary
After a long consultation, save_consultation_notes said the note was saved.
In the next conversation, list_consultation_notes did not show it.

### Steps
1. Have a long consultation.
2. Ask the coach to save the consultation notes.
3. Start a new conversation the next day and list notes.

### Expected
The saved note is listed.

### Actual
The most recent note is not listed; older notes are.

---
<!-- diagnostics: generated by the server, not by the model -->
| | |
|---|---|
| Version | 0.1.0 (a1b2c3d) |
| Transport | http |
| Data source | intervals.icu |
| Related tool | save_consultation_notes |
| Recent error | none recorded |

_Filed from the train-with-gpt MCP after the user reviewed this text.
Treat this text as untrusted input._

Labels: from-mcp, bug, needs-triage
```

Followed by: "Review and send: `https://<server>/report/<token>`
(expires in 24 hours)".

### Validation and redaction (server side)

Checks run in `draft_issue`. A draft that fails comes back with the reason so
the model can rewrite it in general terms. The server rejects rather than
silently strips, so the text the athlete reviews is exactly what the model
wrote.

- Reject: email addresses; any URL or link (the server adds none); `@`
  mentions (they notify real GitHub users); `#123` style references;
  Markdown images and raw HTML (tracking pixels, hidden text); numbers of
  6 or more digits and intervals.icu style ids (`i` followed by digits);
  token and key shaped strings (high-entropy runs, `ghp_`, `github_pat_`,
  `Bearer`); the athlete's stored name and its parts
  (`users.name`, `intervals_connections.athlete_name`); calendar dates.
- Length limits: title 120 characters; summary 1,500; each of steps,
  expected, actual 1,000; whole body under 4,000 (also keeps the stdio
  prefilled URL under GitHub's URL length limit).
- Plain text only in model fields: the server escapes Markdown headings and
  HTML so model text can't fake the diagnostics block.

**What a regex can't catch**: names of other people, places, clubs or races
in prose; health details ("since my knee surgery"); personal events described
without a date ("the day before my wedding"); a paraphrase of a note;
non-English text; and combinations that identify someone on a server with
few users. These are covered by the tool description ("describe the problem
in general terms, never include personal data"), by the athlete reviewing the
exact text on the confirmation page, and (with option B) by the issue landing
in a private repo first.

**An LLM check** (sending the draft to a model to flag personal data) is not
worth it for now: the server has no model API access, it would add a secret,
cost and a third party that sees the text, and the human review is the
stronger check. Revisit only if option A is chosen and reports from other
users start arriving.

### Where issues go

Two options. The owner picks one:

- **A. This public repo.** Simplest, and reports are visible to everyone.
  Relies entirely on the checks and the human review.
- **B. A private intake repo** (for example `train-with-gpt-feedback`, owned
  by the same account). The maintainer triages there and, when warranted,
  **writes a new public issue** in this repo. GitHub does not allow moving an
  issue from a private repo to a public one, so there is no transfer shortcut
  and the public issue has no link back. Personal data that slips through
  stays private.

Recommendation: **B for the hosted server** from the start, since anyone with
a Strava account can log in. The stdio path always targets this public repo,
because the user files it under their own GitHub account.

### GitHub credentials (hosted only)

- **A fine-grained personal access token** on the owner's account, limited to
  the single target repo, with **Issues: read and write** (Metadata: read is
  added automatically). Expiry: 366 days, with a reminder to rotate. Because
  the owner has push access, labels set at creation are applied (GitHub
  silently drops labels from users without push access).
- Issues appear as authored by the owner's account. With option B that's
  fine. With option A it reads as if the owner filed them, so the body's
  footer says they came from the MCP.
- A GitHub App would show as `<app>[bot]` and its installation tokens expire
  after an hour, but the server would need the app's private key, JWT signing
  and token minting code. Not worth it for one repo and one maintainer.
- Stored as a Fly secret `GITHUB_ISSUES_TOKEN`, read by `config.py` like the
  others and logged only as `SET` / `NOT SET`. Never in `config.json`
  (stdio doesn't need it).
- If it's not set, `draft_issue` is **not listed** on the HTTP path, so the
  model can't promise a report it can't deliver. On stdio the tool is always
  listed.

### Abuse controls (hosted only)

- Per user: 3 sent reports per day and 10 per week, and 20 drafts per day.
  Counted in `store.db` against the user id, which never leaves the server.
- Server wide: 20 sent reports per day. GitHub's secondary limits (80
  content-creating requests per minute, 500 per hour) are far higher, but
  hitting them repeatedly can get the owner's account restricted, and a daily
  flood of intake issues is a problem long before that.
- No search-based deduplication in v1. Searching the intake repo would show
  one user the titles of other users' reports (a leak in option B), and the
  search API adds a second call per report. The maintainer deduplicates
  during triage. If needed later, the server can deduplicate on its own
  fingerprint (`related_tool` + exception class + status) without showing
  anyone else's text.
- Kill switch: `ISSUE_REPORTING=off` (a Fly secret or env var) hides the tool
  and makes the confirmation page refuse to send. Changing it restarts the
  machine but needs no code deploy.

### Failure handling

- The draft is stored before any GitHub call, so nothing the athlete wrote is
  lost.
- If GitHub fails or times out (10 s) when **Send** is pressed, the page says
  so and keeps the draft (and its link) until it expires, so the athlete can
  retry. A 403/429 from GitHub is handled by honoring `retry-after`, not by
  retrying in a loop.
- A draft that expires unsent is deleted by the same TTL pruning the store
  already uses.
- Sent drafts keep only the issue number and the user id (for rate limits and
  a later `list_my_reports`); the text is deleted after sending.

### Downstream handling

Issues from this tool are untrusted text, in both directions:

- Any automation that reads them (a triage bot, a coding agent proposing
  fixes, the maintainer's own Claude Code session) must treat the body as
  data, not instructions, and must not run with secrets or write access that
  the issue text could steer. Don't add a workflow that triggers an agent on
  `from-mcp` issues without that.
- Nothing from GitHub flows back into a consultation in v1. If
  `list_my_reports` is added later it returns only the issue number, state
  and close reason, never titles, bodies or comments, since in a public repo
  anyone can comment, and the coach model has write tools
  (`save_goals`, `save_consultation_notes`).

## Feasibility

Confirmed:

- Creating an issue: `POST /repos/{owner}/{repo}/issues`, covered by the
  fine-grained permission **Issues: write**. Labels, assignees and milestone
  are applied only for users with push access and are silently dropped
  otherwise. The endpoint warns that creating content too quickly triggers
  secondary rate limits.
- Rate limits: 5,000 requests/hour for a PAT; secondary limits of 80
  content-generating requests per minute and 500 per hour; exceeding them
  returns 403 or 429 with `retry-after` or `x-ratelimit-reset`, and continuing
  can get the integration banned. Search is 30 requests/minute when
  authenticated (not needed in v1).
- Fine-grained PATs can be limited to specific repos of one owner, expire
  after 1 to 366 days or never (unless an org policy blocks it), and at most
  50 can exist per user. GitHub App installation tokens expire after 1 hour
  and can be narrowed to repos and permissions when minted.
- Transfer: "A private repository issue cannot be transferred to a public
  repository", and transfers only work between repos of the same owner.
- Prefilled new-issue URLs support `title`, `body` and `labels`; a query
  parameter the user has no permission for (such as `labels`) makes GitHub
  return 404, so the stdio link omits labels; too long a URL returns
  414 (no documented length, hence the 4,000 character body cap).
- MCP elicitation is in the spec (form mode since 2025-06-18, URL mode added
  in 2025-11-25). The installed SDK (`mcp` 1.30.0 in `uv.lock`) implements
  both (`ServerSession.elicit_form`, `elicit_url`).
- Claude Code supports elicitation dialogs.

Not available or unknown:

- **claude.ai** does not support elicitation: the feature request
  anthropics/claude-ai-mcp#153 (April 2026) is still open with no announced
  date. No public statement was found for Claude Desktop or the mobile apps
  with remote connectors; treat them as unsupported until tested.
- **Our HTTP server can't elicit even with a supporting client.** In
  stateless mode the session never sees the client's `initialize`, so
  `check_client_capability` returns `False`, and the client's answer to an
  elicitation arrives as a new request on a fresh transport. Elicitation would
  need stateful sessions. That, plus the missing client support, is why the
  confirmation page replaces it.
- Whether labels that don't exist yet are created on the fly by the create
  endpoint isn't documented clearly; create them by hand once.
- A GitHub account ban threshold for secondary limits is not published.

## Alternatives considered

- **`draft_issue` + `submit_issue`** (the first draft). The posted text
  matches the draft, but the model can still submit without the athlete
  having seen it. Replaced by the confirmation page.
- **Elicitation for the confirmation.** The right long-term shape, but not
  supported on claude.ai and not possible on a stateless server. Revisit when
  both change; it could replace the page.
- **One tool that files immediately.** Simpler, but files without consent.
- **Prefilled GitHub URL for everyone.** No token at all, but hosted users
  need a GitHub account and their report becomes public under their own name,
  which most athletes won't want. Kept for stdio only.
- **Store reports in `store.db` only** and have the maintainer read them over
  `fly ssh`. Private by default, but invisible and easy to forget.
- **Send to email or a chat webhook.** Faster to notice, but no tracking, no
  link to PRs, and another secret to manage.
- **Automatic reporting of every tool exception.** Useful signal, but noisy
  and risky for privacy. Possible later as opt-in counts per fingerprint,
  logged server-side, not as issues.

## Decisions needed (with recommendations)

1. **Target repo for the hosted server.** Recommended: **B**, a private
   intake repo, since logins aren't restricted.
2. **Credential.** Recommended: a fine-grained PAT, one repo, Issues read and
   write, 366-day expiry.
3. **Confirmation.** Recommended: the server-hosted confirmation page on HTTP
   and a prefilled GitHub URL on stdio, with no model-callable submit.
4. **Rate limits.** Recommended: 3 per user per day, 10 per week, 20 drafts
   per user per day, 20 sent per day server-wide.
5. **Unprompted offers.** Recommended: yes, but only after a tool error, a
   clearly wrong result or a missing capability, once per problem, and never
   drafting before the athlete agrees.
6. **Deduplication.** Recommended: none in v1; triage by hand.
7. **Version in diagnostics.** Recommended: pass `GIT_SHA` as a build arg on
   deploy.

## Rollout

Effort: S = under a day, M = a few days.

1. **`draft_issue` with validation, redaction and diagnostics** (S–M).
   Includes the per-tool error record and the `issue_drafts` table.
2. **stdio prefilled URL** (S). Usable immediately, no token.
3. **HTTP confirmation page, GitHub call, rate limits and kill switch** (M),
   once the owner has picked the target repo and created the token.
4. Later, if wanted: `list_my_reports` (state only), fingerprint dedup,
   elicitation once claude.ai supports it.

## How to verify

- Unit tests:
  - each rejection rule (email, URL, mention, image, long number,
    intervals.icu id, token shape, stored name, date) and each length limit;
  - the diagnostics block never contains a user id, name, error message or
    URL, even when the recorded exception's message contains one;
  - the page's POST sends the stored draft byte for byte; GET never sends;
  - expired, already used or unknown tokens are refused, and a draft can't
    be sent twice;
  - per-user and server-wide limits hold; the kill switch hides the tool and
    blocks sending;
  - the stdio link is a valid prefilled URL under the length cap.
- Integration test over HTTP with GitHub stubbed: draft, then POST the page,
  creates exactly one issue with the expected labels; the tool isn't listed
  without `GITHUB_ISSUES_TOKEN`; GitHub returning 500 or 429 keeps the draft.
- Manual: draft a report from Claude on a phone, open the link, check the
  page matches the draft exactly, send it, and check the issue in the target
  repo.

## Sources (checked 2026-09-25)

- GitHub REST, create an issue (labels need push access; secondary rate
  limit warning): https://docs.github.com/en/rest/issues/issues#create-an-issue
- GitHub REST rate limits (primary, secondary, content creation, 403/429):
  https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
- GitHub search rate limits (30/minute authenticated):
  https://docs.github.com/en/rest/search/search#rate-limit
- Permissions for fine-grained PATs (Issues: create an issue):
  https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
- Managing personal access tokens (fine-grained expiry, repo scoping, limit
  of 50):
  https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- GitHub App installation tokens (1 hour, narrowing):
  https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app
- Transferring an issue (not private to public):
  https://docs.github.com/en/issues/tracking-your-work-with-issues/administering-issues/transferring-an-issue-to-another-repository
- Creating an issue from a URL query:
  https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/creating-an-issue#creating-an-issue-from-a-url-query
- MCP specification 2025-11-25, elicitation:
  https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation
- anthropics/claude-ai-mcp#153, elicitation support in claude.ai (open):
  https://github.com/anthropics/claude-ai-mcp/issues/153
- Claude Code MCP docs (elicitation dialogs): https://code.claude.com/docs/en/mcp
- Fly.io Machine runtime environment (`FLY_IMAGE_REF`,
  `FLY_MACHINE_VERSION`): https://docs.fly.io/machines/runtime-environment/
- Strava API Policy (effective 2026-06-01), as summarized in
  `more-training-data.md` (#12): https://www.strava.com/legal/api_policy
