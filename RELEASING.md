# Releasing

Releases are SemVer tags `vX.Y.Z` on `main`. The version in `pyproject.toml`
is the single source of truth: the tag must be exactly `v` + that version.
Pre-release tags (`-rc.1` and the like) aren't supported.

1. **Bump the version** in a PR. Pick the next version (MAJOR for breaking
   changes to tools, config or deployment; MINOR for new features; PATCH for
   fixes), then:

   ```bash
   # edit [project] version in pyproject.toml, e.g. 0.2.0
   uv lock                      # uv.lock records the project version too
   git commit -am "Release 0.2.0"
   ```

   Open the PR, let CI pass (it runs `uv lock --check`), merge it.

2. **Tag the merge commit** and push the tag:

   ```bash
   git fetch origin
   git tag -a v0.2.0 -m "v0.2.0" <merge commit sha on origin/main>
   git push origin v0.2.0
   ```

3. **The `Release` workflow** (`.github/workflows/release.yml`) then:
   - checks the tag matches `pyproject.toml` (`scripts/check_release_tag.py`)
     and that the tagged commit is on `main`;
   - runs the full test suite (the same `Tests` workflow as CI);
   - creates a GitHub Release with generated notes (merged PRs since the
     previous tag).

   If a check fails, no release is created. Delete the tag
   (`git push --delete origin v0.2.0 && git tag -d v0.2.0`), fix the problem
   in a new PR and tag again. Never move a tag that already has a release:
   deployments pin tags, so cut a new PATCH version instead.

## Which version is running?

The server reports its package version and the commit it was built from in
the self-test's **Build info** check (`train-with-gpt 0.2.0; GIT_SHA
abc1234; ...`). Pass the commit when building the image:

```bash
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
```
