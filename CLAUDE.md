# CLAUDE.md

Guidance for Claude Code (and other coding agents) working in this repository.

## What this is

`train-with-gpt` is an MCP server for training analysis and coaching
conversations. It runs in two modes:

- **Local stdio** (`train-with-gpt`): single user, data from intervals.icu via a
  personal API key; notes and goals live in a local git repo.
- **Hosted HTTP** (`train-with-gpt-http`): multi-user. Our own OAuth
  authorization server (`oauth_provider.py`) delegates sign-in to Strava
  (`strava_oauth.py`); per-user notes and goals are stored in a shared git repo
  cloned at startup (`docker-entrypoint.sh`).

Tools live in `src/train_with_gpt/tools/` and are registered in
`tools/__init__.py` and `server.py`. Git-backed notes use the helpers in
`helpers.py` (`git_pull_and_read`, `git_save_file`, per-repo lock) — reuse
them rather than adding new sync code. `self_test.py` is the post-deploy smoke
test (the `self_test` tool, the `self-test` prompt, and the
`train-with-gpt-selftest` CLI); keep its `READ_ONLY_TOOLS`/`WRITE_TOOLS`
classification in sync when adding or removing tools.

## Commands

```bash
uv sync                 # install
uv run pytest -q        # full suite; run it twice before pushing
uv lock --check         # CI enforces this whenever uv.lock changes
```

- `tests/unit`: minimal mocking.
- `tests/integration`: black-box through the real stdio subprocess / HTTP app,
  with only external services (Strava, intervals.icu, git remotes) stubbed.
- Tool-count and tool-list assertions exist per transport (stdio vs hosted) —
  update them when tools change.
- CI (`.github/workflows/test.yml`) runs Python 3.10–3.14, only on pushes and
  PRs targeting `main`. PRs stacked on other branches get no CI.
- Releases: see `RELEASING.md`.

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
  intervals.icu path. See the open proposal on moving hosted login off Strava.
- Never merge PRs and never deploy — the maintainer does that.

## How work is organised

- **One task → one branch → one PR**, each in its own git worktree. Don't work
  in, or change the state of, the maintainer's main checkout. The git stash is
  shared across worktrees: never use a bare `git stash`/`git stash pop`
  (prefer a WIP commit).
- **Ideas and proposals** start as a *draft* PR with a design doc in
  `docs/ideas/`. Implementation of an idea is phased; implement only the
  phase that was asked for, and update the doc when the implementation
  diverges.
- **Bug fixes**: write the failing test first, confirm it fails without the
  fix, then fix.
- Keep edits to shared files (`server.py`, `tools/__init__.py`,
  `start_consultation.py`, README) small and localised; several PRs are often
  in flight at once.
- Update the README wherever users are affected.

### PR descriptions

- **"Decisions for the owner"** section at the top: for every non-critical
  choice you made, say what you chose and the alternatives.
- **Critical decisions** (any reasonable implementation would be thrown away;
  legal/policy, security-sensitive or irreversible; no sensible default):
  stop, push what's useful, keep the PR as a draft, and put a
  "⚠️ Decision needed" section at the top.
- Also: summary, how to verify, and conflicts/dependencies with other open PRs.

### Review loop (poll → evaluate → fix)

After pushing a PR that's ready for review:

1. Request a Copilot review:
   `gh pr edit <N> --add-reviewer @copilot`
   (fallback: `gh api -X POST repos/{owner}/{repo}/pulls/<N>/requested_reviewers -f 'reviewers[]=copilot-pull-request-reviewer[bot]'`).
2. Poll every few minutes for a review on the latest head commit.
3. Evaluate **every** finding — inline comments *and* items that appear only in
   the review body (e.g. "Previously missed" / low-confidence notes). Check
   each against the code:
   - valid → fix it, with a test that fails without the fix;
   - not valid → explain why.
4. Reply on each inline thread with the fixing commit or the reasoning
   (`gh api repos/{owner}/{repo}/pulls/<N>/comments/<id>/replies -f body=...`);
   answer body-only items with `gh pr comment`.
5. Push without force, re-request the review, repeat. Stop when a round has
   no new valid findings, or after 4 rounds (then list what's left in the PR).
6. Confirm CI is green (`gh pr checks <N>`).
