# Idea: science-based coaching that stays current (brainstorm)

Brainstorm only. Nothing here is scheduled. It records how the coach could
give advice that is grounded in sport science, says how sure it is, and keeps
up with new research. Research date: 2026-09-25. Every reference in the last
section was checked against Crossref, PubMed or Europe PMC on that date; claims
marked *(unverified)* were not.

## Where things stand

- **All coaching guidance lives in two prompt strings:**
  `tools/start_consultation.py` and `tools/discuss_goals.py`. They cover
  *process* (which tools to call, how many notes to read, one question at a
  time, tone). They say **nothing about training science**: no intensity
  distribution, load progression, taper, fueling, recovery or safety. What the
  coach knows about training comes entirely from the model's pretraining, with
  no citations, no confidence levels and no date.
- **Tool descriptions contain simplified physiology:**
  - `get_hrv_data`: "higher values indicate better recovery". HRV should be
    read against the athlete's own rolling baseline and normal range. Single
    nights are noisy, and a rise is not always good news.
  - `get_resting_heart_rate`: "lower values generally indicate better
    fitness, elevated values may indicate overtraining or illness". This is
    roughly right, but it has no baseline or threshold.
- **Bug found along the way:** `discuss_goals` tells the model to call
  `get_last_week_activities`, but that tool doesn't exist (it should be
  `get_activities`).
- **No computed load metrics:** `get_activities` returns activities, but
  nothing works out weekly volume, ramp, time in zone over a block, or the
  "longest run in the last 30 days", which the checks below would need.
  intervals.icu has fitness/fatigue fields (CTL/ATL/ramp rate), but the repo
  doesn't read them yet *(field names unverified)*.
- **Evidence that this matters:** coaching experts rated ChatGPT's running
  plans below optimal. The plans got better when the model had more athlete
  information, but no plan was rated optimal (Düking et al. 2024). LLMs also
  make up references: in one study 18% of GPT-4's citations were fabricated
  (Walters & Wilder 2023). So "cite your evidence" only works if the citations
  come from a verified source, not from the model's memory.

## Design principles

1. **The server supplies the evidence and the model reasons with it.** The
   coach may only cite from a curated, versioned evidence base or from records
   a tool just fetched. It must never cite from memory.
2. **Confidence is part of the advice.** Every principle says whether it is
   consensus, moderate, emerging or contested, and the coach says so aloud when
   it matters.
3. **Individual data beats population averages, but only with a method.** Use
   the athlete's own baselines and small, explicit experiments, not reactions
   to single data points.
4. **Safety comes before performance.** Red flags lead to a referral to a
   professional, not to coaching around the problem.
5. **Public repo, generic content.** The evidence base, checks and prompts are
   general-purpose. Personal data stays in the per-user training repo and never
   goes in here.

## Idea list

Effort: S = hours, M = a few days, L = a week or more. Value: how much it
improves the quality or safety of the advice.

### A. Guidance in the tool itself

| # | Idea | Effort | Value |
|---|------|--------|-------|
| A1 | **Coaching-principles block in `start_consultation`**: a short list of principles (below), each tagged with a confidence level and pointing to an evidence card. Kept short to save context, with details loaded on demand (A2). | S | High |
| A2 | **`get_coaching_evidence(topic)` tool** returning one evidence card (principle, practical guidance, confidence, caveats, citations with DOI, last-reviewed date). A topic index is added to the `start_consultation` output. | M | High |
| A3 | **Fix physiology in tool descriptions** (HRV/RHR are read against a baseline; single values are noisy) and fix the `get_last_week_activities` bug. | S | Medium |
| A4 | **"Plan review" checklist prompt** that the coach runs before proposing a block: intensity distribution, progression, recovery weeks, strength, fueling for long sessions, taper, and alignment with goals and constraints. | S | Medium-High |
| A5 | **Population-specific notes** (female athletes/menstrual cycle, masters athletes, youth, returning from injury or illness) as separate cards, so they are loaded only when relevant. | M | Medium |

**Draft principles for A1/A2** (this is the evidence as I read it in
September 2026, not final copy):

