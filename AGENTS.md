# AGENTS.md

**`README.md` is the source of truth** for what this project is, how it's
structured, how to build, test, release and self-host it, and how to add
tools. Read the relevant sections before working, and keep the README current
when you change any of that — don't duplicate it here. This file only adds the
rules and working conventions that the README doesn't cover.

## Hard rules

- **This repository is public.**
  - Never commit secrets (tokens, keys, deploy keys). Secrets belong in the
    hosting platform's secret store or in the user's local config, never in
    code, tests, fixtures, docs, commit messages or PR text.
  - **No personal data about any real person**: no athlete names/ids, activity
    ids, health metrics, note or goal contents, event names or dates. Tests and
    docs use synthetic data only. Describe needs generically ("a user logs
    weight daily").
  - Don't read the user's local config (`~/.config/train-with-gpt/`), and don't
    call Strava / intervals.icu / this server's tools with real credentials
    while developing.
- **This repo is a generic template.** Deployment specifics for a particular
  instance (app names, hosting config, the notes-repo URL, runbooks) live in
  that operator's own private deploy repo, not here. Keep docs and code
  provider-neutral and configured through environment variables.
- **Strava API policy** (API Agreement effective 2026-06-01, §5.3/§5.16
  restrict Strava data in AI apps / MCP servers): do not add new processing,
  aggregation, storage or caching of Strava data. New data features go on the
  intervals.icu path.
- Never merge PRs and never deploy — the maintainer does that.

## How work is organised

- **One task → one branch → one PR**, each in its own git worktree. Don't work
  in, or change the state of, the maintainer's main checkout. The git stash is
  shared across worktrees: never use a bare `git stash`/`git stash pop`
  (prefer a WIP commit).
- **Ideas, proposals and follow-ups are GitHub issues**, not PRs: new ideas,
  findings deferred from a PR review, and "not in this PR" items. Open one
  issue per item (`bug` or `enhancement` label), describe the behaviour and
  why it matters (no personal data, same as everywhere in this public repo),
  and link the PR it came from. A PR starts only when the maintainer picks the
  issue up, and it references the issue (`Fixes #N`). Existing proposal PRs
  and `docs/ideas/` docs stay as they are; implement only the phase that was
  asked for, and update the doc when the implementation diverges.
- **Bug fixes**: write the failing test first, confirm it fails without the
  fix, then fix.
- Keep edits to widely shared files small and localised; several PRs are often
  in flight at once.

### PR descriptions

The maintainer reviews mainly the description (and Copilot checks the diff
against it, see `.github/copilot-instructions.md`), so it must be an accurate,
complete account of the change:

- **Describe functionality, not implementation**: what changes for users,
  operators and AI clients calling the tools; compatibility and migration risk
  (existing users, stored data, deployed instances, stdio vs hosted); anything
  an operator must do before deploying (new env vars/secrets). No file-by-file
  or class-by-class changelog.
- **Keep it in sync**: after every push, update the description so it matches
  the code — no stale claims from earlier iterations.
- **Every PR gets exactly one release label** when it's opened, because
  merging to `main` releases automatically (see `RELEASING.md`):
  `release:major`, `release:minor`, `release:patch` or `release:skip`
  (e.g. `gh pr create --label release:minor`, or `gh pr edit <N> --add-label ...`).
  Docs-only proposals and changes that shouldn't ship on their own use
  `release:skip`. Revisit the label when a PR's scope changes.
- **"Decisions for the owner"** section at the top: for every non-critical
  choice you made, say what you chose and the alternatives.
- **Critical decisions** (any reasonable implementation would be thrown away;
  legal/policy, security-sensitive or irreversible; no sensible default):
  stop, push what's useful, keep the PR as a draft, and put a
  "⚠️ Decision needed" section at the top.
- Also: summary, how to verify, and conflicts/dependencies with other open PRs.

### Review loop (poll → evaluate → fix)

After pushing a PR that's ready for review:

1. Request a Copilot review (`gh pr edit <N> --add-reviewer @copilot`).
2. Poll every few minutes for a review on the latest head commit.
3. Evaluate **every** finding — inline comments *and* items that appear only in
   the review body (e.g. "Previously missed" / low-confidence notes):
   - valid → fix it, with a test that fails without the fix;
   - not valid → explain why;
   - description mismatch → update the PR description.
4. Reply on each inline thread with the fixing commit or the reasoning;
   answer body-only items with a PR comment.
5. Push without force, re-request the review, repeat. Stop when a round has
   no new valid findings, or after 4 rounds (then list what's left in the PR).
6. Confirm CI is green.
