"""The personal (single-user) MCP server, black box.

Two ways in, both speaking real MCP:
- the actual stdio entrypoints (`python -m train_with_gpt.server`, and the
  installed `train-with-gpt` console script) as a subprocess, configured purely through its environment - used for
  everything that needs no HTTP stubs (a subprocess can't see respx);
- the same `Server` over the SDK's in-memory transport, in-process, for the
  intervals.icu-backed tools, whose HTTP API is stubbed with respx.
"""

import contextlib
import json
import os
import shutil
import sys
import sysconfig

import pytest
from httpx import Response
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from tests.support import git, push_files, remote_file, remote_files
from train_with_gpt.server import app as mcp_server

INTERVALS = "https://intervals.icu/api/v1"


def _text(result) -> str:
    assert not result.isError, result
    assert len(result.content) == 1, result
    return result.content[0].text


@pytest.fixture
def stdio_env(hermetic):
    """Environment for the subprocess: our tmp HOME and git identity, nothing else."""
    env = {"HOME": str(hermetic), "XDG_CONFIG_HOME": str(hermetic / ".config"), "PATH": os.environ["PATH"]}
    env.update({name: value for name, value in os.environ.items() if name.startswith("GIT_")})
    return env


# The console script `uv sync` installs (pyproject `[project.scripts]`), next to
# this interpreter.
CONSOLE_SCRIPT = shutil.which("train-with-gpt", path=sysconfig.get_path("scripts"))
PYTHON_M = [sys.executable, "-m", "train_with_gpt.server"]


@contextlib.asynccontextmanager
async def StdioServer(env, command=PYTHON_M):
    """Spawn a stdio entrypoint; yields an initialized MCP ClientSession."""
    params = StdioServerParameters(command=command[0], args=command[1:], env=env)
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


# --- stdio subprocess ------------------------------------------------------------

async def test_stdio_lists_all_tools(stdio_env):
    async with StdioServer(stdio_env) as session:
        tools = (await session.list_tools()).tools

    assert len(tools) == 17
    assert {"get_activities", "save_consultation_notes", "setup_training_repo"} <= {tool.name for tool in tools}


async def test_stdio_ignores_the_hosted_allowlist(stdio_env):
    """ALLOWED_STRAVA_ATHLETE_IDS only gates the HTTP server: even a malformed
    value leaves the personal stdio server working."""
    async with StdioServer({**stdio_env, "ALLOWED_STRAVA_ATHLETE_IDS": "not,a,list"}) as session:
        output = _text(await session.call_tool("get_current_date", {}))

    assert output


async def test_console_script_serves_stdio(stdio_env):
    """The installed `train-with-gpt` command really serves MCP (it once just
    created an un-awaited coroutine and exited)."""
    assert CONSOLE_SCRIPT, "train-with-gpt console script not installed (run `uv sync`)"

    async with StdioServer(stdio_env, command=[CONSOLE_SCRIPT]) as session:
        tools = (await session.list_tools()).tools

    assert len(tools) == 17
    assert {"get_activities", "save_consultation_notes", "setup_training_repo"} <= {tool.name for tool in tools}


async def test_stdio_notes_and_goals_round_trip_through_the_remote(stdio_env, training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-10-08-00-00.md": "Earlier note from another device\n"})

    async with StdioServer({**stdio_env, "TRAINING_REPO_PATH": str(training_repo)}) as session:
        # Reading first pulls the other device's note (as start_consultation directs)...
        listed = _text(await session.call_tool("list_consultation_notes", {}))
        saved = _text(await session.call_tool("save_consultation_notes", {"notes": "Tempo run felt easy"}))
        read = _text(await session.call_tool("read_consultation_notes", {"all": True}))
        await session.call_tool("save_goals", {"goals_text": "Sub-40 10k"})
        goals = _text(await session.call_tool("read_goals", {}))

    assert "saved, committed and pushed to remote" in saved
    # Personal path: notes live at the repo root, not under a user id.
    notes = [path for path in remote_files(git_remote) if path.startswith("notes/")]
    assert len(notes) == 2 and all(path.count("/") == 1 for path in notes)
    assert "Found 2 consultation note(s)" in read
    assert "Tempo run felt easy" in read and "Earlier note from another device" in read
    assert "1 consultation note(s)" in listed and "Earlier note from another device" in listed
    assert "Sub-40 10k" in goals
    assert "Sub-40 10k" in remote_file(git_remote, "goals.md")


async def test_stdio_setup_training_repo_persists_across_restarts(stdio_env, tmp_path, hermetic):
    repo = tmp_path / "my-training"
    repo.mkdir()
    git(repo, "init", "--quiet")

    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("setup_training_repo", {"repo_path": str(repo)}))
    assert "Training repository configured" in output

    config_file = hermetic / ".config" / "train-with-gpt" / "config.json"
    assert json.loads(config_file.read_text()) == {"trainingRepoPath": str(repo)}

    # A fresh server process picks the saved path up from the config file.
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("read_goals", {}))
    assert "No goals saved yet" in output


async def test_stdio_without_intervals_key_reports_it(stdio_env):
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("get_activities", {}))

    assert output == "❌ Error: INTERVALS_API_KEY not configured"


async def test_stdio_without_training_repo_asks_for_setup(stdio_env):
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("read_goals", {}))

    assert "Training repository not configured" in output


# --- same server, in-memory transport, intervals.icu stubbed -------------------------

async def test_intervals_backed_tools(http_mock, intervals_api_key):
    http_mock.get(f"{INTERVALS}/athlete/0/activities").mock(return_value=Response(200, json=[{
        "id": "i1", "type": "Run", "distance": 5000, "moving_time": 1500, "start_date": "2024-01-15T07:00:00Z",
    }]))
    http_mock.get(f"{INTERVALS}/athlete/0/wellness").mock(return_value=Response(200, json=[
        {"id": "2024-01-15", "sleepSecs": 28800, "sleepScore": 90, "hrv": 61, "restingHR": 48},
    ]))
    http_mock.get(f"{INTERVALS}/activity/i1").mock(return_value=Response(200, json={
        "id": "i1", "type": "Run", "icu_intervals": [{"start_time": 0, "end_time": 1500, "distance": 5000,
                                                      "moving_time": 1500}],
    }))
    http_mock.get(f"{INTERVALS}/activity/i1/streams").mock(return_value=Response(200, json=[
        {"type": "time", "data": list(range(1500))},
        {"type": "distance", "data": [i * 3.33 for i in range(1500)]},
    ]))
    day = {"start_date": "2024-01-15", "end_date": "2024-01-15"}

    async with create_connected_server_and_client_session(mcp_server) as session:
        activities = _text(await session.call_tool("get_activities", day))
        sleep = _text(await session.call_tool("get_sleep_data", day))
        hrv = _text(await session.call_tool("get_hrv_data", day))
        rhr = _text(await session.call_tool("get_resting_heart_rate", day))
        analysis = _text(await session.call_tool("analyze_activity", {"activity_id": "i1"}))
        lap = _text(await session.call_tool("analyze_lap", {"activity_id": "i1", "lap_number": 1, "num_splits": 3}))

    assert "Found 1 activities for 2024-01-15" in activities and "5.00km" in activities
    assert "8h 0m | ⭐ Score: 90/100" in sleep
    assert "HRV: 61ms" in hrv
    assert "RHR: 48 bpm" in rhr
    assert "only one lap" in analysis
    assert "Split into 3 segments" in lap


async def test_unknown_tool_is_an_error():
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("no_such_tool", {})

    assert result.isError
    assert "Unknown tool: no_such_tool" in result.content[0].text
