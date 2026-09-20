# Train With GPT

A Model Context Protocol (MCP) server that turns Claude into your personal endurance training coach. Connects to your [intervals.icu](https://intervals.icu) data (activities, sleep, HRV, resting heart rate — synced from Strava/Garmin/etc.) and maintains context about your goals and training history across conversations.

## What This Does

- **Training Analysis**: View and analyze your activities with detailed metrics and zone distribution
- **Sleep & Health Tracking**: Access wellness data - sleep duration/quality, HRV, resting heart rate
- **Goal Tracking**: Set training goals and have them persist across conversations
- **Consultation History**: Claude remembers past conversations and provides continuity
- **Smart Coaching**: Claude acts as an experienced coach who asks thoughtful questions and provides data-informed guidance

All training and health data comes from a single source: your [intervals.icu](https://intervals.icu) account. intervals.icu already syncs from Strava, Garmin, and most other platforms, so if your watch/app already feeds it, no separate connection is needed here.

## Quick Start

### 1. Install

```bash
pip install -e .
```

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

Restart Claude Desktop.

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
- Claude shows: sleep duration/quality score, HRV, resting heart rate, rolling averages

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
pytest tests/test_get_activities.py -v
```

**Run specific test:**
```bash
pytest tests/test_get_activities.py::test_get_activities_default_last_week -v
```

### Testing Tools Manually

Test individual tools during development:

```bash
# List all available tools
python test_tools.py --help

# Test a specific tool
python test_tools.py get_activities

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
2. **Add tests for new features** - New tool? Add a `tests/test_<tool_name>.py`
3. **Test both success and failure cases** - Happy path + error conditions
4. **Use mocking for external dependencies** - No real API calls, no real filesystem modifications
5. **Keep tests isolated** - Use `tempfile.TemporaryDirectory()` and patch config

❌ **MUST NOT DO:**
1. **Never skip tests** without documenting why with `@pytest.mark.skip(reason="...")`
2. **Never make real API calls** in tests - Always mock `IntervalsClient` methods
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

# Mock the intervals.icu client (used by most tools)
with patch('train_with_gpt.server.intervals') as mock_intervals:
    mock_intervals.get_activities = AsyncMock(return_value=[...])
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

1. Add the tool to `list_tools()` and `call_tool()` in `server.py`
2. Add `test_{tool_name}_success` for the happy path
3. Add `test_{tool_name}_error` for each error condition
4. Mock all external dependencies (`intervals` client, git, filesystem)

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
    with patch('train_with_gpt.server.intervals') as mock:
        mock.get_activities = AsyncMock(return_value=[])
        activities = await client.get_activities()
```

**Debugging Failed Tests:**

```bash
# Verbose output with full traceback
pytest tests/test_get_activities.py::test_name -vv --tb=long

# Show print statements
pytest tests/ -v -s

# Drop into debugger on failure
pytest tests/ --pdb
```

**Test Files:**
- `tests/test_config.py` - Configuration management
- `tests/test_get_activities.py`, `tests/test_analyze_activity.py`, `tests/test_analyze_lap.py` - Activity tools
- `tests/test_get_sleep_data.py`, `tests/test_get_hrv_data.py`, `tests/test_get_resting_heart_rate.py` - Wellness tools
- `tests/test_consultation_notes.py`, `tests/test_goals.py`, `tests/test_setup_training_repo.py` - Notes/goals persistence

See test file headers for specific guidance on testing each module.

## Extending

### Adding New Tools
1. Add methods to `intervals_client.py` for new intervals.icu API calls
2. Add tool definition + handler in the relevant `tools/*.py` file
3. Wire it into `tools/__init__.py` and `server.py` (`list_tools()` and `call_tool()`)
