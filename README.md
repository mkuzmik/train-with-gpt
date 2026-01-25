# Train With GPT

A Model Context Protocol (MCP) server for analyzing Strava training data.

## Features

This server provides tools for:
- **connect_strava**: Authenticate with Strava (opens browser)
- **get_last_week_activities**: Fetches activities from the last 7 days

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure Strava API Credentials

**Create a Strava API application:**
1. Go to https://www.strava.com/settings/api
2. Create an application with:
   - Authorization Callback Domain: `localhost`
3. Note your Client ID and Client Secret

**Save credentials to config file:**

Option 1 - Use a text editor:
```bash
mkdir -p ~/.config/train-with-gpt
nano ~/.config/train-with-gpt/config.json
```

Add this content:
```json
{
  "clientId": "YOUR_CLIENT_ID",
  "clientSecret": "YOUR_CLIENT_SECRET"
}
```

Option 2 - One-liner (replace values first):
```bash
mkdir -p ~/.config/train-with-gpt && echo '{"clientId":"YOUR_CLIENT_ID","clientSecret":"YOUR_CLIENT_SECRET"}' > ~/.config/train-with-gpt/config.json
```

### 3. Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "train-with-gpt": {
      "command": "/Users/mat/.pyenv/shims/python",
      "args": ["-m", "train_with_gpt.server"],
      "cwd": "/Users/mat/Code/train-with-gpt"
    }
  }
}
```

### 4. Connect Your Strava Account

In Claude, say: **"Connect my Strava account"**

This will:
1. Open your browser for Strava authentication
2. Save your access tokens automatically
3. You're ready to use!

## Usage

Once connected, ask Claude:
- "Show me my trainings from the last week"
- "Get my recent training activities"

## Development

Project structure:
```
train-with-gpt/
├── pyproject.toml
├── README.md
├── .env.example
└── src/
    └── train_with_gpt/
        ├── __init__.py
        ├── server.py
        └── strava_client.py
```

## Extending

To add more tools:
1. Add methods to `strava_client.py` for API calls
2. Add tool definition in `list_tools()` in `server.py`
3. Add tool handler in `call_tool()` in `server.py`
