You are reviewing a pull request in this repository. Read `AGENTS.md` and
`.github/copilot-instructions.md` first: they define what matters here.

Use `gh pr view` (title, description, labels, existing comments) and
`gh pr diff` to see the change. Then **read every changed source file in full**,
not just the diff hunks, plus the code the change calls into or is called
from. A review that only skims the diff is not enough: take the time a careful
human reviewer would.

Check, in this order:

1. **Description vs. code.** The maintainer reviews mainly the description.
   Flag behaviour changes it doesn't mention, claims the diff doesn't back up,
   text left over from earlier iterations, and understated compatibility,
   migration or deployment risk. Pay special attention to anything that
   deletes, overwrites or replaces user data (for example an update that
   silently drops a field the caller didn't resend): it must be stated in the
   description. Suggest concrete wording.
2. **Release label.** Exactly one of `release:major|minor|patch|skip`, and it
   must match the change.
3. **Hard rules.** No secrets, no personal data about real people (tests and
   docs use synthetic data only), no new processing/storage/caching of Strava
   data, and no instance-specific deployment details.
4. **Correctness.** Go through the changed code path by path:
   - **Inputs that reach an external system.** For every value the code sends
     to an external API or writes in a format another system parses (text
     syntaxes, query strings, file formats), ask how that system will
     interpret it. Look for values that pass this repo's validation but carry
     special meaning on the other side (keywords, separators, units, magic
     phrases), and for validation that refuses some cases but misses close
     variants.
   - **Edge cases and errors.** Empty, missing, boundary and malformed
     inputs; partial failures halfway through a multi-step operation; error
     messages that would mislead an AI client.
   - **Tests.** New behaviour and every validation rule should have a test;
     bug fixes need a test that fails without the fix. Name the missing case.

   For each candidate finding, trace a realistic path to the failure before
   reporting it. Weigh it in proportion: a race that needs two simultaneous
   calls from one user's chat client is usually not worth the code to prevent
   it; a value an AI client could plausibly send that silently does the wrong
   thing is.

How to report:

- Post an inline comment on the relevant line for each specific finding. Start
  it with a severity (**High**, **Medium** or **Low**) and say what goes wrong
  and for whom. Use a GitHub `suggestion` block when the fix is small and
  clear-cut.
- Post one short top-level summary comment with `gh pr comment`: the number of
  findings by severity, plus anything that isn't tied to a line. If nothing
  needs changing, say so in one line and say what you checked.
- This review runs again on every push. Read the existing comments first
  (yours and other reviewers') and don't repeat points already raised; mention
  only what's new or still unaddressed.
- Only report findings you're confident about. Skip style nitpicks.