| Topic | Practical guidance | Confidence | Key evidence |
|---|---|---|---|
| Intensity distribution | Most volume should be low intensity. Polarized and pyramidal models both work. Elite distance runners mostly train pyramidally. Polarized showed a small VO2peak advantage but no clear time-trial advantage. A 2026 network meta-analysis found no model clearly better than polarized; rankings favored threshold for VO2max and HIT for time trials. Choose the model to suit the athlete and the sport, not ideology. | Moderate (main pattern), low (which model is "best") | Oliveira 2024; Casado 2022; Li 2026 |
| Load progression | Increase load gradually. For runners, avoid single runs much longer than the longest run in the last 30 days: overuse-injury rate rose once a run exceeded it by more than 10%. The link was weaker for weekly ratios. The "10% weekly rule" has weak support. This is observational and shows association, not causation. | Moderate (observational, large cohort) | Frandsen 2025 |
| ACWR | Don't present the 0.8-1.3 "sweet spot" as settled. The metric has statistical flaws, and evidence for using it to prevent injury is weak or conflicting. A 2025 meta-analysis rests on single-arm cohorts and urges caution. | Contested | Impellizzeri 2020; Qin 2025; Frandsen 2025 |
| Taper | Reduce volume and keep intensity in the final 1-3 weeks. Tapering improves time-trial performance, and more so after a planned overload. The classic figures (about 2 weeks, 41-60% volume cut, intensity kept) come from an older meta-analysis. | Moderate-high | Wang 2023; Bosquet 2007 |
| HRV-guided training | Using a baseline-relative HRV trend to adjust daily intensity is reasonable and low-risk. It beats a fixed plan on submaximal/threshold outcomes, but not clearly on VO2max or performance. It depends on consistent measurement (same time, same position, rolling averages). | Moderate (small trials) | Düking 2021; Manresa-Rocamora 2021; Schaffarczyk 2026 |
| Strength training | Heavy (>80% 1RM) and plyometric training improve running economy and performance in runners. Submaximal and isometric training did not improve economy. Evidence for cyclists and triathletes was not checked here. | Moderate-high (runners) | Llanos-Lagos 2024a, 2024b |
| Fueling during exercise | Up to 90 g/h carbohydrate from glucose+fructose for sessions over 2.5-3 h (guideline). Up to 120 g/h may help trained athletes. Doses above 120 g/h are not supported by research. Train the gut before racing at high intakes. | High (≤90 g/h), emerging (90-120 g/h) | Thomas 2016; Morton 2026 |
| Energy availability / REDs | Low energy availability harms health and performance. Watch for warning signs: menstrual changes, recurrent bone stress injuries, frequent illness, persistent fatigue, falling performance despite training. Refer for screening with the IOC REDs CAT2 tool. | Consensus | Mountjoy 2023 |
| Sleep | Short habitual sleep (<7 h) and poor sleep quality are common in athletes. Sleep needs vary by person, so treat sleep as part of load management, not an afterthought. | Consensus (expert) | Walsh 2021 |
| Overreaching/overtraining | Unexplained performance decline plus mood or sleep disturbance calls for reduced load and ruling out medical causes. There is no single diagnostic marker. | Consensus (older, 2013) | Meeusen 2013 |
| Menstrual cycle | Average performance effects across phases are trivial, and the evidence quality is mostly low. Personalize based on the athlete's own experience instead of prescribing by phase. | Low-moderate | McNulty 2020 |
| Cardiac red flags | Chest pain, fainting or near-fainting during exercise, palpitations, or disproportionate breathlessness mean: stop and see a physician. | Consensus | Pelliccia 2021 (ESC) |
| Weight/body composition | Change weight slowly, in low-priority phases, and never at the expense of fueling training. No crash diets or aggressive deficits, and screen for REDs. Commonly cited rate limits (~0.5-1% body mass per week) are *(unverified here)*. | Consensus (direction), unverified (numbers) | Mountjoy 2023 |

### B. Staying current

