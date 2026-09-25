"""Concurrent writes to the training repo, black box over HTTP.

Several devices (phone, desktop) write through one server at the same time,
and other clones (another server instance) push to the same remote in between.
No save may be lost, and the server's clone must keep working.
"""

from concurrent.futures import ThreadPoolExecutor

from tests.support import assert_clean_and_in_sync, push_files, remote_file, remote_files

ALICE = 1001


def alice_notes(git_remote):
    return [path for path in remote_files(git_remote) if path.startswith(f"notes/{ALICE}/")]


def test_concurrent_saves_through_the_server_all_land(login, git_remote, server_env):
    alice = login(ALICE)

    def save(device):
        return alice.call_tool("save_consultation_notes", {"notes": f"Saved from the {device}"})

    devices = ["phone", "desktop", "laptop", "tablet"]
    with ThreadPoolExecutor(max_workers=len(devices)) as pool:
        outputs = list(pool.map(save, devices))

    assert all("pushed to remote" in output for output in outputs), outputs
    notes = alice_notes(git_remote)
    assert len(notes) == len(devices)
    saved = " ".join(remote_file(git_remote, path) for path in notes)
    assert all(f"Saved from the {device}" in saved for device in devices)
    assert_clean_and_in_sync(server_env)


def test_saves_interleaved_with_another_server_instance(login, git_remote, server_env):
    alice = login(ALICE)

    alice.call_tool("save_consultation_notes", {"notes": "First, from this server"})
    push_files(git_remote, {
        f"notes/{ALICE}/2024-01-10-08-00-00.md": "# Consultation Notes\n\nFrom another server instance\n",
    })
    second = alice.call_tool("save_consultation_notes", {"notes": "Second, from this server"})
    goals = alice.call_tool("save_goals", {"goals_text": "Sub-3 marathon"})

    assert "pushed to remote" in second and "pushed to remote" in goals
    assert len(alice_notes(git_remote)) == 3
    listed = alice.call_tool("list_consultation_notes")
    assert "3 consultation note(s)" in listed
    assert "From another server instance" in listed
    assert "Sub-3 marathon" in remote_file(git_remote, f"goals/{ALICE}.md")
    assert_clean_and_in_sync(server_env)
