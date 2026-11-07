You are reviewing a pull request in this repository. Read `AGENTS.md` and
`.github/copilot-instructions.md` first: they define what matters here.

Use `gh pr view` (title, description, labels, existing comments) and
`gh pr diff` to see the change, and read the surrounding code where you need
context.

Check, in this order:

1. **Description vs. code.** The maintainer reviews mainly the description.
   Flag behaviour changes it doesn't mention, claims the diff doesn't back up,
   text left over from earlier iterations, and understated compatibility,
   migration or deployment risk. Suggest concrete wording.
2. **Release label.** Exactly one of `release:major|minor|patch|skip`, and it
   must match the change.
3. **Hard rules.** No secrets, no personal data about real people (tests and
   docs use synthetic data only), no new processing/storage/caching of Strava
   data, and no instance-specific deployment details.
4. **Correctness.** Real bugs, edge cases, error handling, and missing tests
   (bug fixes need a test that fails without the fix).

How to report:

- Post an inline comment on the relevant line for each specific finding, using
  a GitHub `suggestion` block when the fix is small and clear-cut.
- Post one short top-level summary comment with `gh pr comment`. If nothing
  needs changing, say so in one line.
- This review runs again on every push. Read the existing comments first and
  don't repeat points already raised; mention only what's new or still
  unaddressed.
- Be concise and only report findings you're confident about. Skip style
  nitpicks.
