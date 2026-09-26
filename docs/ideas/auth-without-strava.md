# Idea: move hosted login off Strava OAuth (Strava MCP as a companion)

Not implemented. A design proposal for the hosted (multi-user, OAuth) server.
The stdio / local path is unaffected: it has no login and keeps notes at the
root of the training repo.

The policy research behind it is in
[`strava-api-policy.md`](strava-api-policy.md) (moved here from PR #12). **It
is not legal advice.** It is an engineering reading of public terms, done on
2026-09-26.

## TL;DR

- **Why.** The Strava API Policy (effective 2026-06-01) bars operating "any
  MCP Server ... that exposes ... Strava Data" (§5.16(b)). It also bars using
  Strava API Materials or Strava Data "in connection with the ... operation of
  any AI Application" (§5.3). The hosted server does both today, and it uses
  Strava OAuth as its *only* login. If Strava revokes the app, every hosted
  user loses access to their notes, not only to Strava data.
- **Target.**
  - **Our own login** gives each user **our own internal id** (random, not a
    Strava id).
  - **intervals.icu is linked** as this server's only data source: API key
    now, OAuth once an intervals.icu app is approved.
  - **Strava's official MCP** is recommended as a separate connector the user
    adds in Claude. It is for Strava subscribers only, Claude only, and
    read-only. Our server never calls, proxies or ingests it.
- **Login recommendation:** an **email one-time code** (a 6-digit code, with
  a magic link as a convenience). It needs a domain and an email-sending
  provider, costs about $0 at this scale plus the domain, and puts no
  personal account of the owner at stake.
  - **Google sign-in** is a reasonable second login. The owner's worry: with
    basic scopes only, a Google OAuth client is unlikely to get anyone's
    account suspended. Google's documented consequence for a bad Cloud project
    is suspending the *project*, and even a Cloud-account suspension leaves
    "access to other Google services like Gmail". The risk is not zero,
    though, so if Google is used it should live in a **dedicated Google
    account and Cloud project** that the owner's personal account has no role
    in.
- **Migration:** existing users are keyed by Strava athlete id.
  - Each one gets a new random id the next time they sign in: they add the
    new login once, and their notes and goals are renamed in the same step.
  - Stragglers are matched through their intervals.icu connection or mapped
    by the operator.
  - Then Strava tokens and names are deleted, the Strava code is removed, and
    the Strava app is deleted.
- **First shippable step:** new identity tables, the email-code sign-in page
  for new users, and a "move your account" step for existing Strava users.
  There are no new Strava calls.

## 1. Why: the Strava API Policy

Sources:
- [Strava API Policy](https://www.strava.com/legal/api_policy)
- [Strava API Agreement](https://www.strava.com/legal/api)

Both are effective 2026-06-01. Full quotes are in
[`strava-api-policy.md`](strava-api-policy.md#key-clauses-quoted).

| Clause | What it says (quoted, abridged) | Effect on this server |
|---|---|---|
| §5.16(b) | You may not "operate any MCP Server, agent-mediated interface, or analogous mechanism that exposes the Strava API Materials, Strava Data, or any subset thereof". (a) and (d) are limited to "third parties", **(b) is not**. | The hosted Strava reads (`get_activities`, `analyze_activity`, `analyze_lap`) are exactly this. There is no personal-use or small-app exception. |
| §5.3 | No use of "the Strava API Materials or Strava Data, directly or indirectly, in connection with the development, training, evaluation, or operation of any AI Application", including "ingestion into a context window". It covers derived data "in any form". "This prohibition does not extend to use of the Strava MCP". | The data reads are covered. A **login-only** Strava app is arguably covered too, because it names "Strava API Materials" (the OAuth token is one), not only data. |
| §3.5 | "The Strava MCP is the sole authorized first-party agent-mediated interface". Subscribers "may bring their own AI Application to interact with their own data through the Strava MCP". It "may not be used to enable ... commercial or third-party access". | The only sanctioned route for Strava data into Claude, and it is the user's, not ours. |
| §5.4 | No analytics on Strava Data, and "You may not combine Strava Data with other customer data". | We can't join Strava and intervals.icu data in our code. |
| §5.5 | No Strava Data "or any data derived from Strava Data, in any Persistent Index", including "archives, and any other storage configured to enable subsequent retrieval". | Notes Claude wrote from Strava numbers *may* fall under this (unclear). |
| §6.2, §6.3 | Cache for at most 7 days. Deletions on Strava must be reflected within 48 hours. | Only relevant while the Strava path exists. |
| §7.4 | On revocation, a user's request, or "your cessation of use of the Strava API Materials", delete "all Strava Data and all Personal Data derived from Strava Data" within 30 days, and "certify deletion to Strava in writing on request". | This applies when we retire the Strava app: tokens, names and athlete ids used as keys. |
| §3.3 | Standard-tier apps require "that the developer or specified end users maintain an active Strava subscription". | Keeping even a login-only Strava app costs the owner a subscription and keeps the athlete cap (1 by default, 10 self-serve). |

**Uncertainties.**
- "AI Application", "MCP Server" and "Persistent Index" are undefined.
- Whether free-text notes fall under §5.5 and §7.4 is unclear.
- Enforcement practice and any grace period for existing apps are unknown.

**What to ask developers@strava.com** (Agreement §2.2 invites it). The full
list is in
[`strava-api-policy.md`](strava-api-policy.md#questions-for-developersstravacom).
1. May the current hosted Strava path continue, and if not, what grace period
   applies?
2. Is Strava OAuth *only for login* permitted in an MCP/AI product?
3. Must notes Claude wrote from Strava data be deleted under §7.4?
4. Is a user's Claude copying Strava MCP output into a third-party MCP
   server's notes acceptable?
5. Do athlete ids used as keys, or left in the training repo's history, count
   as Strava Data to delete?

This design does not depend on the answers: it removes our Strava app
either way. The answers set the pace (decision 2) and what happens to
existing notes (decision 3).

## 2. Target architecture

```
                    Claude (one conversation, two connectors)
                   /                                         \
   Train with GPT connector                           Strava connector
   (this server, our OAuth AS)                  (Strava's official MCP,
        |           |                             mcp.strava.com/mcp)
   our login    intervals.icu                     Strava subscribers only.
   (email code  (API key now,                     Our server never calls,
    [+ Google]) OAuth later)                      proxies or sees it.
        |           |
   internal id  activities, wellness,
   u_xxxx       load, zones, calendar
        |
   notes/<id>/, goals/<id>.md in the private training repo
```

### Identity

- **Claude does not tell a connector who the user is.** The only thing we
  learn from Claude is a dynamically registered client id. That id is per
  registration, not per user, and it changes when a user reconnects. So the
  server must run its own login inside the OAuth flow, as it does today.
- The OAuth Authorization Server (`oauth_provider.py`) stays. Only the
  upstream leg changes: `authorize()` redirects to **our own sign-in page**
  instead of `build_strava_authorize_url()`. `complete_authorization()`
  (`authorization.py`) is reused unchanged, now with an internal user id as
  `subject`.
- **Internal ids** are random: `u_` plus 26 base32 characters (128 bits).
  They never derive from a provider id. Notes and goals are keyed by them
  (`helpers.user_scoped_notes_dir` and `user_scoped_goals_file` don't change,
  only the value does).
- **Never accept an identity relayed by the model.** No tool argument like
  "my Strava athlete id is ..." may select a user. A value the model passes is
  not authentication (anyone can type it). A Strava athlete id is also itself
  Strava Data.

### Data

- **intervals.icu is linked** to the internal id through the existing
  `intervals_connections` table: it currently holds an encrypted API key and
  will hold an OAuth token once an app is approved. The connect page
  (`intervals_connect.py`) is reused after sign-in.
- Hosted data tools (`get_activities`, `analyze_activity`, `analyze_lap`,
  wellness, and the new tools from PR #12) read **only intervals.icu**. Users
  without it get a pointer (see §4.6), not an error.
- Strava-synced activities are empty stubs on intervals.icu. Users should
  connect their device to intervals.icu directly or import the Strava
  archive (details in `strava-api-policy.md`, option 2).

### Across the two connectors

What the model **can** do:
- Call Strava's tools (`list_activities`, `get_activity_performance`,
  `get_activity_streams`, `get_athlete_zones`, ...) and ours in the same
  conversation. It can discuss a Strava run next to our notes, goals and
  intervals.icu wellness. That is the user's AI using the user's own data,
  which §3.5 contemplates.
- Follow our guidance text. `start_consultation` can say: "if a Strava
  connector is available, use it for Strava activities; this server's
  activity tools read intervals.icu".

What it **can't** (or must not) do:
- Our server can't see whether the Strava connector exists, can't call it,
  and can't ask Claude to fetch from it on our behalf. There are no joins in
  our code (§5.4 would bar them anyway for a Strava developer, and we won't be
  one).
- It must not use the Strava connector to identify the user to us (see
  above).
- **Open question: Strava-derived numbers in our notes.** Claude may write
  "10 km at 5:00/km" into `save_consultation_notes`, or pass Strava values as
  tool arguments. Legally this is content the user provides, not "data you
  access or collect from the Strava API Materials" (Agreement §2.3), because
  we're no longer a Strava developer. But §3.5 says the Strava MCP may not be
  used "to enable ... third-party access", and on the hosted server the notes
  live in a repo the operator controls. Until Strava answers question 4:
  - build no tool that *ingests* Strava MCP output (no "import this Strava
    activity");
  - `start_consultation` asks Claude to keep notes qualitative when the
    source is Strava (decision 9);
  - longer-term, per-user notes repos would remove the "operator controls
    it" angle.
- Tool-name overlap: Strava's `get_athlete_profile`, `list_activities` and
  `get_athlete_zones` sit next to ours. Our descriptions say "from
  intervals.icu" so the model picks the right source.

The Strava MCP is available to paying Strava subscribers only (trials don't
count). It launched with Claude only, is read-only, and is rate-limited per
minute and per day, with the numbers not published
([help center](https://support.strava.com/hc/en-us/articles/46190267796237-Strava-MCP-Connector)).
Users on other MCP clients (e.g. `mcp-remote`) or without a subscription get
intervals.icu only.

## 3. Login options compared

All options plug into the same spot: the page `authorize()` redirects to.
All of them end in `complete_authorization(pending, user_id)`. They are not
exclusive: the `identities` table (§4.1) lets one account have several.

| Option | Third parties | Owner's personal accounts at stake | Cost | Effort | User friction | Works without intervals.icu | Recovery |
|---|---|---|---|---|---|---|---|
| **A. Email one-time code** (+ magic link) | Email-sending provider; domain registrar | None (a sending account on the app's domain) | ~$10–15/yr domain; email $0 at this scale | M | Low–medium: switch to the mailbox, codes can land in spam | Yes | The email itself |
| **B. Google sign-in** (OIDC, basic scopes) | Google | Low; very low with an isolated account (§3.2) | $0 | S–M | Lowest for most users | Yes | Google's |
| **C. GitHub OAuth** | GitHub | Minimal (can be owned by an org) | $0 | S | Low for developers, odd for athletes | Yes | GitHub's |
| **D. Passkeys** (WebAuthn) | None | None | $0 | M–L | Low once set up; needs bootstrap and recovery | Yes | Weak without email/second device |
| **E. intervals.icu as login** (API key now, OAuth later) | intervals.icu | None | $0 | S (key) / M (OAuth) | Medium: key copy-paste; needs an account | **No** | intervals.icu's |
| F. Hosted auth broker (WorkOS, Clerk, Auth0, Stytch) | The broker (+ Google for B) | Same as B if Google is enabled | Free tiers | S–M | Low | Yes | Broker's |

### 3.1 A. Email one-time code / magic link (recommended to start)

**Flow.**
1. `/authorize` parks Claude's request (as today) and redirects to
   `/login`: a page with one field (email) and a short "what this is" text.
2. We send a 6-digit code and a link, then show a "check your email, enter
   the code" page.
3. The correct code creates or loads the identity and calls
   `complete_authorization`.

**Why a code first, link second.** Claude opens the connector's OAuth in a
browser popup (web) or an in-app/system browser (mobile). A magic link
tapped in a mail app often opens in a *different* browser context, which
doesn't hold the parked authorization. Typing the code into the same window
always works. The link is kept as a convenience: if it opens in the same
browser (matched by a short-lived cookie), it completes the flow. Otherwise
it shows the code to type in the original window. This needs testing on
Claude mobile (uncertainty).

**Providers** (pricing checked 2026-09-26; re-check before choosing):

| Provider | Free tier | Paid entry | Notes |
|---|---|---|---|
| [Resend](https://resend.com/pricing) | 3,000/month, 100/day, 3 domains | $20/month for 50k | Simple API, quick domain setup. |
| [Postmark](https://postmarkapp.com/pricing) | 100/month (testing) | $15/month for 10k | Transactional-only reputation. New accounts go through a manual approval before sending to arbitrary recipients (from memory; verify). |
| Amazon SES | none to speak of | ~$0.10 per 1,000 | Starts in a sandbox (verified recipients only) until production access is granted; more setup. |
| Brevo, Mailgun | small free tiers | varies | Alternatives. |

A handful of users signing in a few times a month stays well inside any
free tier. Recommendation: Resend, because it is the least setup at this
volume.

**Deliverability.**
- A **custom domain is required.** We can't publish SPF/DKIM/DMARC records
  for `*.fly.dev`, and Gmail/Yahoo's 2024 sender rules require
  authentication. So: buy a domain (about $10–15/year) and publish SPF,
  DKIM and a DMARC `p=none` record to start. Send from e.g.
  `login@<domain>`, never from the owner's personal address.
- Keep the email short and plain: the code in the subject line and the body,
  one link to our own domain, no tracking pixels or link tracking.
- UX: "didn't get it? check spam", and a resend button with a cooldown.
- The same domain can host the landing page and privacy policy (needed by
  #11, by intervals.icu's OAuth application, and by Google's production
  consent screen). Optionally it can also host the server itself, as a
  custom domain on Fly.

**Our own sign-in page.**
- Same style and headers as `intervals_connect.py`: `no-store`, a strict
  CSP, `frame-ancestors 'none'`, no external assets.
- Routes: `GET/POST /login`, `POST /login/verify`, `GET /login/link`.

**Abuse and rate limits.**
- Codes are single-use and valid for 10 minutes. We store an HMAC of the
  code (keyed with a server secret, like `TOKEN_ENCRYPTION_KEY`), never the
  code itself. Comparison is constant-time.
- At most 5 wrong attempts per challenge, then a new code is needed. Wrong
  attempts are also limited per IP.
- **Email bombing** (someone typing a victim's address repeatedly) is
  limited:
  - per address: e.g. 3 per 15 minutes, 10 per day;
  - per IP;
  - globally, with a daily cap kept below the provider's limit so the
    sending account is never suspended for volume.
- **No account enumeration.** The response is the same whether or not the
  address is known.
- **Sign-up gate (decision 7):** an optional operator allowlist or invite
  code. The hosted server is small, and a gate caps both abuse and who uses
  the owner's resources. Unknown addresses can still get "ask the operator
  for an invite".
- Optional later: Cloudflare Turnstile (free) on the email form if bots
  show up.

**Privacy.**
- The email address becomes personal data we store. The privacy policy has
  to say so, and the email provider becomes a processor (it sees addresses).
- Store the address lower-cased and trimmed. Don't alias-fold (e.g. Gmail
  dots): that surprises users.
- Deleting the account deletes the email identity.

**Risk to the owner.** A sending account suspended for complaints would
break login until it's fixed, but it touches nothing personal. Keeping
another login (Google or intervals.icu) as a fallback covers that.

### 3.2 B. Google sign-in, and the "can I get banned" question

**Flow.**
- A standard OpenID Connect authorization-code flow with PKCE, scopes
  `openid email`, plus `profile` only if we want a display name.
- The identity is Google's stable `sub` claim, **not** the email address
  (emails can change or be recycled).
- The ID token is verified against Google's JWKS, or we call the userinfo
  endpoint over TLS right after the code exchange.
- We never request any Google API scope, and never ask for or keep refresh
  tokens.

**What Google requires for basic scopes.**
- "If your app utilizes only non-sensitive scopes, it is not mandatory for
  your app to complete the app verification process"
  ([OAuth app verification](https://support.google.com/cloud/answer/13463073)).
  Showing the app's name and logo on the consent screen needs a lighter
  "brand verification".
- The **unverified-app screen and the 100-user cap** apply to *sensitive or
  restricted* scopes: "100 new users in total, after the app presents the
  unverified app screen"
  ([Unverified apps](https://support.google.com/cloud/answer/7454865)).
  `openid`/`email`/`profile` never trigger that screen, so the cap does not
  apply.
- In the **"Testing"** publishing status, only listed test users (up to 100)
  can sign in. The 7-day refresh-token expiry doesn't apply when "the only
  OAuth scopes requested are a subset of name, email address, and user
  profile" ([OAuth 2.0 overview](https://developers.google.com/identity/protocols/oauth2)).
  We don't need refresh tokens anyway. "Testing" is also a fine way to run a
  closed beta.
- **"In production"** needs "a publicly accessible home page" with "links to
  terms of service and a privacy policy", and an app name that honestly
  reflects the app ([OAuth 2.0 policies](https://developers.google.com/identity/protocols/oauth2/policies)).
  OAuth clients unused for 6 months may be deleted.
- No billing account is needed for an OAuth client.

**Can this get the owner's personal Google account suspended?** Google
documents three levels
([project suspension guidelines](https://docs.cloud.google.com/resource-manager/docs/project-suspension-guidelines)):

1. **Project suspension:** for violating the Cloud ToS or Acceptable Use
   Policy. Workloads stop, and our Google login would stop working. Google
   sends a warning first ("If you do not respond to the warning in a timely
   manner your project may be suspended",
   [Policy violations FAQ](https://support.google.com/cloud/answer/7002354)),
   and there is an appeal.
2. **Google Cloud account suspension:** when a user "is consistently
   violating ToS or Google Cloud Acceptable Use Policy (AUP) through their
   projects ... the developer will not be able to access their Cloud
   projects. They will continue to have access to other Google services like
   Gmail."
3. **Google-wide disabled account:** under the general
   [Google Terms of Service](https://policies.google.com/terms). Google may
   suspend or delete an account for material or repeated breaches, or for
   conduct that harms others, "for example, by hacking, phishing, harassing,
   spamming, misleading others". This is the level the owner fears.

What realistically triggers enforcement against an OAuth client:
- deceptive branding or anything that looks like phishing (e.g. imitating
  Google's or Strava's login, or an app name that misrepresents who we are);
- misusing Google user data;
- a leaked client secret used by someone else for phishing;
- abuse coming from the project.

A sign-in-only client with basic scopes, an honest name, a privacy policy
and Google's standard button does none of these. **Assessment: the risk
that a basic-scope sign-in client gets the owner's personal account disabled
is low.** Even the documented Cloud-account consequence explicitly keeps
Gmail.

The honest residual risks:
- Enforcement is largely automated, false positives happen, and appeals are
  slow and opaque.
- Google does link "related" accounts in other products. In Google Play, a
  termination means "any related Google Play developer accounts will also be
  permanently suspended"
  ([Play enforcement](https://support.google.com/googleplay/android-developer/answer/9899234)).
  No equivalent related-account clause was found for Cloud or OAuth, but
  Google doesn't publish how it links accounts (phone number, recovery
  email, devices, payment methods).
- A project suspension breaks Google login for every user until an appeal
  succeeds.

**Proposed isolation** (if Google is chosen):
- Create a **dedicated Google account** used only for this app, e.g. on the
  app's own domain or a fresh address. The owner's personal account is
  **not** an owner, editor or member of the Cloud project, and not a
  recovery address for the new account.
- Give it its **own recovery**: a mailbox on the app's domain and saved
  backup codes. Avoid reusing the personal phone number if practical, since
  the phone number is the likeliest link between accounts. Use it from a
  separate browser profile.
- **No billing account attached.** It isn't needed for OAuth, and it removes
  a payment-method link and any "billing account suspension".
- **Basic scopes only** (`openid email`). No Google APIs enabled beyond
  what sign-in needs.
- Honest branding (the app's own name, not Strava's or Google's), a privacy
  policy and a home page, and Google's standard button.
- Keep the client secret in Fly secrets only. Rotate it on any suspicion.
- **Keep a second login** (email code) so a project suspension never locks
  users out of their notes.

With this, the remaining exposure to the personal account is whatever
undocumented linkage Google applies. That is the part nobody outside Google
can quantify.

**Also note:** hosted brokers (option F) don't remove this. In production
they generally require your own Google client credentials, so the Cloud
project still exists; the broker only holds the secret.

### 3.3 C. GitHub OAuth

- Self-serve, free, and no review. It works with no scopes: the identity is
  the numeric user id from `GET /user`. `user:email` is only needed if we
  want the email.
- The OAuth app can be owned by a GitHub organization instead of the
  personal account. A normal OAuth app carries little account risk.
- Downside: most athletes don't have GitHub accounts. It is useful as an
  owner and developer login, not as the primary one.

### 3.4 D. Passkeys

- No third party, no email cost, and phishing-resistant. There are mature
  libraries (`webauthn`, a.k.a. py_webauthn).
- But:
  - it needs a **bootstrap** (the first registration needs some identity,
    usually email) and **recovery** when a device is lost. Synced passkeys
    (iCloud Keychain, Google Password Manager) help but don't solve it;
  - WebAuthn inside Claude's mobile OAuth browser session is untested.
- Good as a second factor or a faster repeat login on top of email. Not
  first.

### 3.5 E. intervals.icu as the login

- **API key as login.** Works today: `GET /athlete/0` gives the athlete id.
  But:
  - the credential is a full-access, password-equivalent key from someone
    else, which is a gray area;
  - users without intervals.icu (Strava-MCP-only users) can't log in at all;
  - identity is tied to a data provider again. That is the exact failure
    mode this proposal removes: if the provider revokes access, login
    breaks.
- **intervals.icu OAuth:** scoped and revocable. It needs an approved app
  (public site and privacy policy), which is still pending.
- Recommendation: keep intervals.icu as the **linked data source**. Use its
  athlete id as a **migration proof** (§4.2), not as the primary login.

### 3.6 Recommendation

1. **Start with A (email one-time code).** It puts no personal account at
   stake, works for every user (with or without intervals.icu, with or
   without Strava), and its cost is a domain. The domain also serves the
   privacy policy and landing page that #11, intervals.icu OAuth and Google
   would need anyway.
2. **Add B (Google) later if users ask**, in an isolated account and project
   as in §3.2, always next to email, never instead of it.
3. C (GitHub) only as an owner or developer convenience. D (passkeys) later,
   as a faster repeat login. E only as a migration proof.

If the owner would rather avoid running email, Google-via-isolated-project
alone is the fallback. It is the lowest-friction option for users, with the
residual risks stated above.

## 4. Migration plan

### 4.1 Data model (SQLite `store.db`)

- `accounts(user_id TEXT PRIMARY KEY, created_at, disabled_at)`: internal
  ids `u_…`.
- `identities(provider TEXT, subject TEXT, user_id, email, created_at,
  last_login_at, PRIMARY KEY(provider, subject))`:
  - `provider` is one of `email`, `google`, `github`, `intervals`;
  - `subject` is the normalized email, Google `sub`, GitHub id or
    intervals.icu athlete id;
  - `strava_legacy` rows exist only during the migration window.
- `email_login_challenges(id, email, code_hmac, pending_json, attempts,
  created_at)`, plus a small rate-limit table (or in-memory counters; the
  app runs as one instance).
- `intervals_connections`: unchanged. Its `user_id` becomes the internal id.
- `users` (Strava tokens and names) is dropped at the end.
- The "durable identity mapping in the training repo" idea
  (`intervals-icu.md`) stays optional. If it is done, the repo gets only the
  internal id and provider names, **no emails and no tokens**.

### 4.2 Linking existing Strava-keyed users

Today `users.user_id`, `access_tokens.subject`,
`intervals_connections.user_id`, `notes/<id>/` and `goals/<id>.md` all use
the Strava athlete id (and so would #10's `athlete/<id>.md`). Paths, in order
of preference:

1. **Self-service at the next Strava login (recommended, while Strava login
   still exists).**
   - After the usual Strava callback, a page says "Strava sign-in is going
     away. Set up your new sign-in" and runs the email-code flow.
   - On success, in one step:
     - allocate `u_…`;
     - link the email identity;
     - rename `notes/<strava_id>/` → `notes/<u_id>/` and `goals/<strava_id>.md`
       → `goals/<u_id>.md` in one commit (through the existing training-repo
       lock and `git_save` helpers);
     - rewrite `access_tokens.subject` and `intervals_connections.user_id` in
       one SQLite transaction;
     - delete that user's `users` row (Strava tokens and name), after calling
       Strava's deauthorize endpoint.
   - This makes no Strava calls beyond what today's login already does.
     From then on that user signs in by email only.
2. **Match through intervals.icu.**
   - A user who signs in with the new login and connects intervals.icu with
     a key whose athlete id equals a legacy account's
     `intervals_connections.athlete_id` is offered "resume your existing
     notes".
   - Possession of that intervals.icu key is the proof. The migration then
     runs as in 1.
   - This keeps working after Strava login is gone.
3. **Operator mapping.** An admin command (dry-run by default) maps a
   legacy id to a new account after the operator verifies the person out of
   band. The user base is small and known to the operator. Watch for social
   engineering.
4. *(Not recommended)* A one-off "prove your Strava identity" OAuth after
   the new login, with minimal scope. It is still a use of Strava API
   Materials, so only consider it during the transition, and only if 1–3
   leave users stranded.

The rename is idempotent and resumable. If the git push fails, the DB is not
changed and the user is asked to retry. Old paths stay in the training repo's
**git history**. Rewriting it (`git filter-repo`) is possible but
destructive. That's decision 3, pending Strava's answer to question 5.

### 4.3 Deleting Strava data (§7.4)

At cutoff, the remaining `users` rows are handled like this:
- Call `POST https://www.strava.com/oauth/deauthorize` for each (this is part
  of cessation, not new processing), then delete the row.
- Drop the table.
- The owner deletes the Strava app on strava.com and removes
  `STRAVA_CLIENT_ID`/`STRAVA_CLIENT_SECRET` from Fly secrets.

All of this must happen within 30 days of ceasing use. The operator keeps a
short dated record, in case Strava asks for certification. Notes containing
Strava-derived numbers are decision 3.

### 4.4 Code to retire

- Remove `strava_oauth.py` and `strava_client.py`.
- Remove the `StravaClient` branches in:
  - `tools/get_activities.py`, `analyze_activity.py` and `analyze_lap.py`;
  - `get_hrv_data.py`, `get_sleep_data.py` and `get_resting_heart_rate.py`;
  - `self_test.py`;
  - client resolution in `server.py`.
- Remove the Strava settings in `config.py` and the Strava warning in
  `http_server.main()`.
- Reword `NO_WELLNESS_DATA_MESSAGE`, which mentions "the page shown after
  the Strava login".
- Update the README's hosted and Fly sections, plus the tests.

### 4.5 Unmigrated users

After cutoff, a Strava-keyed account whose owner never migrated keeps its
notes in the repo. Nobody can sign into it until the operator maps it
(path 3) or intervals.icu matches it (path 2). How long to keep such notes
is part of decision 3.

### 4.6 What the hosted data tools return without intervals.icu

Notes, goals and the consultation tools work for everyone. The activity and
wellness tools answer with guidance instead of an error, e.g.:

> This server reads training data from intervals.icu, which isn't connected
> for your account. To connect it, disconnect and reconnect this connector in
> Claude and paste your intervals.icu API key when asked. If you have a
> Strava subscription, you can also add Strava's own connector in Claude and
> ask about your Strava activities there.

`start_consultation` describes the same two sources. #11's onboarding owns
the exact wording.

### 4.7 Phased rollout

| Phase | What | Effort | Depends on |
|---|---|---|---|
| **0: owner, no code** | Email developers@strava.com. Choose the login (decision 1). Buy a domain, set up SPF/DKIM/DMARC and the email provider. Publish a privacy policy and landing page. (For Google: create the isolated account and project.) | — | — |
| **1: first shippable** | `accounts` + `identities` + email-code sign-in for **new** users (random ids, then the existing intervals.icu step). The "move your account" step (4.2 path 1) for Strava users. The optional sign-up gate. New users without intervals.icu get the §4.6 pointer. **No new Strava calls**, and legacy users on Strava login keep today's frozen behaviour until they migrate. | M | Phase 0 |
| 2: data off Strava | Hosted data tools read intervals.icu only (lines up with PR #12's tools). Strava reads are removed. `start_consultation`, README and onboarding recommend intervals.icu plus the Strava connector. Announce a cutoff date. | S–M | Phase 1; decision 2 |
| 3: cutoff | Remove the Strava login route and code (4.4). Delete tokens and names (4.3), then delete the Strava app. Operator maps stragglers (4.2 path 3). | S–M | Cutoff date |
| 4: later | intervals.icu OAuth in the connect step (once approved). Optional Google (isolated), passkeys or GitHub as extra identities. | M each | Approvals, demand |

Phase 1 is useful on its own: new users no longer need Strava at all, and
the Strava app's athlete cap stops limiting sign-ups.

### 4.8 Effect on sibling PRs (noted, not edited)

- **#9 consultation context:** its wellness-fallback wording (and
  `NO_WELLNESS_DATA_MESSAGE`) mentions the Strava login. Strava-path
  behaviour in the daily flow goes away in phase 2.
- **#10 athlete profile:**
  - `athlete/<user_id>.md` must be included in the rename (4.2);
  - its computed sections become intervals.icu-only;
  - the "Strava-only refresh (3–5 requests)" goes away;
  - nothing Strava-derived is persisted.
- **#11 onboarding:**
  - the flow becomes "sign in with email → connect intervals.icu (device
    synced directly, not via Strava) → optionally add Strava's connector
    (subscribers)";
  - the "activities source: Strava" branch, the Strava-based 12-week
    baseline and the Strava athlete-capacity concern disappear;
  - the `GET /` landing page can live on the new domain next to the privacy
    policy.
- **#12 more training data:** already intervals.icu-only. Its "switch hosted
  data tools" step is phase 2 here.
- **#13 science-based coaching:** time-in-zone is intervals.icu-only.
  Consistent.
- **#14 issue reporting:** "user ids (they are Strava athlete ids)" becomes
  random ids. Still never include them, and **never include emails**.

## 5. Decisions for the owner

1. ⚠️ **Critical: login method for phase 1.**
   - (a) email code;
   - (b) Google via an isolated account and project;
   - (c) both;
   - (d) GitHub;
   - (e) intervals.icu key.

   *Recommended:* (a) now, and (b) later if users ask, always alongside (a).
2. ⚠️ **Critical: the hosted Strava data path until phase 2** (moved from
   PR #12).
   - (a) turn it off now and point users to the Strava connector;
   - (b) keep it frozen until phase 1 ships and Strava replies (accepting
     the risk);
   - (c) extend it (not recommended).

   *Recommended:* (b), then (a) at phase 2.
3. ⚠️ **Critical: existing Strava-derived content.** This covers notes with
   Strava numbers, old ids in the training repo's git history, and
   unmigrated accounts' notes. Options: keep, scrub, or delete (§5.5, §7.4).
   *Recommended:* ask Strava (questions 3 and 5) before touching anything,
   since deletion and history rewrites are irreversible.
4. ⚠️ **Critical: how existing users are linked** (4.2).
   *Recommended:* path 1 (self-service at the next Strava login), with paths
   2 and 3 for stragglers. Not path 4.
5. **Buy a domain** for email sending, the privacy policy and the landing
   page (optionally also the server's hostname)? *Recommended:* yes.
6. **Email provider:** Resend, Postmark or SES? *Recommended:* Resend (least
   setup at this volume).
7. **Sign-up gate:** open, invite code, or operator allowlist?
   *Recommended:* allowlist or invite at first.
8. **Endorse Strava's MCP** in the README and onboarding as the optional
   Strava path (users pay Strava)? *Recommended:* yes.
9. **Tell Claude to keep notes qualitative when the source is Strava**,
   until Strava answers question 4? *Recommended:* yes.
10. **Apply for an intervals.icu OAuth app** once the privacy policy page
    exists? *Recommended:* yes.
11. **Durable identity mapping in the training repo** (`intervals-icu.md`
    idea 4)? *Recommended:* not now. If done, no emails or tokens in the
    repo.

## 6. Open uncertainties

- Strava's answers to the five questions, and any grace period.
- The Strava MCP's subscriber terms and rate limits. Whether it will come to
  clients other than Claude.
- Magic-link and passkey behaviour inside Claude's OAuth browser on web and
  mobile (hence code-first). This needs a manual test in phase 1.
- How Google links accounts for enforcement (undocumented). The Postmark
  approval step and provider pricing may have changed; re-check before
  choosing.
- Whether Claude clients handle a slow, multi-page login within their OAuth
  timeout. Today's intervals.icu page shows an interactive step already
  works, but the email round-trip is longer.
