"""Per-user isolation of notes and goals on the multi-user OAuth path.

Each authenticated subject must only ever see their own `notes/<user_id>/`
and `goals/<user_id>.md`, never another user's.
"""

import contextlib
from unittest.mock import patch

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from train_with_gpt.server import call_tool

ALICE = "1001"
BOB = "2002"


@contextlib.contextmanager
def as_user(user_id):
    """Run tool calls as if an OAuth'd request for `user_id` were in flight."""
    token = AccessToken(token=f"tok-{user_id}", client_id="claude", scopes=[], subject=user_id)
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        yield
    finally:
        auth_context_var.reset(reset)


def _text(result):
    assert len(result) == 1
    return result[0].text


@pytest.mark.asyncio
async def test_goals_are_isolated_per_user(training_repo):
    with patch("subprocess.run"):
        with as_user(ALICE):
            await call_tool("save_goals", {"goals_text": "Alice: sub-3 marathon"})
        with as_user(BOB):
            await call_tool("save_goals", {"goals_text": "Bob: first century ride"})

        assert (training_repo / "goals" / f"{ALICE}.md").read_text().count("Alice") == 1
        assert "Bob" not in (training_repo / "goals" / f"{ALICE}.md").read_text()
        assert not (training_repo / "goals.md").exists()

        with as_user(ALICE):
            alice_goals = _text(await call_tool("read_goals", {}))
        with as_user(BOB):
            bob_goals = _text(await call_tool("read_goals", {}))

    assert "sub-3 marathon" in alice_goals and "century" not in alice_goals
    assert "century" in bob_goals and "sub-3" not in bob_goals


@pytest.mark.asyncio
async def test_goals_read_does_not_fall_back_to_another_user(training_repo):
    with patch("subprocess.run"):
        with as_user(ALICE):
            await call_tool("save_goals", {"goals_text": "Alice secret goal"})
        with as_user(BOB):
            bob_goals = _text(await call_tool("read_goals", {}))

    assert "Alice secret goal" not in bob_goals


@pytest.mark.asyncio
async def test_notes_are_isolated_per_user(training_repo):
    with patch("subprocess.run"):
        with as_user(ALICE):
            await call_tool("save_consultation_notes", {"notes": "Alice has calf tightness"})
        with as_user(BOB):
            await call_tool("save_consultation_notes", {"notes": "Bob has a sore knee"})

        alice_files = list((training_repo / "notes" / ALICE).glob("*.md"))
        bob_files = list((training_repo / "notes" / BOB).glob("*.md"))
        assert len(alice_files) == 1 and "calf" in alice_files[0].read_text()
        assert len(bob_files) == 1 and "knee" in bob_files[0].read_text()

        with as_user(ALICE):
            read = _text(await call_tool("read_consultation_notes", {"all": True}))
            listed = _text(await call_tool("list_consultation_notes", {}))
            own = _text(await call_tool("search_consultation_notes", {"query": "calf"}))
            other = _text(await call_tool("search_consultation_notes", {"query": "knee"}))

    assert "calf" in read and "knee" not in read
    assert "calf" in listed and "knee" not in listed
    assert "calf tightness" in own
    assert "sore knee" not in other


@pytest.mark.asyncio
async def test_personal_path_does_not_see_user_notes(training_repo):
    """No OAuth subject (stdio/personal) reads root-level notes only."""
    with patch("subprocess.run"):
        with as_user(ALICE):
            await call_tool("save_consultation_notes", {"notes": "Alice private note"})
        result = _text(await call_tool("search_consultation_notes", {"query": "private"}))

    assert "Alice private note" not in result
