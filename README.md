# Train With GPT

A Model Context Protocol (MCP) server that turns Claude into your personal endurance training coach. Connects to your [intervals.icu](https://intervals.icu) data (activities, sleep, HRV, resting heart rate — synced from Strava/Garmin/etc.) and maintains context about your goals and training history across conversations.

## What This Does

- **Training Analysis**: View and analyze your activities with detailed metrics and zone distribution
- **Sleep & Health Tracking**: Access wellness data - sleep duration/quality, HRV, resting heart rate
- **Goal Tracking**: Set training goals and have them persist across conversations
- **Consultation History**: Claude remembers past conversations and provides continuity
- **Smart Coaching**: Claude acts as an experienced coach who asks thoughtful questions and provides data-informed guidance
- **Evidence-aware advice**: `start_consultation` carries a short, dated set of training-science principles with confidence labels and DOIs, safety referral rules and conservative weight guidance (see `docs/ideas/science-based-coaching.md`). It is general information, not medical advice.

All training and health data comes from a single source: your [intervals.icu](https://intervals.icu) account. intervals.icu already syncs from Strava, Garmin, and most other platforms, so if your watch/app already feeds it, no separate connection is needed here.

There are two ways to run it: **locally over stdio** (single user, intervals.icu API key — the Quick Start below), or as a **hosted HTTP server** (multi-user, Strava OAuth, works from the Claude mobile app — see "Deploying to Fly.io"). Hosted users get Strava activity data only; sleep/HRV/resting HR need the intervals.icu path.

## Quick Start

### 1. Install

Dependencies are pinned in `uv.lock`; install [uv](https://docs.astral.sh/uv/) (e.g. `brew install uv`), then from the project directory:

```bash
uv sync
```

This creates `.venv/` with the project and its locked dependencies (including the dev/test tools).

### 2. Get an intervals.icu API Key

1. Sign in to https://intervals.icu (if you don't have an account yet, connect your existing Strava/Garmin/etc. data to it first)
2. Go to Settings → Developer Settings
3. Copy your API key

**Save it to the config file:**

```bash
mkdir -p ~/.config/train-with-gpt
cat > ~/.config/train-with-gpt/config.json << 'EOF'
{
  "intervalsApiKey": "YOUR_INTERVALS_ICU_API_KEY"
}
EOF
chmod 600 ~/.config/train-with-gpt/config.json
```

The `chmod 600` restricts file access to you only. Alternatively, set the `INTERVALS_API_KEY` environment variable instead of using the config file (env vars take priority when both are set).

### 3. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "train-with-gpt": {
      "command": "/path/to/train-with-gpt/.venv/bin/train-with-gpt"
    }
  }
}
```

Replace:
- `/path/to/train-with-gpt` with your project directory (`train-with-gpt` is the console script `uv sync` installs into `.venv`)

`/path/to/train-with-gpt/.venv/bin/python -m train_with_gpt.server` runs the
same stdio server, if you prefer that form.

Restart Claude Desktop.

### Alternative: Run as a standalone HTTP server (multi-user)

Instead of (or alongside) the stdio entrypoint above, the server can run over
HTTP (MCP's Streamable HTTP transport), independent of any locally-spawned
Claude Desktop subprocess. This mode is a full OAuth Authorization Server:
Claude authenticates via a Strava login/consent flow, and every connected
user gets their own identity and their own Strava data — separate from the
stdio entrypoint above, which always uses your personal `INTERVALS_API_KEY`.

You'll need a Strava OAuth app (instant/self-serve, unlike intervals.icu's):
1. Create one at https://www.strava.com/settings/api (set "Authorization
   Callback Domain" to `localhost` for local/Docker testing).
2. Save its Client ID/Secret to `~/.config/train-with-gpt/config.json` as
   `clientId`/`clientSecret`, or export `STRAVA_CLIENT_ID`/`STRAVA_CLIENT_SECRET`.

Start the server:

```bash
uv run train-with-gpt-http
# or: PORT=8000 PUBLIC_URL=http://localhost:8000 uv run train-with-gpt-http
```

This starts a Starlette/uvicorn app with:
- `GET /health` — unauthenticated health check
- `/.well-known/oauth-authorization-server`, `/register`, `/authorize`,
  `/token` — the OAuth endpoints Claude/`mcp-remote` use automatically
- `/oauth/strava/callback` — completes the nested Strava leg of the flow
- `POST/GET /mcp` — the MCP endpoint itself, gated by a bearer token this
  server issued (not a shared secret)

Connect a client that doesn't natively support this (e.g. Claude Desktop) via
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote), which handles the
whole OAuth dance (opens a browser, runs its own callback listener):

```json
{
  "mcpServers": {
    "train-with-gpt-http": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "http://localhost:8000/mcp"]
    }
  }
}
```

See "Deploying to Fly.io" below for the public deployment. The Docker setup
below simulates a remote deployment locally.

### Running the HTTP server in Docker

A `Dockerfile`/`docker-compose.yml` at the repo root run the HTTP entrypoint
above in a container — closer to how it'd behave actually deployed
(no host Python/venv, its own filesystem, reachable only through the port
you map) without needing a real remote host yet.

```bash
docker compose up --build
```

Secrets aren't passed as environment variables (they'd show up in plain text
in `docker inspect`/`docker exec env`). Instead, `docker-compose.yml`
passes your existing `~/.config/train-with-gpt/config.json`
(`clientId`/`clientSecret`/`intervalsApiKey`, from the setup steps above)
as a file secret, and `docker-entrypoint.sh` copies it into the container's
config dir owned by the `app` user (the host file's `chmod 600` owner UID
usually isn't the container's). No code changes or exports are needed, just
that the file exists on the host (`chmod 600`, and never committed - see
`.gitignore`). Add `"tokenEncryptionKey"` (a Fernet key, generated as in the
Fly.io setup below) to it to turn on the optional intervals.icu login step.

This maps container port 8000 to `localhost:8123` on the host and sets
`PUBLIC_URL=http://localhost:8123` to match (override either with `HOST_PORT`/
`PUBLIC_URL` env vars — they must stay in sync, since `PUBLIC_URL` is what
gets baked into the OAuth redirect URIs sent to Claude and Strava). Point
`mcp-remote` at `http://localhost:8123/mcp` as above.

