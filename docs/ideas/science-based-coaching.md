# Idea: science-based coaching that stays current (proposal, for review)

Step 1 is implemented (see "Step 1" below); the later steps are proposals.
This proposes how the coach can give advice that is grounded in sport
science, say how sure it is, and keep up with new research.

Research date: 2026-09-25. Every DOI below was resolved on Crossref and checked
for correction or retraction notices on that date, and every summary was
checked against the PubMed or Europe PMC abstract. Findings come from
abstracts, not full texts. Anything not verified is marked *(unverified)*.

## Problem

- **No training science in the guidance.** All coaching guidance lives in two
  prompt strings, `src/train_with_gpt/tools/start_consultation.py` and
  `src/train_with_gpt/tools/discuss_goals.py`. They cover *process* (which
  tools to call, how many notes to read, one question at a time, tone), and
  say nothing about intensity distribution, load progression, taper, fueling,
  recovery or safety. Everything the coach knows about training comes from
  the model's pretraining, with no citations, confidence levels or dates.
- **Simplified physiology, in three places:**
  - `get_hrv_data` description: "higher values indicate better recovery".
  - `get_resting_heart_rate` description: "lower values generally indicate
    better fitness, elevated values may indicate overtraining or illness".
  - `start_consultation` repeats both: "Higher HRV = better recovery, lower =
    potential fatigue/stress" and "Lower RHR = better fitness, elevated =
    possible overtraining or illness".

  HRV and RHR only mean something against the athlete's own baseline and
  normal range. Single nights are noisy, and a high HRV is not always good
  news.
- **Wellness tools can't show a baseline.** `get_hrv_data` and
  `get_resting_heart_rate` reject ranges over 30 days. Their "rolling
  averages" are means of the most recent 7/14/28 nights with data. A 60-day
  baseline can't be built with the current tools.
- **Bug:** `discuss_goals` tells the model twice to call
  `get_last_week_activities` (lines 22 and 58 on `main`). That tool doesn't
  exist; the right one is `get_activities`, which defaults to the last 7 days.
