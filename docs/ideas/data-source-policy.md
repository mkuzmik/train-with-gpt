# Data-source policy options (analysis, for the owner's decision)

Companion to `more-training-data.md`. The Strava API Policy that took effect
on 2026-06-01 restricts using Strava data with AI applications and MCP
servers. This doc quotes the relevant text and compares the ways the server
could get training data. It ends with a recommendation and a list of the
owner's decisions.

**This is not legal advice.** It is an engineering reading of public terms,
done on 2026-09-26. Where the text is ambiguous, the doc says so and suggests
asking the provider. Strava explicitly invites such questions: "If you are
unsure if a certain use of the Strava API Materials is permitted ... please
contact us at developers@strava.com" (API Agreement §2.2).

## TL;DR

- Read literally, the **hosted server's current Strava path is not
  compliant.** It is an MCP server that puts Strava activities, laps, streams
  and zones into Claude's context. §5.16(b) and §5.3 of the Strava API Policy
  prohibit exactly that. There is no personal-use or small-app exception. The
  only carve-out (§3.5) is for Strava's own MCP.
- **The owner's idea works: use the official Strava MCP alongside ours.** The
  user connects both in Claude. Strava data flows Strava → Strava MCP →
  Claude, and this server never calls the Strava API. It is the only
  Strava-sanctioned way to get Strava data into an AI conversation (§3.5,
  §5.3's last sentence). It needs a paid Strava subscription per user, and a
  few caveats remain (see option 5).
- For this server's own data, **intervals.icu becomes the only source.** Its
  API terms allow "any lawful purpose, including commercial use" and say
  nothing about AI. The catch: intervals.icu withholds activities it got from
  Strava (they come back as empty stubs). Users need their device to sync to
  intervals.icu directly, or a one-off Strava archive import.
- Hosted login therefore has to **move off Strava OAuth.** Recommended:
  intervals.icu, with the personal API key now and intervals.icu OAuth once
  an app is approved. The existing `intervals_connections` table already maps
  users to intervals.icu athletes, so existing users keep their notes.
- Keeping Strava **for login only** is not clearly allowed (§5.3 also covers
  "Strava API Materials"). Standard-tier API access also needs the developer
  to hold a Strava subscription. Not recommended unless Strava confirms in
  writing.

## Key clauses (quoted)

Sources:
- [Strava API Policy (2026)](https://www.strava.com/legal/api_policy), effective June 1, 2026 ("Policy").
- [Strava API Agreement (2026)](https://www.strava.com/legal/api), effective June 1, 2026 ("Agreement"). The Policy "is incorporated by reference into, and forms part of" the Agreement.

**Scope.** Agreement §2.3(i): "'Strava Data' means all data you access or
collect from the Strava API Materials, including without limitation Strava
user personal and activity data". "Strava API Materials" covers "the Strava
application programming interface ... and any software, materials or data
that Strava makes available to you ... including the API Token". Neither
document defines "AI Application", "MCP Server" or "Persistent Index".

**Policy §5.3, "No AI/ML Training, Fine-Tuning, Grounding, Evaluation,
Embedding, or Retrieval-Augmented Generation":**
> You may not use the Strava API Materials or Strava Data, directly or
> indirectly, in connection with the development, training, evaluation, or
> operation of any AI Application. This prohibition extends to: Any data
> derived from, aggregated from, anonymized from, or generated using Strava
> Data, in any form (including original, derivative, aggregated, anonymized,
> de-identified, or model-output form); and Any of the following activities
> with respect to an AI Application: training, [...], retrieval-augmented
> generation, ingestion into a context window or working memory, and any
> other activity intended or reasonably likely to develop, improve, evaluate,
> or operate an AI Application.
> This prohibition does not extend to use of the Strava MCP, as discussed
> above in Section 3.5.

**Policy §5.16, "No Abstraction Layers, Pass-Through Proxies, or
Unauthorized Agent Interfaces":**
> You may not, and may not authorize any third party to: (a) operate, offer,
> or facilitate any abstraction layer, [...] pass-through proxy,
> intermediary, or aggregator that re-exposes the Strava API Materials, in
> whole or in part, to third parties; (b) operate any MCP Server,
> agent-mediated interface, or analogous mechanism that exposes the Strava
> API Materials, Strava Data, or any subset thereof; [...] (d) build a
> Developer Application whose primary purpose is to enable third parties to
> access the Strava API Materials or Strava Data through your credentials or
> infrastructure. The Strava MCP is the sole authorized first-party
> agent-mediated interface to the Strava Platform. [...]

Note that (a) and (d) are limited to "third parties", but **(b) is not**. An
MCP server that exposes only the operator's own Strava data is still covered.

**Policy §3.5, "Strava MCP":**
> [...] The Strava MCP is the sole authorized first-party agent-mediated
> interface and may be made available on AI platforms Strava trusts [...].
> Subscribers to Strava may access the Strava MCP in connection with their
> personal use of their own Strava data [...] and may bring their own AI
> Application to interact with their own data through the Strava MCP. The
> Strava MCP is not authorized for, and may not be used to enable, any
> commercial or third-party access to the Strava API Materials or Strava
> Data outside the developer's own personal use.

**Policy §5.4:** "You may not process or disclose Strava Data [...] for the
purposes of analytics, analyses, customer insight generation, or product or
service improvements. You may not combine Strava Data with other customer
data for these or any other purposes. The restrictions in this Section 5.4
apply to data derived from Strava Data and to output that incorporates or was
generated using Strava Data."

**Policy §5.5:** "You may not store Strava Data, or any data derived from
Strava Data, in any Persistent Index. The foregoing prohibits indefinite
storage in vector stores, embedding stores, search indexes, knowledge graphs,
retrieval-augmented data stores, archives, and any other storage configured
to enable subsequent retrieval, query, or use." The 7-day cache of §6.2 is
excepted.

**Retention and deletion.**
- §6.2: "You may not retain Strava Data in your cache for longer than seven (7) days."
- §6.3: deletions on Strava must be reflected "in all cases within forty-eight (48) hours."
- §7.4: on a user's request, revocation or account deletion, or on "your
  cessation of use of the Strava API Materials", delete "all Strava Data and
  all Personal Data derived from Strava Data" within 30 days, and "certify
  deletion to Strava in writing on request."

**Other obligations that apply to any Strava app, AI or not.**
- §2.1 and §7.2: a consent disclosure (data types, methods, withdrawal, deletion).
- §7.3: a GDPR-compliant privacy policy.
- §2.5: deletion on request, with written confirmation.
- §4.3: no implied affiliation.
- §4.4: Garmin attribution for Garmin-sourced data.

**Tiers and cost.**
- Policy §3.3: "Standard Tier Applications are subject to subscription
  requirements [...] including a requirement that the developer or specified
  end users maintain an active Strava subscription."
- Strava's [developer program update](https://communityhub.strava.com/insider-journal-9/an-update-to-our-developer-program-13428):
  "A Strava subscription will be required to access the API as a Standard
  Tier developer", from 2026-06-30 for existing developers.

**Strava MCP availability.** Per [Strava's help center](https://support.strava.com/hc/en-us/articles/46190267796237-Strava-MCP-Connector):
- "Only Strava subscribers have access to the MCP." Trials don't count.
- Launched "with Anthropic (Claude)"; endpoint `https://mcp.strava.com/mcp`.
- "The MCP is read-only."
- Rate-limited per minute and per day, with the numbers not published.

Its tool list, as a Claude connector shows it: `list_activities`,
`get_activity_performance`, `get_activity_streams`,
`get_strength_workout_details`, `get_athlete_profile`, `get_athlete_zones`,
`get_gear`, `get_training_plan`, `get_club_info`, `eligibility`, `health`.

**intervals.icu.** The [API Terms and Conditions](https://forum.intervals.icu/t/intervals-icu-api-terms-and-conditions/114087) (effective 2025-10-23):
- §1: "a non-exclusive, worldwide, royalty-free, perpetual license to access
  and use the API for any lawful purpose, including commercial use. Except
  for the Garmin attribution requirements in 1.1, you may integrate, modify,
  distribute, and sublicense outputs derived from the API without restriction
  or attribution."
- §1.1: "if your application displays information derived from
  Garmin-sourced data, you must display attribution to Garmin in the form and
  manner required by Garmin's brand guidelines."
- No AI clause.

intervals.icu and Strava-sourced activities:
- The OpenAPI spec says of activity endpoints: "An empty stub object is
  returned for Strava activities."
- The intervals.icu developer, answering an [MCP use case (Oct 2025)](https://forum.intervals.icu/t/solved-mcp-server-for-coaches-via-api-do-not-see-athletes-activities-brought-from-strava-ans-strava-api-forbids-data-fowarding/113828):
  "Intervals.icu cannot supply Strava activities via the API."
- Activities imported from the Strava *archive export* are different ([forum](https://forum.intervals.icu/t/import-all-data-from-strava/81068)):
  "This data is not subject to the Strava API restrictions". The import is a
  supporter (paid) feature, and the race flag is not in the archive.

**Garmin.**
- The [API brand guidelines](https://developer.garmin.com/brand-guidelines/api-brand-guidelines/)
  require a "Garmin [device model]" attribution wherever Garmin device data is
  shown, including derived data.
- The [Connect Developer Program](https://developer.garmin.com/gc-developer-program/program-faq/)
  "is only for business use", and new applications have been paused since
  spring 2026 ([report](https://the5krunner.com/2026/09/14/garmin-developer-api-access-paused/)).

## Options compared

Effort: S ≈ a day, M ≈ a few days, L ≈ a week or more.

| # | Option | Data it gives | Policy position | Approval / cost | Effort here | User friction |
|---|---|---|---|---|---|---|
| 1 | **Status quo:** hosted server reads Strava via our Strava app | Activities, laps, streams, zones, profile. No wellness. | **Conflicts** with §5.16(b) and §5.3 as written. No personal-use exception. Also needs §2.1/§7.3 consent and privacy policy, and §7.4 deauthorization handling. | Developer must hold a Strava subscription (Standard tier). Capacity 1 by default, 10 self-serve. | 0 | Low |
| 2 | **intervals.icu as the only data source** (API key now, OAuth later) | Activities *not* from Strava (Garmin, Wahoo, Coros, Polar, Suunto, Zwift, uploads, Strava archive import): full fields, streams, intervals, zones, load, curves. Wellness (HRV, RHR, sleep, weight, CTL/ATL). Settings, gear, calendar. Strava-synced activities are stubs. | Permissive terms, no AI clause. Garmin attribution required. intervals.icu decides itself what it may pass on (it withholds Strava data). | API key: none (gray area: full-access keys of other people). OAuth: [apply](https://forum.intervals.icu/t/intervals-icu-oauth-support/2759), manual approval, OAuth unusable until approved. | M (login) + S (switch hosted data client) | Medium: needs an intervals.icu account, and the device synced directly (not via Strava) |
| 3 | **Direct device platforms** | Garmin: activities + health. Polar AccessLink: activities, sleep, recharge. Wahoo: workouts/FIT. COROS, Suunto: activities. Oura/Whoop: wellness. | Garmin: business-only, onboarding paused, attribution. Polar: open registration, must "credit Polar", no AI clause found. Suunto, COROS, Wahoo: partner approval, Suunto "not for personal use". Oura: 10 users before review. Whoop: API terms, not checked for AI. | High and per vendor | L per vendor | Medium |
| 4 | **User-supplied files** (FIT/GPX/TCX, or the Strava archive) | Whatever the file holds: full streams, laps. No wellness. | No third-party API terms. The user's own export (Policy §6.6 preserves the user's export right). Garmin attribution may still apply to Garmin files. | None | M–L: an MCP tool can't easily receive a file (Claude would base64 it, size limits), so it needs an upload page + parsing (`fitparse`) + storage | High: manual export per activity |
| 5 | **Official Strava MCP alongside ours** (owner's suggestion) | Whatever Strava MCP exposes (activities, performance, streams, zones, gear, profile, Strava training plan) directly to Claude. This server holds none of it. | The sanctioned path (§3.5, §5.3 last sentence), for "personal use of their own Strava data". See the caveats below. | Each user needs a Strava subscription (no trials). Nothing for us. | S: guidance text + tool descriptions. Plus the login change (option 2 or 7). | Low–medium: connect a second connector, pay Strava |
| 6 | **Strava for login only** (no activity reads) | Identity only | **Unclear.** §5.3 bars using "Strava API Materials" (not only Data) "in connection with ... operation of any AI Application". The athlete id and name are Strava Data. §5.16(b) arguably not triggered (nothing is exposed). Only safe with Strava's written OK. | Still a Standard-tier app: developer subscription, athlete cap | S (remove data reads) | Low |
| 7 | **Generic login** (GitHub OAuth, email magic link) | Identity only | No data-provider terms | GitHub OAuth app: free, self-serve. Email: a mail provider. | M | Low (GitHub users) / medium |

### Option 1: status quo (what the server does today)

Remote mode:
- Strava OAuth login (`strava_oauth.py`), with `activity:read_all,profile:read_all`.
- Per-request `StravaClient` for `get_activities`, `analyze_activity` and
  `analyze_lap`: activity list, detail, laps, streams, zones. The results go
  straight into Claude's context.
- Stores tokens and the athlete's name in `store.db`. Keys notes and goals in
  the training repo by the **Strava athlete id**. Claude-written notes can
  contain numbers derived from Strava activities.

Against the text:
- "operate any MCP Server ... that exposes ... Strava Data" (§5.16(b)) and
  "ingestion into a context window" (§5.3) describe this server directly.
  Being a hobby project or having one user does not change the wording.
- Notes in a git repo that hold Strava-derived numbers look like "storage
  configured to enable subsequent retrieval" (§5.5), and fall under §7.4's
  delete-on-cessation rule. This is less clear-cut, and a question for
  Strava.
- Independent of AI, the app lacks the §2.1 consent text, a §7.3 privacy
  policy, deletion confirmation (§2.5) and deauthorization handling (§7.4:
  delete within 30 days of revocation; there is no webhook today).

Practical risk:
- Strava can revoke the API token (Agreement §2.2 and §4.2). That would break
  **login** for every hosted user, not only Strava data.
- Notes are keyed by Strava id, so users would lose their way back to their
  notes until another login exists.
- Enforcement practice is unknown; no public reports were found either way.

### Option 2: intervals.icu as the primary hosted source

What's good:
- The terms are the most permissive of any source reviewed.
- The data is the richest: wellness, load, curves and the calendar exist only
  here.
- Stdio already uses intervals.icu, and every new tool in
  `more-training-data.md` is intervals.icu-first.

The big limitation: **Strava-synced activities are stubs.** A user whose watch
syncs Garmin → Strava → intervals.icu gets nothing useful from this server.
Fixes on the user's side:
- (a) connect the device directly in intervals.icu settings (Garmin, Wahoo,
  Polar, Suunto, COROS and others). Keep Strava connected there only for
  names, if at all;
- (b) for history, use intervals.icu's "Import All Strava Data" with the
  Strava archive (supporter feature).

Onboarding (#11) has to explain this.

Login options:
- **API key as login** (idea 2 in `intervals-icu.md`): the login page asks
  for the key and calls `GET /athlete/0` for the athlete id. Works today.
  Downside: collecting full-access keys from other people. They must be told
  plainly what the key allows, as the current connect page already does.
- **intervals.icu OAuth**: scoped (`ACTIVITY:READ`, `WELLNESS:READ`) and
  revocable. It needs an app at `intervals.icu/oauth/apply` with a public
  website and privacy policy, and the flow can't be used until the app is
  approved. Once approved, "you can send anyone you like to the OAuth consent
  page". Listing in the public directory is optional.

Identity migration is cheap:
- `intervals_connections(user_id → athlete_id)` already links hosted users
  who added a key.
- An intervals.icu login looks up the athlete id there and resumes the
  existing `user_id`, so notes are kept.
- Users who never added a key need one Strava login while it still exists,
  to attach intervals.icu. After the cutover, the owner can map them by hand.

Attribution: Garmin-sourced activities (`device_name` starting "Garmin") need
"Garmin [device model]" next to the data in tool output. That's small, but
it's a real obligation passed down by intervals.icu's terms. Garmin has
reportedly been redesigning its developer terms, possibly including AI use.
Re-check if Garmin publishes anything that intervals.icu passes on.

### Option 3: direct device platforms

- Garmin, the most common source, is closed to new developers, and business
  use only.
- Most others need partner approval.
- intervals.icu already aggregates all of them (its athlete record has
  per-source wellness key lists for Garmin, Polar, Oura, Whoop and Google).

**Not recommended.** Revisit only if intervals.icu access becomes a problem.
Polar AccessLink is the easiest to start (self-serve registration).

### Option 4: user-supplied files

Clean policy-wise, and the only route for someone who uses neither
intervals.icu nor a Strava subscription. But it's clumsy:
- MCP clients can't hand a file to a remote server.
- It would need a web upload page, FIT parsing and per-user storage (with its
  own GDPR duties).
- Users would export files by hand.

intervals.icu already does all of this (upload, parse, store) for free, so
the recommendation is to point users there instead. Keep as a fallback idea.

### Option 5: official Strava MCP alongside ours

How it works:
- The user adds two connectors in Claude: Strava's (`mcp.strava.com/mcp`)
  and Train with GPT.
- Claude calls Strava's `list_activities`/`get_activity_performance` for
  Strava data, and this server's tools for notes, goals, the consultation
  flow and intervals.icu data.
- This server has no Strava app and never calls the Strava API, so the
  Strava API Agreement no longer binds it (except §7.4's deletion duties that
  survive cessation).

Why it's attractive:
- It's what §3.5 and §5.3 explicitly allow ("may bring their own AI
  Application to interact with their own data through the Strava MCP").
- It removes the Strava code, tokens, rate-limit budget and subscription
  requirement from this project.
- Strava's MCP already covers activities, streams, zones, gear and "training
  load", which is most of what our Strava path did.

Caveats (the owner should weigh these, and ideally ask Strava about the last):
1. **Paid Strava subscription per user**, Claude only for now, and rate
   limits we don't control. Users without one fall back to intervals.icu
   alone.
2. **No cross-source joins in our code.** We can't fetch Strava data to
   combine with intervals.icu wellness (and §5.4 would bar it anyway if we
   were a Strava developer). Claude can put both side by side in the
   conversation. That is the user's AI using the user's data, which §3.5
   contemplates.
3. **Strava-derived content can still reach our server through Claude.**
   Claude may write "10 km at 5:00/km" into `save_consultation_notes`, or
   pass Strava numbers as tool arguments. Legally this is user-provided
   content, not "data you access or collect from the Strava API Materials"
   (Agreement §2.3). But §3.5 says the Strava MCP may not be used "to enable
   ... third-party access ... outside the developer's own personal use". On
   the hosted server, other users' notes live in a repo the operator
   controls.

   Mitigations:
   - never design tools that *ingest* Strava MCP output (no
     "import this Strava activity" tool);
   - tell Claude in `start_consultation` to keep notes qualitative when the
     source is Strava;
   - longer-term, let each user point at their own notes repo.

   Worth a direct question to Strava.
4. **Tool overlap.** Strava's `get_athlete_profile`, `list_activities` and
   `get_athlete_zones` sit next to our `get_activities` and
   `get_athlete_settings`. Our descriptions must say "from intervals.icu" so
   the model picks the right source. `get_athlete_profile` is avoided already
   (see `more-training-data.md`).
5. The Strava MCP's own subscriber terms were not reviewed here (only the
   API Agreement/Policy and the help-center page). Check them.

What we must not do: proxy, wrap or call the Strava MCP from our server.
That would make us an "agent-mediated interface" again (§5.16), and §3.5 bars
"third-party access" through it.

### Option 6: Strava for login only

Tempting, because nothing changes for users. But:
- §5.3 names "Strava API Materials", and the OAuth token is part of them. An
  MCP server is plausibly an "AI Application" (the term is undefined).
- It keeps the Standard-tier costs: the developer's subscription, athlete
  capacity 1 by default, 10 self-serve, more after review.
- §7.4 duties stay.

Only worth it if Strava confirms in writing. Even then, option 2/7 logins
cost only M effort.

### Option 7: generic login

GitHub OAuth is quick and free, but odd for athletes. An email magic link
needs a mail provider and anti-abuse work. It is only needed for users who
use the Strava MCP and have no intervals.icu account. Defer until such users
exist.

## Recommendation

**Short term (next few weeks):**
1. **Owner:** email developers@strava.com. Describe the server (open-source,
   hobby, Standard tier) and ask:
   - (a) whether the current hosted Strava path may continue, and if not,
     what grace period applies;
   - (b) whether Strava OAuth *only for login* is permitted in an MCP/AI
     product;
   - (c) whether notes Claude wrote from Strava data (in a repo the operator
     controls) must be deleted under §7.4 when the app stops using the API;
   - (d) whether a user's Claude passing Strava MCP output into a
     third-party MCP server's notes tool is acceptable.
2. **Keep the freeze:** no new Strava processing, storage or caching (the
   hard rule already in force). Build every new data feature on intervals.icu.
3. **Add intervals.icu login** (API key first) next to Strava login, and
   resume existing users through `intervals_connections`. Apply for an
   intervals.icu OAuth app in parallel. It needs a public page and privacy
   policy; the README or a GitHub Pages page can serve.
4. **Switch hosted data tools to intervals.icu** (activities as well as
   wellness), and remove the Strava data reads from the hosted server. In
   `start_consultation`, say: "for Strava activities, use the Strava
   connector if the user has it".
5. **README:** document "Strava data → connect the official Strava MCP"
   and "devices → sync directly to intervals.icu".

**Longer term:**
- Retire Strava OAuth completely:
  - delete stored Strava tokens and names;
  - delete the Strava app on strava.com;
  - move internal user ids off Strava athlete ids (the "durable identity
    mapping" idea in `intervals-icu.md`), renaming `notes/<id>` and
    `goals/<id>.md` once.
- Replace API keys with intervals.icu OAuth when approved (scoped, read-only).
- Add a generic login (GitHub) only if Strava-MCP-only users appear.
- Don't integrate device APIs or file uploads unless intervals.icu stops
  being viable.

If Strava answers (1) favourably, steps 3–5 are still worth doing: they
remove the per-developer subscription, the 10-athlete cap and the token
revocation risk.

## Decisions for the owner

1. ⚠️ **Critical: what to do with the hosted Strava path now.**
   - (a) Turn off Strava data reads on the hosted server now and point users
     to the Strava MCP (the most conservative option).
   - (b) Keep them frozen as they are until Strava replies (the current
     state; this is a risk the owner would be accepting).
   - (c) Keep them and extend them (not recommended).
   - *Recommended:* (b) → (a). Ask Strava this week, and ship intervals.icu
     login and data before turning Strava reads off, so users aren't
     stranded.
2. ⚠️ **Critical: login provider for the hosted server.** Options:
   intervals.icu API key, intervals.icu OAuth (needs approval), GitHub, or
   keep Strava for login only (needs Strava's written OK).
   *Recommended:* intervals.icu API key now, OAuth when approved.
3. ⚠️ **Critical: existing notes containing Strava-derived numbers.** Leave
   them, scrub them, or delete them on cessation (§7.4). *Recommended:* ask
   Strava (question 1c) before touching them. Notes are irreversible to
   delete and valuable to users.
4. **Endorse the Strava MCP officially** in the README and onboarding
   (requires users to pay Strava)? *Recommended:* yes, as the optional
   Strava path.
5. **Apply for an intervals.icu OAuth app** (needs a public page and privacy
   policy)? *Recommended:* yes.
6. **Internal user ids:** keep Strava athlete ids as opaque internal ids for
   now, or migrate to random ids? *Recommended:* migrate when Strava OAuth is
   retired. It's an S–M one-off rename in the training repo.

## Open uncertainties

- Whether an MCP server or Claude connector counts as an "AI Application"
  (undefined in both documents). The §5.16(b) wording makes the point moot
  for data exposure, but it matters for the login-only question.
- Whether §5.5 and §7.4 reach free-text notes Claude wrote from Strava data.
- Strava's enforcement practice and any grace period for existing apps.
- The Strava MCP's subscriber terms and rate limits (not published in the
  pages reviewed).
- Whether intervals.icu's derived values (CTL/ATL, curves) include load from
  Strava-imported activities. That is intervals.icu's obligation, not ours,
  since we're not a party to its Strava agreement, but it's worth knowing.
- Whether Garmin's pending developer-terms redesign adds AI restrictions
  that intervals.icu must pass on.
- Details from secondary sources that were not verified first-hand: the
  COROS partner/MCP option, Suunto, Wahoo, Oura and Whoop terms, and the
  Garmin onboarding pause.