The container's `~/.config/train-with-gpt` directory is a named Docker
volume (`train-with-gpt-config`), so the SQLite store (users/tokens/OAuth
clients, kept at mode `600`) survives `docker compose restart`/rebuilds;
`config.json` is re-copied from the host file on every start.
`docker compose down -v` clears the store (not the host file).

**Notes/goals repo in Docker.** OAuth'd users' notes and goals are stored per
user (`notes/<user_id>/`, `goals/<user_id>.md`) in a separate, *private* git
repo, cloned by the container on first start (`docker-entrypoint.sh`) and
pushed to on every save. Set it up once:

1. Create a private repo (e.g. `training-context-shared`) and set
   `TRAINING_REPO_URL` (default in `docker-compose.yml`/`fly.toml`, edit it to
   your repo).
2. Generate a dedicated deploy key and save it outside the repo:
   ```bash
   ssh-keygen -t ed25519 -f ~/.config/train-with-gpt/training-context-deploy-key -N "" -C "train-with-gpt"
   chmod 600 ~/.config/train-with-gpt/training-context-deploy-key
   ```
3. Add the `.pub` file as a **deploy key with write access** in that repo's
   GitHub settings (scoped to just that repo — not a personal access token).

Compose mounts the key as a Docker secret; the entrypoint copies it to the
`app` user with correct permissions. `setup_training_repo` is deliberately
disabled for OAuth sessions — the repo is server configuration
(`TRAINING_REPO_PATH`/`TRAINING_REPO_URL`), not a per-user setting.