| # | Idea | Effort | Value |
|---|------|--------|-------|
| B1 | **Curated evidence base in the repo** (design below): one card per topic with citations, confidence and `last_reviewed`, plus CI validation. This is the foundation for everything else. | M | High |
| B2 | **Scheduled literature watch** that opens a PR: a monthly job runs saved PubMed/Europe PMC searches for new systematic reviews, meta-analyses and position stands per topic, and an LLM drafts card updates with quoted abstract sentences. A human reviews and merges. | M-L | High |
| B3 | **`search_literature` tool used during a consultation** (Europe PMC or PubMed), for questions the evidence base doesn't cover. It returns real records only (title, year, journal, DOI, abstract snippet, publication type), and the model must label them as "not yet reviewed". | M | Medium |
| B4 | **Retraction and correction check** on every DOI in the evidence base, using the Crossref REST API `update-to` data, which now includes the Retraction Watch database. Run it in CI or on a schedule. | S | Medium |
| B5 | **Staleness warnings**: cards whose `last_reviewed` date is older than 18 months are flagged in CI, and the tool output says "may be out of date". | S | Medium |
| B6 | **Point users to existing literature MCP servers** (several open-source PubMed/Europe PMC servers exist, see below) or to Claude's built-in web search, instead of building B3 ourselves. | S | Low-Medium |

#### Literature APIs (checked 2026-09-25)

| API | Free? | Limits / notes | Fit |
|---|---|---|---|
| **PubMed E-utilities** (`eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`, `esummary`, `efetch`) | Yes | 3 requests/s without a key, 10/s with a free NCBI key. Supports publication-type filters (`meta-analysis[pt]`, `systematic review[pt]`, `practice guideline[pt]`) and date filters. Returned JSON in testing. | Best for the scheduled watch (B2): precise filters, authoritative metadata. |
| **Europe PMC REST** (`www.ebi.ac.uk/europepmc/webservices/rest/search`) | Yes, no key | Returned JSON with DOI, PMID and full abstracts (`resultType=core`) in testing. Supports `PUB_TYPE:"Meta-Analysis"` and includes preprints. | Best for the consultation-time tool (B3): one call gives the abstract, no key needed. |
| **Semantic Scholar Graph API** (`api.semanticscholar.org/graph/v1/paper/search`) | Yes, key on request | The unauthenticated pool is shared by all users. **Every test call returned HTTP 429.** Keyed access starts at 1 request/s. Has TLDRs and citation graphs. | Unreliable without a key. Good for "what cites this review" later. |
| **OpenAlex** (`api.openalex.org/works`) | Partly | Now uses usage-based pricing: docs say $1/day free, and unauthenticated responses showed a $0.10/day budget with search costing $0.001 per call. Data is CC0. | Fine at low volume. Metadata is broad but weaker on publication types. |
| **Crossref REST** (`api.crossref.org/works`) | Yes | Used here to verify every DOI. Carries retraction and correction notices (Retraction Watch data, in the REST API since Jan 2025). | DOI validation and retraction check (B4). |

**Trade-offs of searching at consultation time (B3):**
- *Latency:* 1-3 s per call, plus the model reading the results. That is fine
  when a question needs it and wasteful on every turn.
- *Reliability:* APIs throttle (as Semantic Scholar did). The coach must still
  work if search fails.
- *Relevance:* keyword search is noisy. In testing, a PubMed query for a
  specific 2026 fueling review returned a hydrogel chemistry paper as the
  first ID. Always filter by publication type and topic terms, and show the
  results to the model as candidates, not as answers.
- *Hallucination:* much lower than citing from memory if the model may only
  cite DOIs the tool returned. But the model can still over-read an abstract.
  Keep quoted snippets short, and label results as unreviewed and weaker than
  the curated base.
- *Cost:* free APIs, so the main cost is context tokens. Cap results at 5 and
  trim abstracts.

### C. Structured, checkable advice

| # | Idea | Effort | Value |
|---|------|--------|-------|
| C1 | **Advice format**: each substantive recommendation states *what*, *why*, *confidence* (consensus/moderate/emerging/contested) and *source* (card id or DOI). "Emerging" and "contested" findings are presented as options, never as rules. This goes in the `start_consultation` style section. | S | High |
| C2 | **`check_training_load` tool** (deterministic, no LLM): from recent activities it computes weekly volume and change, the longest session vs. the longest in the prior 30 days, time in zone over 4 weeks (low/moderate/high share), days since the last rest day, and consecutive hard days. It returns neutral flags plus the evidence card behind each flag. | M | High |
| C3 | **Recovery signal check**: HRV 7-day average vs. the athlete's 60-day baseline and normal range, RHR elevated vs. baseline for several days, and a short-sleep streak. Output is "worth asking about", not a diagnosis. Thresholds are tunable and documented as heuristics. | M | High |
| C4 | **Safety guardrails section** in the prompt, plus a `safety` card: cardiac symptoms, REDs signs, suspected bone stress injury (localized bone pain that gets worse with loading), illness with fever ("neck check"-style rules are *(unverified)* and would need a source), eating-disorder cues, pregnancy, and new medications. The behavior is to pause the coaching topic, recommend a professional, and record the flag in the notes. | S | High |
| C5 | **Weight-guidance rules**: no calorie targets below estimated needs during training blocks, no rapid-loss protocols, no body-composition goals for adolescents, and always pair weight talk with REDs screening questions. | S | High |
| C6 | **Plan sanity check before saving**: when the coach proposes a block, it runs C2's rules on the *planned* weeks too (ramp, long-run jump, hard-day spacing) and says where it goes against the evidence base. | M | Medium |

