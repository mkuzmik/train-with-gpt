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
  - Cadence (spm for running, rpm for cycling)
  - Temperature
  - Activity ID for detailed analysis
- **analyze_activity**: Deep dive analysis of a specific activity:
  - Lap-by-lap breakdown with metrics for each lap
  - Heart rate zone distribution (uses your Strava zones)
  - Power zone distribution (for cycling)
  - Automatic detection of interval workouts
  - Coaching insights based on workout type
- **discuss_goals**: Get framework for having a goal-setting conversation
- **save_goals**: Save training goals to persistent storage

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
- "Analyze activity 17130571886" (use ID from activity list)
- "What kind of workout was my run on January 21?"

The analyze_activity tool will:
- Show time spent in each heart rate/power zone
- Detect intervals automatically
- Provide coaching insights about your workout type

## Development

### Running Tests

**Install development dependencies:**
```bash
pip install -e ".[dev]"
```

**Run all tests:**
```bash
pytest tests/ -v
```

**Run specific test file:**
```bash
pytest tests/test_server.py -v
```

**Run specific test:**
```bash
pytest tests/test_server.py::test_setup_training_repo_success -v
```

### Testing Tools Manually

Test individual tools during development:

```bash
# List all available tools
python test_tools.py --help

# Test a specific tool
python test_tools.py get_last_week_activities

# Test with arguments
python test_tools.py setup_training_repo '{"repo_path": "/path/to/repo"}'
```

### Continuous Integration

Tests run automatically via GitHub Actions on:
- Every push to main branch
- Every pull request

The CI pipeline tests against Python 3.10, 3.11, and 3.12.

**⚠️ IMPORTANT: All tests must pass before merging PRs.**

### Writing Tests

**Critical Rules:**

✅ **MUST DO:**
1. **All tests must pass before committing** - Run `pytest tests/ -v`
2. **Add tests for new features** - New tool? Add test in `tests/test_server.py`
3. **Test both success and failure cases** - Happy path + error conditions
4. **Use mocking for external dependencies** - No real API calls, no real filesystem modifications
5. **Keep tests isolated** - Use `tempfile.TemporaryDirectory()` and patch config

❌ **MUST NOT DO:**
1. **Never skip tests** without documenting why with `@pytest.mark.skip(reason="...")`
2. **Never make real API calls** in tests - Always mock `httpx` calls
3. **Never commit commented-out tests** - Fix or remove them
4. **Never ignore test failures** - Fix the test or fix the code

**Test Structure:**

```python
@pytest.mark.asyncio  # Required for async tests
async def test_new_tool_success():
    """Test new_tool with valid inputs."""
    with patch('train_with_gpt.server.dependency') as mock_dep:
        # Setup
        mock_dep.return_value = "expected_value"
        
        # Execute
        result = await call_tool("new_tool", {"arg": "value"})
        
        # Assert
        assert len(result) == 1
        assert "✅" in result[0].text

@pytest.mark.asyncio
async def test_new_tool_error_case():
    """Test new_tool with missing required argument."""
    result = await call_tool("new_tool", {})
    
    assert "❌" in result[0].text
    assert "required" in result[0].text.lower()
```

**Common Mocking Patterns:**

```python
# Mock config
with patch('train_with_gpt.server.config') as mock_config:
    mock_config.training_repo_path = "/tmp/test"
    # Run test

# Mock HTTP requests (Strava API)
with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
    mock_response = MagicMock()
    mock_response.json.return_value = {"data": "value"}
    mock_get.return_value = mock_response
    # Run test

# Mock subprocess (git commands)
with patch('subprocess.run') as mock_run:
    mock_run.return_value = MagicMock(returncode=0, stdout="Success")
    # Run test

# Mock filesystem
with tempfile.TemporaryDirectory() as tmpdir:
    test_file = Path(tmpdir) / "test.txt"
    test_file.write_text("content")
    # Run test with isolated filesystem
```

**When Adding a New Tool:**

1. Add tool name to `test_list_tools` in `tests/test_server.py`
2. Add `test_{tool_name}_success` for the happy path
3. Add `test_{tool_name}_error` for each error condition
4. Mock all external dependencies (API calls, git, filesystem)

**Common Pitfalls:**

```python
# ❌ WRONG - Forgetting @pytest.mark.asyncio
async def test_something():
    result = await call_tool(...)

# ✅ CORRECT
@pytest.mark.asyncio
async def test_something():
    result = await call_tool(...)

# ❌ WRONG - Making real API call
async def test_get_activities():
    activities = await client.get_activities()

# ✅ CORRECT - Mocking the API call
async def test_get_activities():
    with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock:
        mock.return_value.json.return_value = []
        activities = await client.get_activities()
```

**Debugging Failed Tests:**

```bash
# Verbose output with full traceback
pytest tests/test_server.py::test_name -vv --tb=long

# Show print statements
pytest tests/test_server.py -v -s

# Drop into debugger on failure
pytest tests/ --pdb
```

**Test Files:**
- `tests/test_config.py` - Configuration management
- `tests/test_server.py` - MCP server tools (add new tool tests here)
- `tests/test_strava_client.py` - Strava API client

See test file headers for specific guidance on testing each module.

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