## Deploying to Fly.io (public, HTTPS)

This is how the server runs remotely so it works from other devices (including
the Claude mobile app). The repo's `Dockerfile` and `fly.toml` are used as-is.
**Never commit secrets** — this repo is public; everything sensitive below goes
through `fly secrets` or files under `~/.config/train-with-gpt/`.

### One-time setup

1. Install and log in (`fly auth login` needs a real terminal, not a `!` shell):
   ```bash
   brew install flyctl
   fly auth login
   ```
2. Pick a globally unique app name; set it as `app` and in `PUBLIC_URL`
   (`https://<app>.fly.dev`) in `fly.toml`, then create the app and a volume
   (holds `store.db` — without it users are logged out on every deploy):
   ```bash
   fly apps create <app>
   fly volumes create train_with_gpt_data --region fra --size 1 -a <app>
   ```
3. Register the Strava OAuth app at https://www.strava.com/settings/api and set
   **Authorization Callback Domain** to `<app>.fly.dev` (hostname only — no
   `https://`, no path). Strava allows one domain per app, so a second app is
   needed if you also want to keep testing against `localhost`.
4. Set secrets (encrypted, injected as env vars at runtime). The deploy key
   must keep its real newlines, so pass it via `$(cat ...)`:
   ```bash
   fly secrets set -a <app> \
     STRAVA_CLIENT_ID=... \
     STRAVA_CLIENT_SECRET=... \
     "TRAINING_CONTEXT_DEPLOY_KEY=$(cat ~/.config/train-with-gpt/training-context-deploy-key)" \
     "TOKEN_ENCRYPTION_KEY=$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
   ```
   `TOKEN_ENCRYPTION_KEY` encrypts users' intervals.icu API keys in `store.db`
   and turns on the optional intervals.icu step at login (see below). Leave it
   out to skip that step. Changing it later makes stored keys unreadable, so
   users would need to add them again.
5. Deploy:
   ```bash
   fly deploy --ha=false -a <app>
   ```

### Verify

```bash
curl https://<app>.fly.dev/health                                   # {"status":"ok"}
curl -i -X POST https://<app>.fly.dev/mcp                           # 401 + WWW-Authenticate
curl https://<app>.fly.dev/.well-known/oauth-authorization-server   # https:// URLs
fly logs -a <app>
```

Then run the real flow: `npx mcp-remote https://<app>.fly.dev/mcp` (opens a
browser for Strava consent) and call a tool.

### Connecting clients

- **Claude mobile / web:** claude.ai → Settings → Connectors → Add custom
  connector → `https://<app>.fly.dev/mcp`, sign in with Strava. It syncs to the
  mobile app (paid plan required).
- **Claude Desktop:** use `mcp-remote` as in the local setup, with the
  `https://<app>.fly.dev/mcp` URL.

**Sleep, HRV and resting HR (optional).** Strava has no wellness data. After
the Strava consent, the login shows one more page asking for your
intervals.icu API key (intervals.icu → Settings → Developer Settings). If your
Garmin syncs to intervals.icu, paste it there and the wellness tools use it;
otherwise press Skip. The key goes from your browser straight to the server
(never through Claude or the chat), is checked against intervals.icu, and is
stored encrypted.

- It belongs to your account, not to a device: add it once from any client and
  it works everywhere you're connected.
- **Already connected?** Disconnect and reconnect the connector (claude.ai →
  Settings → Connectors). Strava usually skips its consent screen for an app you
  already approved, so you go straight to the intervals.icu page. The same page
  lets you replace or disconnect the key later.
- Personal intervals.icu keys have full access to the account. To cut the
  server off, regenerate your key on intervals.icu.

### Operations

- **Redeploy:** `fly deploy --ha=false -a <app>`. The volume (and therefore
  users/tokens) survives; the notes repo is re-cloned on boot (saves push
  immediately, so nothing is lost unless a push failed).
