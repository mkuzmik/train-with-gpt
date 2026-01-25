# Train With GPT

A Model Context Protocol (MCP) server for training analysis and coaching suggestions. Currently supports Strava as a data source.

## Features

This server provides tools for training analysis:
- **connect_strava**: Authenticate with Strava (opens browser for OAuth)
- **get_last_week_activities**: Fetches activities from the last 7 days with detailed metrics:
  - Distance, duration, and pace/speed
  - Elevation gain
  - Heart rate (average and max)
  - Power output (cycling)
  - Cadence
  - Temperature

Note: Currently supports Strava. Additional data sources planned for future releases.

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure Data Source (Strava)

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
      "command": "/path/to/python",
      "args": ["-m", "train_with_gpt.server"],
      "cwd": "/path/to/train-with-gpt"
    }
  }
}
```

Replace:
- `/path/to/python` with your Python path (e.g., `which python` or `~/.pyenv/shims/python`)
- `/path/to/train-with-gpt` with your project directory

### 4. Connect Your Data Source

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

### Testing Tools

Test individual tools during development:

```bash
# List all available tools
python test_tools.py --help

# Test a specific tool
python test_tools.py get_last_week_activities

# Test with arguments
python test_tools.py connect_strava '{"force": true}'
```

## Extending

### Adding New Data Sources
The architecture supports multiple data sources. To add a new source:
1. Create a new client module (similar to `strava_client.py`)
2. Implement OAuth/authentication flow
3. Add tools in `server.py` for the new source

### Adding New Tools
To add more tools for existing sources:
1. Add methods to `strava_client.py` for API calls
2. Add tool definition in `list_tools()` in `server.py`
3. Add tool handler in `call_tool()` in `server.py`
