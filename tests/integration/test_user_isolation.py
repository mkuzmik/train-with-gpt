"""Per-user isolation of notes and goals, black box over HTTP.

Two real OAuth logins (Alice and Bob) against one server and one shared
training repo: each must only ever see their own `notes/<user_id>/` and
`goals/<user_id>.md`, and the personal (no-OAuth) path sees neither.
"""

from mcp.shared.memory import create_connected_server_and_client_session

from tests.support import remote_file, remote_files
from train_with_gpt.server import app as mcp_server

ALICE = 1001
BOB = 2002


def test_goals_are_isolated_per_user(login, git_remote):
    alice, bob = login(ALICE), login(BOB)

    alice.call_tool("save_goals", {"goals_text": "Alice: sub-3 marathon"})
    bob.call_tool("save_goals", {"goals_text": "Bob: first century ride"})

    files = remote_files(git_remote)
    assert f"goals/{ALICE}.md" in files and f"goals/{BOB}.md" in files
    assert "goals.md" not in files
    assert "Bob" not in remote_file(git_remote, f"goals/{ALICE}.md")

    alice_goals = alice.call_tool("read_goals")
    bob_goals = bob.call_tool("read_goals")
    assert "sub-3 marathon" in alice_goals and "century" not in alice_goals
    assert "century" in bob_goals and "sub-3" not in bob_goals


def test_goals_read_does_not_fall_back_to_another_user(login):
    alice, bob = login(ALICE), login(BOB)

    alice.call_tool("save_goals", {"goals_text": "Alice secret goal"})

    bob_goals = bob.call_tool("read_goals")
    assert "Alice secret goal" not in bob_goals
    assert "No goals saved yet" in bob_goals


def test_notes_are_isolated_per_user(login, git_remote):
    alice, bob = login(ALICE), login(BOB)

    alice.call_tool("save_consultation_notes", {"notes": "Alice has calf tightness"})
    bob.call_tool("save_consultation_notes", {"notes": "Bob has a sore knee"})

    notes = [path for path in remote_files(git_remote) if path.startswith("notes/")]
    assert len(notes) == 2
    alice_note = next(path for path in notes if path.startswith(f"notes/{ALICE}/"))
    bob_note = next(path for path in notes if path.startswith(f"notes/{BOB}/"))
    assert "calf" in remote_file(git_remote, alice_note)
    assert "knee" in remote_file(git_remote, bob_note)

    read = alice.call_tool("read_consultation_notes", {"all": True})
    listed = alice.call_tool("list_consultation_notes")
    own = alice.call_tool("search_consultation_notes", {"query": "calf"})
    other = alice.call_tool("search_consultation_notes", {"query": "knee"})

    assert "calf" in read and "knee" not in read
    assert "calf" in listed and "knee" not in listed
    assert "calf tightness" in own
    assert "sore knee" not in other


async def test_personal_path_does_not_see_user_notes(login):
    """No OAuth subject (stdio/personal path) reads root-level notes only."""
    login(ALICE).call_tool("save_consultation_notes", {"notes": "Alice private note"})

    async with create_connected_server_and_client_session(mcp_server) as personal:
        result = await personal.call_tool("search_consultation_notes", {"query": "private"})

    assert "Alice private note" not in result.content[0].text