- **Auto-stop:** the machine stops when idle and starts on the next request
  (`fly.toml`), so the first request after a quiet period is slower.
- **Backups:** Fly snapshots the volume daily (5 days). It's one copy on one
  machine; if lost, users simply re-authenticate.
- **Rotating secrets:** re-run `fly secrets set ...` (redeploys automatically).
  For the Strava secret, regenerate it in Strava's settings first. For the
  deploy key, generate a new one, swap it in GitHub, then set the secret.
- **Revoking access:** clients can revoke their own token via `/revoke`. To
  cut off a user (e.g. a leaked token), open `fly ssh console -a <app>` and
  run `su app -c 'python -c "from train_with_gpt import store; print(store.delete_user_access_tokens(\"<user_id>\"))"'`
  (or delete `store.db` and restart to log everyone out). Each device holds
  its own token, so a new login does not invalidate the others.
- **`mcp-remote` cache:** clients cache OAuth registrations per server URL in
  `~/.mcp-auth`. If you wipe the server's store, clear that folder too or you
  will get `400` on `/authorize`.
- **Limitations:** OAuth'd users' activities always come from Strava.
  Wellness (sleep/HRV/resting HR) needs the optional intervals.icu key.

## Usage

### First Time Setup

**Step 1: Set Up Training Repository** (Recommended)

Create a git repository for your training notes:
```bash
mkdir ~/training-notes
cd ~/training-notes
git init
```

Then tell Claude: **"Setup my training repository at ~/training-notes"**

This enables goal tracking and consultation history across sessions.

**Step 2: Set Your Goals**

Say: **"Let's discuss my training goals"**
- Claude will guide you through setting clear goals
- Your goals are saved and referenced in future conversations
- Say **"Save these goals"** when ready

---

### Using the Coach

**Starting a Conversation**

Best practice: **"Start a consultation"**

This tells Claude to:
1. Check today's date
2. Review your goals
3. Read recent consultation notes
4. Act as a thoughtful coach (asking ONE question at a time)

**Reviewing Your Training**

- "Show me my activities from last week"
- "Show me my runs from January 15 to 20"
- "What did I do yesterday?"

**Analyzing Workouts**

- "Analyze my most recent run"
- "Analyze activity i180171555" (use ID from activity list)
- Claude shows: zone distribution, interval detection, coaching insights

**Reviewing Sleep & Recovery**

- "Show me my sleep from last night"
- "How was my sleep on January 15?"
- "What's my HRV trend this week?"
- Claude shows: sleep duration/quality score, HRV, resting heart rate, rolling averages, read against your own baseline rather than "higher is better"

**Continuing Conversations**

At the end of a session:
- **"Save notes from this consultation"** - Creates timestamped record
- **"What did we discuss last time?"** - Reviews recent consultations

Your goals and consultation notes persist across conversations, giving Claude full context.

---

### Example Workflow

```
You: "Start a consultation"

Claude: [Reads goals, reviews notes, checks date]
        "I see your goal is to run a sub-4 hour marathon in June.
         Last week we discussed building your long runs. 
         How are you feeling today?"

You: "Show me my runs from the past week"

Claude: [Shows activities with metrics]
        "I see three runs. Would you like me to analyze 
         the interval workout from Thursday?"

You: "Yes, analyze that one"

Claude: [Shows zone distribution, detects intervals]
        "This looks like a threshold workout..."

[Conversation continues...]

You: "Save notes from this consultation"

Claude: ✅ Saved to training-notes/notes/2024-01-28-10-30-15.md
```

## Troubleshooting

**Problem:** Tools return "INTERVALS_API_KEY not configured"
**Solution:**
1. Check `~/.config/train-with-gpt/config.json` has `intervalsApiKey` set, or that `INTERVALS_API_KEY` is exported in your environment
2. Restart Claude Desktop after changing config

