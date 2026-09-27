# Releasing

**Merging a PR into `main` releases it.** The `Release` workflow
(`.github/workflows/release.yml`) runs on every push to `main`:

1. It works out the next version from the latest `vX.Y.Z` tag and the labels
   of the PRs merged since then (`scripts/release_version.py`).
2. It runs the full test suite on that exact commit (the same `Tests`
   workflow as CI).
3. It creates the tag on that commit and a GitHub Release with generated
   notes (the PRs merged since the previous release).

If the tests fail, nothing is tagged. Fix it in a new PR; the next merge
releases everything since the last tag.

## Choosing the version: PR labels

Versions are SemVer tags `vX.Y.Z`. Label the PR before merging it:

| Label | Effect |
|---|---|
| *(none)* | patch: `v0.3.1` → `v0.3.2` |
| `release:minor` | minor: `v0.3.1` → `v0.4.0` (new features) |
| `release:major` | major: `v0.3.1` → `v1.0.0` (breaking changes to tools, config or deployment) |
| `release:skip` or `skip-release` | no release for this PR (docs, CI tweaks). Its changes ship with the next release |

- If several PRs are merged before a release runs, the largest bump among them wins.
- A direct push to `main` (no PR) counts as a patch.
- The very first release is `v0.1.0`.
- A commit that already has a tag is never released twice, so re-running the workflow is safe.
- Pre-release tags (`-rc.1` and the like) aren't supported.

## Releasing by hand, from the GitHub UI

Go to **Actions → Release → Run workflow**, keep the branch on `main`, and
pick a bump:

- `auto`: from the labels, but always at least a patch.
- `patch`, `minor` or `major`.

This releases `main`'s current head, after running the tests. It does
nothing if that commit is already released.

**Don't use "Draft a new release" on the Releases page.** It publishes
without running the tests, and the tag it creates can clash with the next
automatic release. If one was made by mistake, delete that release and its
tag, then re-run the workflow.

Never move or delete a tag that has been deployed. Deployments pin tags, so
ship a fix as the next patch instead.

## Where the version lives

Git tags are the only source of truth. The `version` in `pyproject.toml` is
a fixed placeholder: it is never bumped, so releases don't touch `uv.lock`
and need no bot commits to `main`.

A build learns its version from the `TRAIN_WITH_GPT_VERSION` build arg. The
self-test's **Build info** check shows it together with the commit
(`train-with-gpt v0.2.0; GIT_SHA abc1234; ...`). If the build arg is
missing, the check shows `<placeholder>+dev` and a warning. To build a
release image:

```bash
git checkout v0.2.0
docker build --build-arg TRAIN_WITH_GPT_VERSION=v0.2.0 \
             --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
```