### D. Personalization with the scientific method

| # | Idea | Effort | Value |
|---|------|--------|-------|
| D1 | **Experiment notes**: a small template in consultation notes with hypothesis, intervention, primary metric, measurement protocol, duration, decision rule, and result. The coach proposes one experiment at a time (for example "2x/week heavy strength for 8 weeks; metric: HR at fixed pace on a flat route"). | S | Medium-High |
| D2 | **Baseline and noise awareness**: before calling a change real, compare it with the athlete's own day-to-day variation. This follows the logic of Hecksteden 2015/2018 and Swinton 2018: one before/after test can't separate real response from noise, so repeat measurements. Tools report baseline mean and SD, not just the latest value. | M | Medium-High |
| D3 | **Standard field tests** (repeatable time trial, fixed-pace/fixed-power HR test, decoupling on long easy runs) scheduled every 4-8 weeks so blocks can be compared. | S-M | Medium |
| D4 | **Block review tool**: compares two date ranges (volume, intensity distribution, field-test results, HRV/RHR trend) so the coach can check whether a block did what it was meant to. | M | Medium |
| D5 | **Response profile in the user's training repo**: over time, record what worked for this athlete (for example "responds well to threshold volume; HRV suppressed >3 days after long runs >2.5 h"). It lives in the private per-user repo, never in this one. | S | Medium |

### E. Other

| # | Idea | Effort | Value |
|---|------|--------|-------|
| E1 | **Evaluation set**: 15-25 generic athlete scenarios (synthetic, no real data) with expected behaviors ("flags the 40% long-run jump", "refers the chest-pain case", "doesn't promise 120 g/h is proven"). Run them when prompts or cards change, as an LLM-judged regression test. This is the only way to know if A/C actually changed behavior. | M | High |
| E2 | **"How sure are you?" follow-up**: when asked, the coach lists the cards and DOIs behind the last recommendation. | S | Low-Medium |
| E3 | **Glossary card** (zones, thresholds, TSS/CTL) so the coach explains terms consistently when the athlete asks. | S | Low |

## Evidence base: design

**Location:** `src/train_with_gpt/evidence/` (package data, so the server can
serve it and wheels include it), one Markdown file per topic with YAML front
matter:

```yaml
id: taper
title: Tapering before key events
confidence: moderate-high      # consensus | moderate-high | moderate | emerging | contested
last_reviewed: 2026-09-25
reviewed_by: <github handle>
applies_to: [running, cycling, triathlon, swimming]
summary: >
  Reduce volume, keep intensity, 1-3 weeks; larger effect after planned overload.
citations:
  - doi: 10.1371/journal.pone.0282838
    type: meta-analysis
    year: 2023
    finding: "Taper improved TT performance (SMD -0.45); overload + taper > conventional taper."
  - doi: 10.1249/mss.0b013e31806010e0
    type: meta-analysis
    year: 2007
    finding: "..."
superseded: []                 # DOIs previously cited and now replaced, with a reason
```

The body holds the practical guidance, caveats, and "what would change this
card".

**Confidence scale** (a simplified GRADE-style ladder, so the model and
reviewers use the same words):
- **Consensus**: position stand or consensus statement plus consistent
  meta-analyses.
- **Moderate-high / moderate**: at least one good meta-analysis with
  consistent direction, but small or heterogeneous trials.
- **Emerging**: single RCTs, cohorts, mechanistic work, or widespread
  practice that research hasn't caught up with yet.