**Problem:** No wellness data (sleep/HRV/resting HR) shows up
**Solution:** intervals.icu only has wellness data for dates you've synced a source (Garmin, Oura, etc.) into it. Check your intervals.icu account has a wellness source connected.

## Development

### Running Tests

**Install development dependencies** (the `dev` group is included by default):
```bash
uv sync
```

**Run everything (both levels):**
```bash
uv run pytest
```

**Run one level:**
```bash
uv run pytest tests/unit          # or: uv run pytest -m unit
uv run pytest tests/integration   # or: uv run pytest -m integration
```

**Run a specific file or test:**
```bash
uv run pytest tests/unit/test_get_activities.py -v
uv run pytest tests/unit/test_get_activities.py::test_explicit_date_range -v
```

The suite is hermetic, so it passes the same way on any machine, in any order
(`uv run --with pytest-randomly pytest` shuffles it). `tests/conftest.py`
enforces this for every test:
- `HOME` is a throwaway directory, set *before* `train_with_gpt` is imported.
  The global `config` loads at import time, so without this the tests would
  read your real `~/.config/train-with-gpt/config.json` and `store.db`.
- `INTERVALS_API_KEY`, `STRAVA_CLIENT_*`, `TOKEN_ENCRYPTION_KEY`,
  `TRAINING_REPO_PATH`, `PUBLIC_URL`, `PORT` and all `GIT_*` env vars are
  cleared, and git gets a fixed test identity.
- The global `config` starts empty, and its file and the SQLite store live in
  the test's `tmp_path`.
- All httpx traffic goes through a respx router (the `http_mock` fixture).
  Any request that isn't stubbed fails the test, and so does any non-loopback
  socket connection.

**Changing dependencies:** edit `pyproject.toml` (or use `uv add` / `uv add --dev`), then run `uv lock` and commit the updated `uv.lock`. CI fails if the lockfile is out of date, and the Docker image installs exactly what's locked.

### Testing Tools Manually

Test individual tools during development:

```bash
# List all available tools
uv run python test_tools.py --help

# Test a specific tool
uv run python test_tools.py get_activities

# Test with arguments
uv run python test_tools.py setup_training_repo '{"repo_path": "/path/to/repo"}'
```

### Continuous Integration

Tests run automatically via GitHub Actions on:
- Every push to main branch
- Every pull request

The CI pipeline tests against Python 3.10 through 3.14, running the unit and integration levels as separate steps. The Docker image and local dev (`.python-version`) use 3.14.

**⚠️ IMPORTANT: All tests must pass before merging PRs.**

### Writing Tests

Tests come in two levels. Pick the level by what you're testing, not by what's
easiest to set up.

**Unit tests (`tests/unit/`)** test one module or tool handler directly, with
as little faking as possible:
- Use real objects: a real `IntervalsClient`/`StravaClient`, a real temp
  SQLite store (the `db` fixture), real config files in `tmp_path`, and real
  git repos. The `training_repo` fixture is a clone of `git_remote`, a local
  bare repo, and is already set as the training repo.
- Stub only true I/O boundaries: HTTP to intervals.icu or Strava, through the
  `http_mock` respx router.
- Don't patch internals (`subprocess.run`, client methods, `train_with_gpt.*`
  functions). If something is hard to test without patching, make it
  injectable instead, like `Config(config_file)` or `create_app()`.
- Assert on behaviour: the tool's output text, files in the repo or its
  remote, rows in the store, and the HTTP requests that were or weren't made
  (`route.calls`, `route.called`). Don't assert that a mock was called.

**Integration tests (`tests/integration/`)** test the app as a black box,
through its public interfaces only:
- The HTTP server: `create_app()` behind Starlette's `TestClient` (the `http`
  fixture). Drive the OAuth endpoints (`/register`, `/authorize`,
  `/oauth/strava/callback`, `/token`, `/revoke`) and `/mcp` with real MCP
  JSON-RPC (`McpHttpClient`). `login(athlete_id)` runs the full OAuth round
  trip and returns an initialised MCP client. It walks through the optional
  intervals.icu page, which is on when a test has
  `@pytest.mark.intervals_login_step`, by skipping it or pasting
  `intervals_api_key=...`.
