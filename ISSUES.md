# train-with-gpt: Issues Found

## 1. `garminconnect` API breaking change — `garth` → `client`

**Files affected:**
- `setup_garmin.py:64`
- `src/train_with_gpt/garmin_client.py:66`

**Problem:** The `garminconnect` library (v0.3.x) renamed the internal client attribute from `garth` to `client`. Calls to `client.garth.dump()` fail with `AttributeError: 'Garmin' object has no attribute 'garth'`.

**Fix:** Replace `client.garth.dump(...)` with `client.client.dump(...)`.

## 2. README only documents Claude Desktop configuration

**File:** `README.md:68-82`

**Problem:** Setup instructions only show Claude Desktop MCP config. The server is provider-agnostic and works with any MCP client (OpenCode, etc.). Should document alternative clients or at least mention it's not Claude-specific.

## 3. No `uv` / venv setup instructions

**File:** `README.md`

**Problem:** README doesn't mention using `uv sync` (or `pip install -e .`) to create a venv and install dependencies. Users have to figure out the Python packaging step themselves.

**Fix:** Add a section between "Clone" and "Configure" with `uv sync` or `pip install -e .` instructions.

## 4. No OpenCode configuration instructions

**File:** `README.md`

**Problem:** No instructions for using the server with OpenCode. Should document creating an `opencode.json` with the local MCP config:
```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "train-with-gpt": {
      "type": "local",
      "command": [".venv/bin/python", "-m", "train_with_gpt.server"]
    }
  }
}
```

## 5. `command` format in MCP config example

**File:** `README.md:76-77`

**Problem:** The example uses `"command"` and `"args"` as separate fields, which is the Claude Desktop format. Other MCP clients (like OpenCode) expect `"command": ["python", "-m", "train_with_gpt.server"]` as an array. Worth noting in docs.
