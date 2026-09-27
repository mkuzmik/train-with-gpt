# Instructions for Copilot code review

The maintainer reads the **PR description**, not every line of the diff. Your
most important job is to make sure the description is an accurate, complete
account of what the PR does.

## 1. Description ↔ code consistency (highest priority)

Compare the PR title and description against the diff and flag every
discrepancy:

- **Undescribed behaviour changes**: anything a user, an operator or an AI
  client calling the MCP tools would notice (new/removed/renamed tools or
  parameters, changed tool output, changed defaults, auth or access changes,
  new env vars or secrets, data stored, migrated or deleted) that the
  description doesn't mention.
- **Claims the code doesn't back up**: a described feature, fix, safeguard or
  test that isn't in the diff, or works differently than described.
- **Stale description**: text describing an earlier iteration of the PR.
- **Missing or understated risk**: breaking changes, compatibility or migration
  impact (existing users, stored data, deployed instances, stdio vs hosted
  mode), steps an operator must take before deploying, and security or privacy
  impact.
- **Release label** (`release:major|minor|patch|skip`) that doesn't match the
  change: breaking → major, new functionality → minor, fixes → patch,
  nothing shipped → skip.

Report these as review comments with a concrete suggested wording for the
description.

## 2. What a good description looks like

Written for the maintainer, in terms of **functionality**, not implementation:
what changes for users and operators, compatibility and migration risk,
decisions for the maintainer, and how to verify. It should **not** be a
file-by-file or class-by-class changelog ("added class X", "modified file Y");
if the description is mostly that, say so and suggest a functional summary.

## 3. Then the code

Review for correctness, security and tests as usual. Also flag:

- secrets or personal data (real athlete/activity ids, names, health metrics)
  anywhere in code, tests, fixtures or docs — this repository is public;
- new processing, storage or caching of Strava data (restricted by the Strava
  API Agreement; new data features belong on the intervals.icu path);
- deployment-specific details (app names, hosting config) — this repo is a
  generic template.

Skip style nitpicks that don't affect behaviour.
