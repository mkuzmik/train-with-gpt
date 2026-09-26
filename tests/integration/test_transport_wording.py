"""What each transport offers and says, black box: the hosted (OAuth) HTTP
server vs the personal stdio server.

Hosted users get Strava activities, no setup_training_repo, and an "ask the
operator" message when the server has no notes storage; the stdio user gets
intervals.icu, setup_training_repo, and is told to run it.
"""

import pytest
from httpx import Response
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.testclient import TestClient

from tests.support import referenced_tool_names
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

    for tool in ("start_consultation", "discuss_goals"):
        referenced = referenced_tool_names(mcp.call_tool(tool))
        assert "get_activities" in referenced
        assert referenced <= offered, (tool, referenced - offered)


async def test_stdio_guidance_only_references_offered_tools(stdio_env):
    async with StdioServer(stdio_env) as session:
        offered = {tool.name for tool in (await session.list_tools()).tools}
        guidance = {
            tool: _text(await session.call_tool(tool, {})) for tool in ("start_consultation", "discuss_goals")
        }

    for tool, text in guidance.items():
        referenced = referenced_tool_names(text)
        assert "get_activities" in referenced
        assert referenced <= offered, (tool, referenced - offered)
