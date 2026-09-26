"""What each transport offers and says, black box: the hosted (OAuth) HTTP
server vs the personal stdio server.

Hosted users get Strava activities, no setup_training_repo, and an "ask the
operator" message when the server has no notes storage; the stdio user gets
intervals.icu, setup_training_repo, and is told to run it. Both get one entry
point, start_consultation, which reports whether this athlete is new or
returning (no separate discuss_goals tool).
"""

import pytest
from httpx import Response
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.testclient import TestClient

from tests.support import push_files, referenced_tool_names
from train_with_gpt.config import config
from train_with_gpt.http_server import create_app
from train_with_gpt.server import app as mcp_server

from .conftest import PUBLIC_URL, McpHttpClient, oauth_login
from .test_personal_server import StdioServer, _text, stdio_env  # noqa: F401 (stdio_env is a fixture)

INTERVALS = "https://intervals.icu/api/v1"


async def _personal_tool_names() -> set[str]:
    async with create_connected_server_and_client_session(mcp_server) as session:
        return {tool.name for tool in (await session.list_tools()).tools}


# --- tool list ---------------------------------------------------------------------

async def test_hosted_users_are_not_offered_setup_training_repo(login):
    hosted = {tool["name"] for tool in login(5101).list_tools()}
    personal = await _personal_tool_names()

    assert "setup_training_repo" not in hosted
    assert personal - hosted == {"setup_training_repo"}


async def test_stdio_offers_setup_training_repo(stdio_env):
    async with StdioServer(stdio_env) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}

    assert "setup_training_repo" in names


def test_hosted_user_with_a_cached_tool_list_is_still_refused(login, tmp_path):
    output = login(5102).call_tool("setup_training_repo", {"repo_path": str(tmp_path)})

    assert "can't be changed from an OAuth'd session" in output


# --- "training repository not configured" --------------------------------------------

def test_hosted_server_without_notes_storage_points_to_the_operator(server_env, strava, monkeypatch):
    # The operator deployed without TRAINING_REPO_PATH / TRAINING_REPO_URL.
    monkeypatch.delenv("TRAINING_REPO_PATH")
    monkeypatch.setattr(config, "training_repo_path", None)
    config.load()
    assert config.training_repo_path is None

    with TestClient(create_app(), base_url=PUBLIC_URL) as http:
        mcp = McpHttpClient(http, oauth_login(http, strava, 5103))
        mcp.initialize()
        outputs = [
            mcp.call_tool("read_goals"),
            mcp.call_tool("save_consultation_notes", {"notes": "Easy run"}),
            mcp.call_tool("list_consultation_notes"),
        ]

    for output in outputs:
        assert "This server's notes storage isn't set up" in output
        assert "contact the server's operator" in output
        assert "setup_training_repo" not in output


async def test_stdio_without_training_repo_points_to_setup(stdio_env):
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("save_goals", {"goals_text": "Sub-50 10k"}))

    assert "Training repository not configured" in output
    assert "setup_training_repo" in output


# --- start_consultation wording -------------------------------------------------------

def test_hosted_start_consultation_names_strava_and_no_wellness(login):
    output = login(5104).call_tool("start_consultation")

    assert "**Training Activities (Strava):**" in output
    assert "**Recovery Metrics: not connected.**" in output
    assert "intervals.icu wellness data" not in output


@pytest.mark.intervals_login_step
def test_hosted_start_consultation_with_intervals_connected(login, http_mock):
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(200, json={"id": "i1", "name": "Test"}))

    output = login(5105, intervals_api_key="synthetic-key").call_tool("start_consultation")

    assert "**Training Activities (Strava):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "not connected" not in output


async def test_stdio_start_consultation_names_intervals(stdio_env):
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("start_consultation", {}))

    assert "**Training Activities (intervals.icu):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "Strava" not in output


# --- guidance only references tools that exist ------------------------------------------

def test_hosted_guidance_only_references_offered_tools(login):
    mcp = login(5106)
    offered = {tool["name"] for tool in mcp.list_tools()}

    referenced = referenced_tool_names(mcp.call_tool("start_consultation"))
    assert {"get_activities", "save_goals"} <= referenced
    assert referenced <= offered, referenced - offered


async def test_stdio_guidance_only_references_offered_tools(stdio_env):
    async with StdioServer(stdio_env) as session:
        offered = {tool.name for tool in (await session.list_tools()).tools}
        guidance = _text(await session.call_tool("start_consultation", {}))

    referenced = referenced_tool_names(guidance)
    # No training repo configured: offers setup, and no goals/notes tools.
    assert {"get_activities", "setup_training_repo"} <= referenced
    assert "save_goals" not in referenced
    assert referenced <= offered, referenced - offered


# --- single entry point: start_consultation tells new from returning athletes ---------

def test_hosted_has_one_entry_point(login):
    names = {tool["name"] for tool in login(5107).list_tools()}

    assert "start_consultation" in names
    assert "discuss_goals" not in names


async def test_stdio_has_one_entry_point(stdio_env):
    async with StdioServer(stdio_env) as session:
        names = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool("discuss_goals", {})

    assert "start_consultation" in names
    assert "discuss_goals" not in names
    assert result.isError and "Unknown tool: discuss_goals" in result.content[0].text


def test_hosted_new_athlete_becomes_returning(login):
    mcp = login(5108)

    first = mcp.call_tool("start_consultation")
    assert "- **Saved goals:** none" in first
    assert "- **Consultation notes:** none" in first
    assert "NEW athlete** (Path A)" in first

    mcp.call_tool("save_goals", {"goals_text": "Half marathon under 1:50"})
    mcp.call_tool("save_consultation_notes", {"notes": "First session: goals set."})
    later = mcp.call_tool("start_consultation")

    assert "- **Saved goals:** yes" in later
    assert "- **Consultation notes:** 1, most recent" in later
    assert "RETURNING athlete** (Path B)" in later

    # Another athlete on the same server is still new.
    assert "NEW athlete** (Path A)" in login(5109).call_tool("start_consultation")


def test_hosted_start_consultation_without_notes_storage(server_env, strava, monkeypatch):
    monkeypatch.delenv("TRAINING_REPO_PATH")
    monkeypatch.setattr(config, "training_repo_path", None)
    config.load()

    with TestClient(create_app(), base_url=PUBLIC_URL) as http:
        mcp = McpHttpClient(http, oauth_login(http, strava, 5110))
        mcp.initialize()
        output = mcp.call_tool("start_consultation")

    assert "- **Notes storage:** not set up on this server" in output
    assert "contact the server's operator" in output
    assert "the server can't tell" in output
    assert "setup_training_repo" not in output


async def test_stdio_returning_athlete(stdio_env, training_repo, git_remote):
    push_files(git_remote, {
        "goals.md": "# Training Goals\nSub-40 10k\n",
        "notes/2026-05-01-07-00-00.md": "# Consultation Notes\nDate: synthetic\n\nTempo went well.\n",
    })

    async with StdioServer({**stdio_env, "TRAINING_REPO_PATH": str(training_repo)}) as session:
        output = _text(await session.call_tool("start_consultation", {}))

    assert "- **Activities source:** intervals.icu" in output
    assert "- **Saved goals:** yes" in output
    assert "- **Consultation notes:** 1, most recent 2026-05-01" in output
    assert "RETURNING athlete** (Path B)" in output


async def test_stdio_without_notes_storage_offers_setup(stdio_env):
    async with StdioServer(stdio_env) as session:
        output = _text(await session.call_tool("start_consultation", {}))

    assert "- **Notes storage:** not set up on this server" in output
    assert "**setup_training_repo**" in output