- **Contested**: good sources disagree, or the metric/method has known
  flaws.

**CI checks** (in `tests/unit`, offline by default):
- The schema is valid, and the `confidence` value is in the allowed set.
- Every citation has a DOI or PMID.
- `last_reviewed` is older than 18 months → warning; older than 36 months →
  failure.
- An optional network job (scheduled workflow, not on every PR) checks that
  each DOI resolves on Crossref and has no retraction or correction notice.

**Serving:** `start_consultation` includes an index (id, one-line summary,
confidence) of about 20 lines. `get_coaching_evidence(topic)` returns the full
card. Cards stay small (about 300-600 words) so loading two or three per
consultation is cheap.

## Update process (B2)

1. **Trigger:** a monthly GitHub Actions cron job (or a scheduled Claude Code
   routine).
2. **Harvest:** for each card, a saved PubMed query (topic terms plus
   `meta-analysis[pt] OR systematic review[pt] OR practice guideline[pt] OR
   consensus development conference[pt]`), limited to publications since the
   last run. Optionally restrict to or boost a journal list: Sports Med, BJSM,
   IJSPP, MSSE, J Appl Physiol, Scand J Med Sci Sports, Eur J Sport Sci, JISSN,
   and J Strength Cond Res. Position stands are tracked from ACSM, IOC, ISSN,
   ECSS and ESC. Drop DOIs already cited.
3. **Triage:** an LLM reads the abstracts (fetched from Europe PMC) and sorts
   each into *not relevant*, *confirms the card*, *nuances the card* or
   *contradicts or supersedes the card*. It may only reference DOIs from this
   run's harvest, and it must quote the abstract sentence behind each claim.
4. **Draft:** it edits the affected cards: adds citations, adjusts wording and
   confidence, and moves replaced citations to `superseded` with a reason.
   Unrelated cards are left alone.
5. **PR:** it opens a PR labeled `evidence-review` with a digest table
   (paper, design, n, finding, proposed change, quoted evidence). CI re-checks
   every DOI on Crossref.
6. **Human review:** a maintainer reads the abstracts (and the full text for
   anything that changes confidence), edits, and merges. **Nothing reaches the
   coach without a merge.**
7. **Appraisal rules for reviewers:** a newer meta-analysis does not
   automatically win. For example, the 2025 ACWR meta-analysis pools
   single-arm cohorts and is weaker than its title suggests. Prefer
   pre-registered reviews, RCT-based pooling, trained or athlete populations,
   and performance outcomes over surrogates.

**Costs and secrets:** PubMed and Europe PMC are free. The LLM triage for
roughly 20 topics a month is small. The job needs an LLM API key and optionally
an NCBI key, both as repository secrets. All content is generic literature, so
it's safe for a public repo.

## Recommended first step

**One small PR: A3 + A1 + C1 + C4**, with no new infrastructure:
- Fix the `get_last_week_activities` bug and the HRV/RHR descriptions.
- Add a "Training science principles" section to `start_consultation` with
  about 10 principles from the table above. Each gets a confidence tag and
  one or two verified DOIs, plus a "reviewed 2026-09" line.
- Add the advice format (what / why / confidence / source) and the
  "never cite from memory" rule.
- Add the safety and weight guardrails with referral behavior.

This changes the coach's behavior right away, costs a few hundred prompt
tokens, and turns straight into cards when B1 lands.

## Roadmap

1. **Now (S):** the first step above.
2. **Next (M):** B1 evidence cards + A2 `get_coaching_evidence` + B5
   staleness CI. Move the principles out of the prompt into cards.
3. **Then (M):** C2 `check_training_load` + C3 recovery signal check
   (deterministic, unit-tested), linked to cards. E1 evaluation set, so
   changes can be measured.
4. **Later (M-L):** B2 monthly literature-watch PR + B4 retraction check.
   D1-D4 experiment and block-review support.
5. **Optional:** B3 consultation-time `search_literature` (Europe PMC first),
   or just document B6.

## Open questions

- Which sports matter beyond running? The strongest verified evidence here is
  for runners (injury spikes, strength). Cycling, triathlon and swimming would
  need their own searches.
- Who reviews evidence PRs? A single maintainer is fine, but maybe cards that
  change confidence should get a second opinion.