- The personal stdio server: the installed `train-with-gpt` console script
  or `python -m train_with_gpt.server` as a subprocess (`StdioServer`). For
  intervals.icu-backed tools, which need HTTP stubs a subprocess can't see,
  use the same `Server` over the MCP SDK's in-memory transport.
- Configure the app the way production does, through env vars and
  `config.load()` (the `server_env` fixture).
- Stub only external dependencies: Strava (`FakeStrava`), intervals.icu
  (`http_mock`), and the git remote (`git_remote`, a local bare repo). Check
  results through the public interface or in the bare remote, e.g. that notes
  landed under `notes/<user_id>/`.

**Rules for both levels:**
1. Never touch the real `~/.config/train-with-gpt/`, real env vars or the
   network. The autouse fixtures enforce this, so don't work around them.
2. Don't depend on the current date or time. Use fixed dates, or compare
   against values taken before and after the call.
3. Don't leak state: use `monkeypatch` and fixtures, not manual
   save-and-restore.
4. Test both the happy path and the error cases.
5. Don't skip tests silently. Use `@pytest.mark.skip(reason=...)` or
   `xfail(strict=True, reason=...)` for a known bug.

Async tests need no decorator (`asyncio_mode = "auto"`):

```python
async def test_get_activities_date_range(http_mock, intervals_api_key):
    route = http_mock.get("https://intervals.icu/api/v1/athlete/0/activities").mock(
        return_value=Response(200, json=[{"id": "i1", "type": "Run", "distance": 5000,
                                          "moving_time": 1500, "start_date": "2024-01-10T10:00:00Z"}])
    )

    result = await get_activities_handler(
        {"start_date": "2024-01-10", "end_date": "2024-01-15"}, IntervalsClient()
    )

    assert "5.00km" in result[0].text
    assert route.calls.last.request.url.params["oldest"] == "2024-01-10"
```

**When adding a new tool:**
1. Add it to `list_tools()` and `call_tool()` in `server.py`.
2. Add `tests/unit/test_<tool_name>.py` covering the handler's success and
   error cases.
3. Add or extend an integration test that calls it over MCP, e.g. in
   `tests/integration/test_oauth_flow.py` or `test_personal_server.py`.

**Debugging failed tests:**

```bash
uv run pytest tests/unit/test_get_activities.py::test_name -vv --tb=long
uv run pytest -s        # show print/stderr output
uv run pytest --pdb     # drop into the debugger on failure
```

**Test layout:**
- `tests/conftest.py`: the hermetic environment and shared fixtures
  (`http_mock`, `db`, `git_remote`, `training_repo`, credentials).
  `tests/support.py` has plain git and text helpers.
- `tests/unit/`: `test_config.py`, `test_store.py`, `test_helpers.py` (git
  operations, headlines, zones), the HTTP clients (`test_intervals_client.py`,
  `test_strava_client.py`), OAuth (`test_oauth_provider.py`,
  `test_strava_oauth.py`, `test_intervals_connect.py` for the optional
  intervals.icu login step and `secret_box`) and one file per tool.
- `tests/integration/`: `test_oauth_flow.py` (full OAuth round trip, then
  MCP tool calls), `test_http_auth.py` (the /mcp auth boundary),
  `test_user_isolation.py` (per-user notes and goals) and
  `test_personal_server.py` (the stdio server).

## Extending

### Adding New Tools
1. Add methods to `intervals_client.py` for new intervals.icu API calls
2. Add tool definition + handler in the relevant `tools/*.py` file
3. Wire it into `tools/__init__.py` and `server.py` (`list_tools()` and `call_tool()`)