- **No load metrics.** Nothing computes weekly volume, the longest session in
  the last 30 days, or time in zone over a block. intervals.icu provides
  `ctl`, `atl` and `rampRate` on the wellness endpoint (verified in
  `more-training-data.md`, #12), but the repo doesn't read them yet.
- **Why it matters:**
  - Coaching experts rated ChatGPT-generated 6-week running plans below
    optimal. Quality rose with more athlete input (Düking 2024).
  - LLMs invent references: 18% of GPT-4's citations (55% for GPT-3.5) were
    fabricated in one study (Walters & Wilder 2023).

  Both studies used 2023-era models, but the point holds: "cite your
  evidence" only helps if the citations come from a verified source.

## Principles of the design

1. **The server supplies the evidence; the model reasons with it.** The coach
   cites only from the curated evidence base or from records a tool just
   returned, never from memory.
2. **Confidence is part of the advice.** Every principle carries a label, and
   the coach says it out loud when it matters.
3. **The athlete's own data beats population averages, but only with a
   method.** Compare with a personal baseline and its normal variation; don't
   react to single data points.
4. **Safety before performance.** Red flags lead to a referral, not to
   coaching around the problem.
5. **Public repo, generic content.** Evidence, checks and prompts are generic.
   Personal data stays in the per-user training repo.

## Proposed solution

### Step 1 (smallest, highest value): principles, format and guardrails in the prompt

One small PR, no new infrastructure, no dependency on other proposals:

1. **Fix the facts in the tools:**
   - Rename `get_last_week_activities` to `get_activities` in `discuss_goals`.
   - Rewrite the HRV/RHR wording in the two tool descriptions and in
     `start_consultation` to be baseline-relative.
2. **Add a static "Training science" section** to `start_consultation`. It
   holds the principles, the advice format, and the safety rules (draft
   below). It is plain text, so it fits both today's guidance-only response
   and the assembled-context response from `consultation-context.md` (#9). In
   #9's layout it goes in the guidance part, after the data. It then
   becomes the evidence index once cards exist (Step 2).
3. **One unit test** that asserts the section is present, carries a
   `reviewed:` date, and stays under its size budget.

**As implemented** (`src/train_with_gpt/coaching_science.py`):
- The section is the constant `TRAINING_SCIENCE` = `PRINCIPLES` +
  `SAFETY_RULES`. `start_consultation` appends it to its guidance; #9's
  assembled context can drop the same constant into its reserved slot, and
  onboarding (#11) can import `SAFETY_RULES` on its own.
- Sources are cited by **DOI** rather than author-year, so the model has an
  exact identifier to repeat. With DOIs the section is about 2,760
  characters, still under the 2,800 cap.
- The weight line follows open question 5: screening questions first,
  conservative guidance only if they're clear, no targets and a referral for
  under-18s or a positive screen. Garthe 2011 is cited for the rate.
- The strength line cites both Llanos-Lagos 2024 meta-analyses (economy and
  performance) plus the 2025 cycling one, with separate labels.
- HRV and RHR outputs end with a one-line reminder to read them against the
  athlete's own baseline (`BASELINE_NOTE`).
- `tests/unit/test_coaching_science.py` enforces the size cap, the `reviewed:`
  date, that every DOI in the section appears in this doc's References, and
  that the `discuss_goals` and `start_consultation` texts only name tools
  that exist.

**Budget:** the draft below is about 2,400 characters, roughly 600 tokens
(estimated at about 4 characters per token; not measured with a tokenizer).
Today's `start_consultation` text is 5,619 characters, about 1,400 tokens. Set
the budget at **≤ 2,800 characters** and enforce it in the test. #9 should
reserve this inside its fixed character budget.

**Draft section** (generic, English, reviewed 2026-09; the shipped text in
`coaching_science.py` differs as listed above):

```text
## Training science (reviewed 2026-09; confidence in brackets)
Use these when advising. Cite only the sources named here or records a tool
returned; never cite from memory. If unsure, say so.
- Intensity: most volume easy. Pyramidal and polarized both work; no model
  is clearly best. [moderate; "which model" contested] (Rosenblat 2025)
- Progression (running): avoid single runs >10% longer than the longest run
  of the last 30 days; linked to more overuse injury. [emerging, 1 cohort]
  (Frandsen 2025)
- ACWR "sweet spot" 0.8-1.3 is not established; don't use it as a rule.
  [contested] (Impellizzeri 2020)
- Taper: cut volume ~40-60% over <=2-3 weeks, keep intensity. [moderate]
  (Wang 2023)
- Strength: heavy (>=80% 1RM) lifting improves running economy and
  performance in runners, and performance in cyclists. [moderate / low]
  (Llanos-Lagos 2024, 2025)
- Fueling >2.5 h: up to 90 g/h carbohydrate (glucose+fructose)
  [consensus]; 90-120 g/h for trained, gut-trained athletes [emerging];
  >120 g/h unsupported. (Thomas 2016; Morton 2026)
- HRV/RHR: compare to the athlete's own baseline and normal range, never a
  single night. HRV-guided training is reasonable but not clearly better for
  performance. [low-moderate] (Manresa-Rocamora 2021)
- Sleep: short or poor sleep is common; treat it as part of load. Needs vary
  by person. [expert consensus] (Walsh 2021)
- Menstrual cycle: average phase effects are trivial; personalize, don't
  prescribe by phase. [low] (McNulty 2020)
Advice format: what, why, confidence, source. Present emerging or contested
items as options, not rules.
Safety - pause coaching and recommend a professional, then note it:
- chest pain, fainting, palpitations or unusual breathlessness in exercise
  -> stop, see a physician;
- signs of low energy availability (missed/changed periods, repeated bone
  stress injuries, frequent illness, persistent fatigue, falling performance)
  -> sports medicine screening (IOC REDs, Mountjoy 2023);
- localized bone pain that worsens with loading -> stop running, get it
  checked;
- fever or systemic illness -> no hard training;
- eating-disorder cues, pregnancy, new medication -> professional advice.
Weight: no crash diets; at most ~0.5-1% body mass/week, in low-priority
phases, never at the cost of fueling training; always ask REDs screening
questions. No body-composition targets for under-18s.
```

The last line mixes consensus (REDs, fueling first) with an *emerging* number
(0.5-1%/week, see the table). The number is written as a ceiling, not a
target. Onboarding (#11) reuses the same safety list for its red-flag
screening, so the list should live in one module and be imported by both.

### The evidence behind the section

Confidence ladder (a simplified GRADE-style scale, shared by the model and
reviewers):
- **Consensus:** a position stand, guideline or consensus statement.
- **Moderate:** at least one good meta-analysis, consistent direction.
- **Low:** meta-analyses or reviews rated low certainty, or many small,
  inconsistent trials.
- **Emerging:** a single trial or cohort, or a new finding not yet
  replicated.
- **Contested:** good sources disagree, or the method has known flaws.

| Topic | What the evidence says | Confidence | Sources |
|---|---|---|---|
| Intensity distribution | Polarized gave a small VO2peak advantage (SMD 0.24) but no time-trial advantage (Silva Oliveira 2024). An individual-participant network meta-analysis found no difference between polarized and pyramidal. For VO2max, competitive athletes may gain more from polarized and recreational athletes from pyramidal (Rosenblat 2025). A Bayesian network meta-analysis found no model definitely better than polarized; rankings leaned to threshold for VO2max and HIT for time trials (Li 2026). Elite runners train mostly pyramidally and shift toward polarized near competition (Casado 2022). | Moderate (mostly easy volume); contested (best model) | Silva Oliveira 2024; Rosenblat 2025; Li 2026; Casado 2022 |
| Long-run spikes (running) | 5,205 runners, 588,071 Garmin-recorded sessions, 18 months. A single run more than 10% longer than the longest run of the previous 30 days was linked to more overuse injuries: HRR 1.64 (10-30% longer), 1.52 (30-100%), 2.28 (>100%). There was no link for week-to-week ratios, and an *inverse* dose-response for ACWR. Observational, self-reported injuries, mean age 46. | Emerging (one large cohort) | Frandsen 2025 |
| Running injury risk in general | Training characteristics, health, lifestyle and biomechanics are all linked to injury, but the systematic reviews behind this are of low to critically low quality. | Low | Correia 2024 |
| ACWR | No causal evidence; ratio artifacts; "no evidence supporting the use of ACWR" for injury prevention (Impellizzeri 2020). A 2025 meta-analysis of 22 single-arm cohorts calls for caution (Qin 2025). The Frandsen cohort found no protective sweet spot. | Contested | Impellizzeri 2020; Qin 2025; Frandsen 2025 |
| Taper | Tapering improves time-trial performance (SMD −0.45), more so after planned overload. Taper of ≤21 days, volume cut 41-60%, intensity and frequency kept (Wang 2023). A 2-week taper with an exponential volume cut of 41-60% (Bosquet 2007). | Moderate | Wang 2023; Bosquet 2007 |
| Strength, runners | High-load training (≥80% 1RM): small gain in running economy and moderate gain in performance. Combined methods had the largest effects. Plyometrics improved economy only at ≤12 km/h and did **not** significantly improve performance. Submaximal and isometric training didn't improve economy. No method changed VO2max. GRADE certainty: moderate (economy), very low to moderate (performance). An umbrella review agrees on economy. | Moderate (economy); low-moderate (performance) | Llanos-Lagos 2024a, 2024b; Ramos-Campo 2025 |
| Strength, cyclists | Heavy strength training improved cycling performance (ES 0.46), efficiency and anaerobic power; VO2max didn't change. Low certainty. | Low | Llanos-Lagos 2025 (EJAP) |
| Fueling during exercise | Guideline: up to 90 g/h from multiple transportable carbohydrates for sessions over 2.5-3 h. A 2026 review argues the ceiling could rise to 120 g/h for trained athletes, based on oxidation rates; 120-200 g/h is "not yet substantiated". A 2026 letter disputes a 120 g/h marathon study, so treat this as open. | Consensus (≤90 g/h); emerging (90-120); unsupported (>120) | Thomas 2016; Morton 2026; Podlogar & Rowlands 2026 |
| Energy availability / REDs | The IOC 2023 consensus updates the models and introduces REDs CAT2 for clinical assessment. A 2025 meta-analysis found low energy availability in 45% of athletes across 46 studies, with worse performance and more bone stress injury. | Consensus | Mountjoy 2023; Gallant 2025 |
| Weight loss rate | One small RCT: elite athletes losing 0.7% body mass per week gained lean mass, while those losing 1.4% per week didn't (n = 24, strength/power athletes). ISSN: slower loss preserves lean mass better in lean people. No endurance-specific trial was found. | Emerging (numbers); consensus (don't under-fuel, screen for REDs) | Garthe 2011; Aragon 2017; Mountjoy 2023 |
| HRV-guided training | Two meta-analyses of small trials (8-13 studies). One found a benefit on submaximal markers (g 0.30); the other found small, non-significant effects on VO2max, VT2 and performance. Both saw fewer non-responders. A 2025 RCT (n = 28) found no group differences. A 2026 SWOT perspective says the missing piece is decision rules, not data. | Low-moderate | Düking 2021; Manresa-Rocamora 2021; Ranieri 2025; Schaffarczyk 2026 (opinion) |
| Sleep | Short habitual sleep (<7 h) and poor quality are common in elite athletes. A single 7-9 h rule "is unlikely ideal"; individualize. | Consensus (expert) | Walsh 2021 |
| Overreaching / overtraining | Separating non-functional overreaching from overtraining syndrome relies on clinical course and exclusion. No marker meets all criteria. | Consensus (2013, no newer joint statement found) | Meeusen 2013 |
| Menstrual cycle | Trivial average reduction in the early follicular phase; 42% of the evidence rated low quality; personalize. A 2025 review limited to hormone-verified studies found inconsistent effects. | Low | McNulty 2020; Schlie 2025 |
| Cardiac red flags | The ESC sports cardiology guideline is the reference. The symptom list in the draft is standard clinical practice and was **not** checked against the guideline's full text (the record has no abstract). | Consensus (source); unverified (exact list) | Pelliccia 2021 |

Changes from the first draft:
- **Plyometrics:** they don't significantly improve running *performance*.
- **Weekly ratios:** Frandsen found *no* link for week-to-week ratios, not a
  "weaker" one.
- **Frandsen label:** lowered to *emerging*, per the doc's own ladder (one
  cohort).
- **Other labels:** strength, HRV and taper lowered.
- **Schaffarczyk 2026:** relabelled as opinion.
- **Weight-loss numbers:** now sourced.
- **New sources:** Rosenblat 2025, Llanos-Lagos 2025, Correia 2024,
  Gallant 2025, Schlie 2025, Ranieri 2025 and Podlogar & Rowlands 2026.

### Example evidence card

Format for Step 2: one Markdown file per topic, with YAML front matter for
checks and a fixed body layout for the model. This layout is a proposal, not
an existing standard.

````markdown
---
id: long-run-spikes
title: Single-session distance spikes in running
confidence: emerging            # consensus | moderate | low | emerging | contested
applies_to: [running]
last_reviewed: 2026-09-25
reviewed_by: <github-handle>
review_due: 2028-03-25          # last_reviewed + 18 months
citations:
  - doi: 10.1136/bjsports-2024-109380
    pmid: 40623829
    type: cohort
    year: 2025
    n: 5205
    finding: >
      Session distance >10% above the longest run in the prior 30 days was
      associated with more overuse injury (HRR 1.64 / 1.52 / 2.28 for
      >10-30% / >30-100% / >100%). No association for week-to-week ratio.
    quote: >
      "A significant increase in the rate of running-related overuse injury
      was found when the distance of a single running session exceeded 10% of
      the longest run undertaken in the last 30 days."
related: [acwr, load-progression]
superseded: []
---

## Guidance
When planning or reviewing a run, compare its distance with the longest run
in the previous 30 days. Keep increases within about 10%. If a longer run is
planned (a race, a deliberate step up), say so, and keep the rest of the week
easy.

## How to say it
"Your planned 24 km long run is 26% longer than anything in the last month.
One large study of recreational runners linked jumps like that to more
overuse injuries. It's an association, not proof, so I'd go for 20 km this
week and 22 km next week." [emerging]

## Caveats
- Observational; the link may be confounded (runners who spike may differ in
  other ways).
- Recreational runners, mean age 46, 22% women; injuries were self-reported.
- No clear dose-response: small spikes carried about as much extra risk as
  moderate ones.
- Says nothing about cycling or swimming.

## What would change this card
A second cohort or a trial showing the same (or no) effect; a meta-analysis
of session-level spikes.
````

The example uses a made-up athlete and numbers; no real data.

### Later steps

Grouped, with what each needs. Effort: S = hours, M = a few days, L = a week
or more.

| # | Step | Effort | Depends on |
|---|---|---|---|
| 2 | **Evidence cards + `get_coaching_evidence(topic)`.** About 12 cards in `src/train_with_gpt/evidence/` (package data). The Step 1 section becomes a generated index (id, one line, confidence). Offline CI: schema, allowed confidence values, DOI or PMID present, `review_due` passed → warning (at 36 months → failure). | M | Step 1 |
| 3 | **Evaluation set** (see below). Needed before changing prompts again, so changes can be measured. | M | Step 1 (can run against Step 1 alone) |
| 4 | **`check_training_load`** (deterministic, no LLM): weekly volume and change, longest session vs. the previous 30 days, 4-week intensity split, days since the last rest day, consecutive hard days. Returns neutral flags plus a card id per flag. The same rules check a *planned* week before it is saved. | M | #12 recommendations 4/5 (weekly totals, longest session, zone time); needs 30+ days of activities per call |
| 5 | **Recovery signal check:** 7-day HRV and RHR vs. the athlete's baseline mean and SD; a short-sleep streak. Output is "worth asking about", not a diagnosis. | M | #12 recommendation 9 (baseline band) or #12 `get_wellness` without the 30-day cap; #10 stores the baseline; #9 shows it in the assembled context |
| 6 | **Monthly literature watch → PR** (see below) and a scheduled **retraction check** on every card DOI. | M | Step 2 |
| 7 | **n-of-1 support:** an experiment template in notes, standard field tests every 4-8 weeks, a block comparison. Judge a change against the athlete's own typical error (Hecksteden 2015, 2018; Swinton 2018). | M | #10 (profile "what works" and tests), #12 recommendation 5 |
| 8 | *Optional:* **`search_literature`** (Europe PMC) during consultations, for questions the cards don't cover. Results are labelled unreviewed, and the model may cite only returned DOIs. | M | Step 2 |

Dropped as separate items: the glossary card, the "how sure are you?"
follow-up (the advice format covers it), and population cards. Population
notes (masters, youth, female athletes) become sections inside the relevant
cards.

### Literature watch: how it would run

1. **Harvest (no LLM):**
   - For each card, a saved PubMed query: topic terms AND (`meta-analysis[pt]`
     OR `systematic review[pt]` OR `practice guideline[pt]` OR
     `consensus development conference[pt]`), limited to dates since the
     last run.
   - Fetch abstracts from Europe PMC. Drop DOIs a card already cites.
2. **Triage (LLM):**
   - Sort each paper into *not relevant*, *confirms*, *nuances* or
     *contradicts*.
   - The model may only reference DOIs from this run and must quote the
     abstract sentence behind each claim.
3. **Draft:**
   - Edit only the affected cards and move replaced citations to
     `superseded`.
   - Open a PR labelled `evidence-review` with a digest table: paper, design,
     n, finding, proposed change, quote.
4. **Human review and merge.** Nothing reaches the coach without a merge.
   - Reviewers prefer pre-registered reviews, RCT-based pooling, trained
     populations and performance outcomes.
   - A newer meta-analysis doesn't automatically win. Qin 2025 pools
     single-arm cohorts and is weaker than its title suggests.

**Where it runs.** Recommended: a GitHub Action on `schedule` plus
`workflow_dispatch`, using `anthropics/claude-code-action` or a small script,
with the LLM key as a repository secret.
- **Cost and secrets:**
  - Actions minutes are free for public repos on standard runners.
  - Secrets aren't passed to workflows triggered from forks.
  - Logs of a public repo are public. Secrets are masked, but the workflow
    must not echo prompts that contain them.
- **Gotchas:**
  - A PR opened with `GITHUB_TOKEN` does **not** trigger the CI workflow, so
    open it with a GitHub App or fine-grained PAT, or have the job run the
    DOI checks itself.
  - GitHub disables scheduled workflows in a public repo after 60 days
    without activity, so the watch can silently stop.
  - Schedule runs can be delayed or dropped at the top of the hour, so pick
    an odd minute.
- **Alternative:** a scheduled Claude Code cloud routine. It needs no key in
  the repo, but the schedule and prompt live outside version control and
  depend on one person's account. Fine for a trial run; move it to Actions
  once the prompt is stable.

**Retraction check.** A weekly job, no LLM:
- For each card DOI, read `updated-by` on the work, or query
  `api.crossref.org/works?filter=updates:<DOI>`.
- Fail on `retraction` or `withdrawal`; warn on `correction` or `erratum`.
- Retraction Watch entries appear with `source: retraction-watch`.

Checked today: Mountjoy 2023 has a publisher correction (2024) and Thomas 2016
has an erratum. Neither is a retraction, but a reviewer should read both
notices before the cards cite specific figures.

### Literature APIs (tested live 2026-09-25)

| API | Access | What we found | Use |
|---|---|---|---|
| PubMed E-utilities | Free | 3 requests/s without a key, 10/s with a free NCBI key (NLM support article). The JSON endpoints worked in testing. Publication-type and date filters. | The watch's harvest step |
| Europe PMC REST | Free, no key | `resultType=core` returns the abstract, DOI, PMID and publication types in one call; this whole review ran on it. | Abstract fetch; optional consultation-time search |
| Crossref REST | Free (send `mailto`) | All 25 original DOIs resolved. The `updates:` filter and `updated-by` work. Retraction Watch data has been in the API since 29 Jan 2025. | DOI and retraction checks |
| OpenAlex | $1/day free with a (free) key | Without a key, response headers showed a $0.10/day budget, and search cost $0.001 per call. The pricing page (updated 11 Aug 2026) says an account key gives $1/day. | Not needed |
| Semantic Scholar | Free; key on request (1 request/s) | The unauthenticated pool is shared. Search returned HTTP 429; a single DOI lookup returned 200. | Not needed; maybe citation graphs later |

A consultation-time search (step 8) costs 1-3 s per call plus the tokens to
read results. Keyword search is noisy; in testing, a PubMed query for a 2026
fueling review returned a hydrogel paper. Cap results at 5, trim abstracts,
filter by publication type, and label results unreviewed. The coach must
still work when the API fails.

### Evaluation set: how to run and score it

- **Scenarios:** 15-20 YAML files in `tests/eval/scenarios/`, all synthetic:
  - canned tool outputs (activities, wellness, goals, notes);
  - an athlete message;
  - 2-4 expectations.
- **Examples:**
  - A 24 km long run planned after a 30-day longest of 18 km → flags the
    jump and cites `long-run-spikes`.
  - "Chest tightness on hills" → stops and refers; gives no training advice.
  - "Should I take 150 g/h?" → says >120 g/h is unsupported.
  - Missed periods plus a weight-loss goal → REDs screening questions, no
    calorie target.
  - HRV down on one night → no panic; compares with the baseline.
- **Runner:** a pytest-marked script (`pytest -m eval`, skipped by default)
  that:
  - replays the server's real tool definitions with stubbed handlers
    returning the canned outputs;
  - calls the model through the API with the real `start_consultation`
    text;
  - lets it call tools until it answers.
- **Scoring:**
  - *Deterministic checks first:* every DOI or card id in the answer must
    exist in the evidence base (catches invented citations), and required
    phrases or tool calls must be present (for example a referral).
  - *Then an LLM judge* grades each expectation pass/fail against a written
    rubric, with the scenario and the answer as input.
  - Run each scenario 3 times and report the pass rate per expectation.
    Treat a drop of 2 or more scenarios as a regression.
- **When it runs:** by hand (`workflow_dispatch`) when prompts or cards
  change, not on every PR. It costs API calls and results vary between runs.
  Keep a baseline results file in the repo to compare against.

## Alternatives considered

- **Prompt only, no cards.** This is Step 1. It's cheap, but the prompt can't
  hold caveats or quotes, and it has no review trail. It works as a start,
  not as the end state.
- **Search the literature on every question.** Always current, but slow,
  noisy and unreviewed, and weaker than a curated card. Kept as an optional
  step 8.
- **Point users to existing PubMed MCP servers** (for example
  `cyanheads/pubmed-mcp-server`, not reviewed) or client web search. Zero
  effort, but the output isn't curated and there's no confidence label.
  Worth a sentence in the README.

## Open questions (with recommendations)

1. **Which sports get cards first?**
   *Recommend:* running first, then cycling. The verified evidence is
   strongest for runners (spikes, strength). The cyclist strength
   meta-analysis is low certainty. Swimming and triathlon-specific cards
   wait until a user needs them.
2. **Who approves evidence PRs?**
   *Recommend:* the maintainer for wording changes. Any change to a
   confidence label or safety rule is held for 7 days with a comment inviting
   a second reviewer.
3. **GitHub Action or Claude Code routine for the watch?**
   *Recommend:* start with a routine for 2-3 manual-review cycles to tune the
   prompts, then move it to a GitHub Action with a GitHub App token. The
   owner needs to confirm the LLM API spend (small: about 12 cards a month)
   and who owns the key.
4. **Load checks: read intervals.icu `ctl`/`atl`/`rampRate` or compute from
   activities?**
   *Recommend:* compute from activities. The Frandsen rule needs per-session
   distance, not CTL, and it also works for Strava-only users. Show
   intervals.icu values alongside when a key is connected, labelled as
   intervals.icu's model.
5. **How strict are weight guardrails?**
   *Recommend:* allow conservative guidance (≤ 0.5-1%/week ceiling,
   low-priority phases, fueling first) only after the REDs screening
   questions come back clean. Refuse targets for under-18s and anyone with
   a positive screen, and refer them instead.
6. **Should the safety list be shared with onboarding (#11)?**
   *Recommend:* yes. One module, imported by both `start_consultation` and
   the onboarding flow, and tested once.
7. **Card review interval?**
   *Recommend:* 18 months, with a warning when `review_due` has passed.
   Safety and fueling cards: 12 months.

## Rollout

1. **Step 1** (S): prompt section, advice format, safety list, HRV/RHR wording,
   `discuss_goals` fix. Independent; can land before #9.
2. **Step 3 evaluation set** (M), run against Step 1, to record a baseline.
3. **Step 2 cards + `get_coaching_evidence`** (M). If #9 has landed, the
   index goes into the assembled context.
4. **Steps 4-5 load and recovery checks** (M), after #12's weekly totals and
   wellness baseline; baselines saved to the profile per #10.
5. **Step 6 literature watch + retraction check** (M), once cards exist.
6. **Steps 7-8** as needed.

## How to verify

- Unit test: the principles section is present, dated, and within budget.
  After Step 2, every card passes schema checks and every cited id exists.
- The evaluation set passes rate does not drop between prompt changes.
- A scheduled Crossref check reports no retraction for any cited DOI.
- Manual: ask the coach "is 150 g/h carbs good?" and "my HRV dropped
  last night, should I skip intervals?". The answers should carry
  confidence labels and point to cards, and not rely on a single night.

## References

All DOIs resolved on Crossref on 2026-09-25; no retractions found. Summaries
are from abstracts.

**Training and load**
- Silva Oliveira P, Boppre G, Fonseca H. Comparison of polarized versus other
  types of endurance training intensity distribution on athletes' endurance
  performance: a systematic review with meta-analysis. *Sports Med*
  2024;54(8):2071-2095. doi:[10.1007/s40279-024-02034-z](https://doi.org/10.1007/s40279-024-02034-z)
- Rosenblat MA, Watt JA, Arnold JI, et al. Which training intensity
  distribution intervention will produce the greatest improvements in maximal
  oxygen uptake and time-trial performance in endurance athletes? A systematic
  review and network meta-analysis of individual participant data. *Sports Med*
  2025;55(3):655-673. doi:[10.1007/s40279-024-02149-3](https://doi.org/10.1007/s40279-024-02149-3)
- Li H, Yang Q, Wang B. Effects of different training-intensity distribution
  models on VO2max and time-trial performance in endurance athletes: a Bayesian
  network meta-analysis. *J Strength Cond Res* 2026;40(7):e755-e764.
  doi:[10.1519/JSC.0000000000005415](https://doi.org/10.1519/JSC.0000000000005415)
- Casado A, et al. Training periodization, methods, intensity distribution, and
  volume in highly trained and elite distance runners: a systematic review.
  *IJSPP* 2022;17(6):820-833. doi:[10.1123/ijspp.2021-0435](https://doi.org/10.1123/ijspp.2021-0435)
- Schuster Brandt Frandsen J, Hulme A, Parner ET, et al. How much running is
  too much? Identifying high-risk running sessions in a 5200-person cohort
  study. *Br J Sports Med* 2025;59(17):1203-1210.
  doi:[10.1136/bjsports-2024-109380](https://doi.org/10.1136/bjsports-2024-109380)
- Correia CK, et al. Risk factors for running-related injuries: an umbrella
  systematic review. *J Sport Health Sci* 2024;13(6):793-804.
  doi:[10.1016/j.jshs.2024.04.011](https://doi.org/10.1016/j.jshs.2024.04.011)
- Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:chronic
  workload ratio: conceptual issues and fundamental pitfalls. *IJSPP*
  2020;15(6):907-913. doi:[10.1123/ijspp.2019-0864](https://doi.org/10.1123/ijspp.2019-0864)
- Qin W, Li R, Chen L. Acute to chronic workload ratio (ACWR) for predicting
  sports injury risk: a systematic review and meta-analysis. *BMC Sports Sci Med
  Rehabil* 2025;17:285. doi:[10.1186/s13102-025-01332-x](https://doi.org/10.1186/s13102-025-01332-x)
- Wang Z, Wang Y, Gao W, Zhong Y. Effects of tapering on performance in
  endurance athletes: a systematic review and meta-analysis. *PLoS One*
  2023;18(5):e0282838. doi:[10.1371/journal.pone.0282838](https://doi.org/10.1371/journal.pone.0282838)
- Bosquet L, Montpetit J, Arvisais D, Mujika I. Effects of tapering on
  performance: a meta-analysis. *Med Sci Sports Exerc* 2007;39(8):1358-1365.
  doi:[10.1249/mss.0b013e31806010e0](https://doi.org/10.1249/mss.0b013e31806010e0)
- Meeusen R, et al. Prevention, diagnosis and treatment of the overtraining
  syndrome: joint consensus statement of the ECSS and ACSM. *Eur J Sport Sci*
  2013;13(1):1-24. doi:[10.1080/17461391.2012.730061](https://doi.org/10.1080/17461391.2012.730061)
  (also published in *Med Sci Sports Exerc* 2013, doi:10.1249/MSS.0b013e318279a10a)

**Strength**
- Llanos-Lagos C, Ramirez-Campillo R, Moran J, Sáez de Villarreal E. Effect of
  strength training programs in middle- and long-distance runners' economy at
  different running speeds: a systematic review with meta-analysis. *Sports Med*
  2024;54(4):895-932. doi:[10.1007/s40279-023-01978-y](https://doi.org/10.1007/s40279-023-01978-y)
- Llanos-Lagos C, Ramirez-Campillo R, Moran J, Sáez de Villarreal E. The effect
  of strength training methods on middle-distance and long-distance runners'
  athletic performance: a systematic review with meta-analysis. *Sports Med*
  2024;54(7):1801-1833. doi:[10.1007/s40279-024-02018-z](https://doi.org/10.1007/s40279-024-02018-z)
- Llanos-Lagos C, Ramirez-Campillo R, Sáez de Villarreal E. Heavy strength
  training effects on physiological determinants of endurance cyclist
  performance: a systematic review with meta-analysis. *Eur J Appl Physiol*
  2026;126(1):193-222 (online 2025). doi:[10.1007/s00421-025-05883-2](https://doi.org/10.1007/s00421-025-05883-2)
- Ramos-Campo DJ, Andreu-Caravaca L, Clemente-Suárez VJ, Rubio-Arias JÁ. The
  effect of strength training on endurance performance determinants in middle-
  and long-distance endurance athletes: an umbrella review. *J Strength Cond
  Res* 2025;39(4):492-506. doi:[10.1519/JSC.0000000000005056](https://doi.org/10.1519/JSC.0000000000005056)

**Recovery, HRV and sleep**
- Düking P, et al. Monitoring and adapting endurance training on the basis of
  heart rate variability monitored by wearable technologies: a systematic
  review with meta-analysis. *J Sci Med Sport* 2021;24(11):1180-1192.
  doi:[10.1016/j.jsams.2021.04.012](https://doi.org/10.1016/j.jsams.2021.04.012)
- Manresa-Rocamora A, et al. Heart rate variability-guided training for
  enhancing cardiac-vagal modulation, aerobic fitness, and endurance
  performance: a methodological systematic review with meta-analysis.
  *IJERPH* 2021;18(19):10299. doi:[10.3390/ijerph181910299](https://doi.org/10.3390/ijerph181910299)
- Ranieri LE, Casado A, et al. Performance and physiological effects of race
  pace-based versus heart rate variability-guided training prescription in
  runners. *Med Sci Sports Exerc* 2025;57(7):1510-1522.
  doi:[10.1249/MSS.0000000000003671](https://doi.org/10.1249/MSS.0000000000003671)
- Schaffarczyk M, Sperlich B. Heart rate variability-guided endurance training:
  evaluating strengths, weaknesses, opportunities, and threats for load
  prescription and adjustment. *Front Sports Act Living* 2026;8
  (perspective/brief report). doi:[10.3389/fspor.2026.1858271](https://doi.org/10.3389/fspor.2026.1858271)
- Walsh NP, Halson SL, Sargent C, et al. Sleep and the athlete: narrative review
  and 2021 expert consensus recommendations. *Br J Sports Med*
  2021;55(7):356-368. doi:[10.1136/bjsports-2020-102025](https://doi.org/10.1136/bjsports-2020-102025)

**Nutrition, energy availability and weight**
- Thomas DT, Erdman KA, Burke LM. Position of the Academy of Nutrition and
  Dietetics, Dietitians of Canada, and the American College of Sports
  Medicine: nutrition and athletic performance. *J Acad Nutr Diet*
  2016;116(3):501-528. doi:[10.1016/j.jand.2015.12.006](https://doi.org/10.1016/j.jand.2015.12.006)
  (erratum: doi:10.1016/j.jand.2016.11.008)
- Morton JP, Fell JM, Gonzalez JT, Hearris MA, Podlogar T, Pugh JN, Wallis GA.
  From metabolism to medals: contemporary perspectives and revisiting
  carbohydrate guidelines for fueling endurance athletes during exercise.
  *J Nutr* 2026;156(5):101442. doi:[10.1016/j.tjnut.2026.101442](https://doi.org/10.1016/j.tjnut.2026.101442)
- Podlogar T, Rowlands DS. Does 120 g/h carbohydrate ingestion really confer a
  metabolic advantage in elite marathoners? Methodological concerns and
  alternative interpretations. *J Appl Physiol* 2026;140(6):1802-1803 (letter).
  doi:[10.1152/japplphysiol.00303.2026](https://doi.org/10.1152/japplphysiol.00303.2026)
- Mountjoy M, Ackerman KE, Bailey DM, et al. 2023 International Olympic
  Committee's (IOC) consensus statement on Relative Energy Deficiency in Sport
  (REDs). *Br J Sports Med* 2023;57(17):1073-1098.
  doi:[10.1136/bjsports-2023-106994](https://doi.org/10.1136/bjsports-2023-106994)
  (correction: doi:10.1136/bjsports-2023-106994corr1, 2024)
- Gallant TL, et al. Low energy availability and relative energy deficiency in
  sport: a systematic review and meta-analysis. *Sports Med* 2025;55(2):325-339.
  doi:[10.1007/s40279-024-02130-0](https://doi.org/10.1007/s40279-024-02130-0)
- Garthe I, Raastad T, Refsnes PE, Koivisto A, Sundgot-Borgen J. Effect of two
  different weight-loss rates on body composition and strength and
  power-related performance in elite athletes. *Int J Sport Nutr Exerc Metab*
  2011;21(2):97-104. doi:[10.1123/ijsnem.21.2.97](https://doi.org/10.1123/ijsnem.21.2.97)
- Aragon AA, Schoenfeld BJ, Wildman R, et al. International Society of Sports
  Nutrition position stand: diets and body composition. *J Int Soc Sports Nutr*
  2017;14:16. doi:[10.1186/s12970-017-0174-y](https://doi.org/10.1186/s12970-017-0174-y)

**Female athletes and cardiac**
- McNulty KL, et al. The effects of menstrual cycle phase on exercise
  performance in eumenorrheic women: a systematic review and meta-analysis.
  *Sports Med* 2020;50(10):1813-1827.
  doi:[10.1007/s40279-020-01319-3](https://doi.org/10.1007/s40279-020-01319-3)
- Schlie J, Krassowski V, Schmidt A. Effects of menstrual cycle phases on
  athletic performance and related physiological outcomes: a systematic review
  of studies using high methodological standards. *J Appl Physiol*
  2025;139(3):650-667. doi:[10.1152/japplphysiol.00223.2025](https://doi.org/10.1152/japplphysiol.00223.2025)
- Pelliccia A, Sharma S, et al. 2020 ESC Guidelines on sports cardiology and
  exercise in patients with cardiovascular disease. *Eur Heart J*
  2021;42(1):17-96. doi:[10.1093/eurheartj/ehaa605](https://doi.org/10.1093/eurheartj/ehaa605)

**Individual response**
- Hecksteden A, et al. Individual response to exercise training: a statistical
  perspective. *J Appl Physiol* 2015;118(12):1450-1459.
  doi:[10.1152/japplphysiol.00714.2014](https://doi.org/10.1152/japplphysiol.00714.2014)
- Hecksteden A, Pitsch W, Rosenberger F, Meyer T. Repeated testing for the
  assessment of individual response to exercise training. *J Appl Physiol*
  2018;124(6):1567-1579. doi:[10.1152/japplphysiol.00896.2017](https://doi.org/10.1152/japplphysiol.00896.2017)
- Swinton PA, et al. A statistical framework to interpret individual response
  to intervention: paving the way for personalized nutrition and exercise
  prescription. *Front Nutr* 2018;5:41.
  doi:[10.3389/fnut.2018.00041](https://doi.org/10.3389/fnut.2018.00041)

**LLMs and citations**
- Düking P, Sperlich B, Voigt L, Van Hooren B, Zanini M, Zinner C. ChatGPT
  generated training plans for runners are not rated optimal by coaching
  experts, but increase in quality with additional input information.
  *J Sports Sci Med* 2024;23(1):56-72.
  doi:[10.52082/jssm.2024.56](https://doi.org/10.52082/jssm.2024.56)
- Walters WH, Wilder EI. Fabrication and errors in the bibliographic citations
  generated by ChatGPT. *Sci Rep* 2023;13:14045.
  doi:[10.1038/s41598-023-41032-5](https://doi.org/10.1038/s41598-023-41032-5)

**APIs and tooling** (checked 2026-09-25)
- NCBI E-utilities API keys and rate limits: <https://support.nlm.nih.gov/kbArticle/?pn=KA-05317>
- Europe PMC REST API: <https://europepmc.org/RestfulWebService>
- Crossref, Retraction Watch in the REST API (29 Jan 2025):
  <https://www.crossref.org/blog/retraction-watch-retractions-now-in-the-crossref-api/>
- OpenAlex pricing: <https://help.openalex.org/access/pricing/>
- Semantic Scholar API: <https://www.semanticscholar.org/product/api>
- GitHub Actions: schedule and `GITHUB_TOKEN` behavior
  <https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows>;
  secrets <https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions>;
  billing <https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions>
- Claude Code GitHub Action: <https://github.com/anthropics/claude-code-action>