- Is the scheduled job a GitHub Action with an LLM API key (costs money,
  visible in a public repo's Actions log) or a local/scheduled Claude Code
  routine?
- Should the load checks read intervals.icu's own fitness/fatigue fields or
  compute from activities (which also works for Strava-only hosted users)?
- How strict should guardrails be for weight-related requests: refuse
  targets, or allow conservative guidance with screening questions?

## References

All DOIs resolved on Crossref on 2026-09-25. Findings are summarized from
abstracts, not full texts.

**Training and load**
- Oliveira PS, Boppre G, Fonseca H. Comparison of polarized versus other types
  of endurance training intensity distribution on athletes' endurance
  performance: a systematic review with meta-analysis. *Sports Med* 2024.
  doi:[10.1007/s40279-024-02034-z](https://doi.org/10.1007/s40279-024-02034-z)
- Casado A, et al. Training periodization, methods, intensity distribution, and
  volume in highly trained and elite distance runners: a systematic review.
  *IJSPP* 2022;17(6):820. doi:[10.1123/ijspp.2021-0435](https://doi.org/10.1123/ijspp.2021-0435)
- Li H, Yang Q, Wang B. Effects of different training-intensity distribution
  models on VO2max and time-trial performance in endurance athletes: a Bayesian
  network meta-analysis. *J Strength Cond Res* 2026;40(7):e755-e764.
  doi:[10.1519/JSC.0000000000005415](https://doi.org/10.1519/JSC.0000000000005415)
- Frandsen JSB, et al. How much running is too much? Identifying high-risk
  running sessions in a 5200-person cohort study. *Br J Sports Med* 2025.
  doi:[10.1136/bjsports-2024-109380](https://doi.org/10.1136/bjsports-2024-109380)
- Impellizzeri FM, Tenan MS, Kempton T, Novak A, Coutts AJ. Acute:chronic
  workload ratio: conceptual issues and fundamental pitfalls. *IJSPP*
  2020;15(6):907-913. doi:[10.1123/ijspp.2019-0864](https://doi.org/10.1123/ijspp.2019-0864)
- Qin W, Li R, Chen L. Acute to chronic workload ratio (ACWR) for predicting
  sports injury risk: a systematic review and meta-analysis. *BMC Sports Sci Med
  Rehabil* 2025. doi:[10.1186/s13102-025-01332-x](https://doi.org/10.1186/s13102-025-01332-x)
- Wang Z, Wang Y, Gao W, Zhong Y. Effects of tapering on performance in
  endurance athletes: a systematic review and meta-analysis. *PLoS One*
  2023;18(5):e0282838. doi:[10.1371/journal.pone.0282838](https://doi.org/10.1371/journal.pone.0282838)
- Bosquet L, Montpetit J, Arvisais D, Mujika I. Effects of tapering on
  performance: a meta-analysis. *Med Sci Sports Exerc* 2007;39(8).
  doi:[10.1249/mss.0b013e31806010e0](https://doi.org/10.1249/mss.0b013e31806010e0)
  (pre-2020, still the source of the classic taper figures)
- Meeusen R, et al. Prevention, diagnosis and treatment of the overtraining
  syndrome: joint consensus statement of the ECSS and ACSM. *Eur J Sport Sci*
  2013 (online 2012). doi:[10.1080/17461391.2012.730061](https://doi.org/10.1080/17461391.2012.730061)
  (pre-2020; no newer joint consensus found)

**Recovery and HRV**
- Düking P, et al. Monitoring and adapting endurance training on the basis of
  heart rate variability monitored by wearable technologies: a systematic
  review with meta-analysis. *J Sci Med Sport* 2021.
  doi:[10.1016/j.jsams.2021.04.012](https://doi.org/10.1016/j.jsams.2021.04.012)
- Manresa-Rocamora A, et al. Heart rate variability-guided training for
  enhancing cardiac-vagal modulation, aerobic fitness, and endurance
  performance: a methodological systematic review with meta-analysis.
  *IJERPH* 2021;18(19):10299. doi:[10.3390/ijerph181910299](https://doi.org/10.3390/ijerph181910299)
- Schaffarczyk M, et al. Heart rate variability-guided endurance training:
  evaluating strengths, weaknesses, opportunities, and threats for load
  prescription and adjustment. *Front Sports Act Living* 2026.
  doi:[10.3389/fspor.2026.1858271](https://doi.org/10.3389/fspor.2026.1858271)
- Walsh NP, Halson SL, Sargent C, et al. Sleep and the athlete: narrative review
  and 2021 expert consensus recommendations. *Br J Sports Med* 2021;55:356-368.
  doi:[10.1136/bjsports-2020-102025](https://doi.org/10.1136/bjsports-2020-102025)

**Strength**
- Llanos-Lagos C, et al. Effect of strength training programs in middle- and
  long-distance runners' economy at different running speeds: a systematic
  review with meta-analysis. *Sports Med* 2024.
  doi:[10.1007/s40279-023-01978-y](https://doi.org/10.1007/s40279-023-01978-y)
- Llanos-Lagos C, et al. The effect of strength training methods on middle-
  and long-distance runners' athletic performance: a systematic review with
  meta-analysis. *Sports Med* 2024.
  doi:[10.1007/s40279-024-02018-z](https://doi.org/10.1007/s40279-024-02018-z)

**Nutrition and health**
- Thomas DT, Erdman KA, Burke LM. Position of the Academy of Nutrition and
  Dietetics, Dietitians of Canada, and the American College of Sports
  Medicine: nutrition and athletic performance. *J Acad Nutr Diet* 2016.
  doi:[10.1016/j.jand.2015.12.006](https://doi.org/10.1016/j.jand.2015.12.006)
  (pre-2020, still the current joint guideline)
- Morton JP, Fell JM, Gonzalez JT, Hearris MA, Podlogar T, Pugh JN, Wallis GA.
  From metabolism to medals: contemporary perspectives and revisiting
  carbohydrate guidelines for fueling endurance athletes during exercise.
  *J Nutr* 2026. doi:[10.1016/j.tjnut.2026.101442](https://doi.org/10.1016/j.tjnut.2026.101442)
- Mountjoy M, Ackerman KE, Bailey DM, et al. 2023 International Olympic
  Committee's (IOC) consensus statement on Relative Energy Deficiency in Sport
  (REDs). *Br J Sports Med* 2023;57:1073-1097.
  doi:[10.1136/bjsports-2023-106994](https://doi.org/10.1136/bjsports-2023-106994)
- McNulty KL, et al. The effects of menstrual cycle phase on exercise
  performance in eumenorrheic women: a systematic review and meta-analysis.
  *Sports Med* 2020;50(10):1813-1827.
  doi:[10.1007/s40279-020-01319-3](https://doi.org/10.1007/s40279-020-01319-3)
- Pelliccia A, Sharma S, et al. 2020 ESC Guidelines on sports cardiology and
  exercise in patients with cardiovascular disease. *Eur Heart J*
  2021;42(1):17-96. doi:[10.1093/eurheartj/ehaa605](https://doi.org/10.1093/eurheartj/ehaa605)

**Individual response**
- Hecksteden A, et al. Individual response to exercise training: a statistical
  perspective. *J Appl Physiol* 2015;118:1450-1459.
  doi:[10.1152/japplphysiol.00714.2014](https://doi.org/10.1152/japplphysiol.00714.2014)
- Hecksteden A, Pitsch W, Rosenberger F, Meyer T. Repeated testing for the
  assessment of individual response to exercise training. *J Appl Physiol*
  2018;124(6):1567-1579. doi:[10.1152/japplphysiol.00896.2017](https://doi.org/10.1152/japplphysiol.00896.2017)
- Swinton PA, et al. A statistical framework to interpret individual response
  to intervention: paving the way for personalized nutrition and exercise
  prescription. *Front Nutr* 2018.
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

**APIs and tooling**
- NCBI E-utilities rate limits and API keys:
  <https://support.nlm.nih.gov/kbArticle/?pn=KA-05317>
- Europe PMC REST API: <https://europepmc.org/RestfulWebService>
- Semantic Scholar API: <https://www.semanticscholar.org/product/api>
- OpenAlex pricing: <https://help.openalex.org/access/pricing/>
- Crossref, Retraction Watch data in the REST API:
  <https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/>
- Example open-source literature MCP servers (not reviewed for quality):
  <https://github.com/cyanheads/pubmed-mcp-server>,
  <https://github.com/BerkayCelk/pubmed-mcp>
