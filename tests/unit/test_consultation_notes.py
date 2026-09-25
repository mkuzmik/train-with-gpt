"""Unit tests for the consultation-notes tools (save/read/list/search).

Handlers run against a real git clone (`training_repo`) of a local bare
remote (`git_remote`); notes written "by another device" are pushed to the
remote first, so every read also exercises the real `git pull`.
"""

import re

import pytest

from tests.support import push_files, remote_file, remote_files, text_of
from train_with_gpt.config import config
from train_with_gpt.tools import (
    list_consultation_notes_handler,
    read_consultation_notes_handler,
    save_consultation_notes_handler,
    search_consultation_notes_handler,
)

NOT_CONFIGURED = "Training repository not configured"


def eight_daily_notes():
    return {f"notes/2024-01-{15 + i:02d}-08-00-00.md": f"Note {i + 1}\n" for i in range(8)}


# --- save ----------------------------------------------------------------------

async def test_save_writes_commits_and_pushes(training_repo, git_remote):
    notes = "Discussed marathon training plan.\n\nNext Steps:\n- Start with 40km/week"

    output = text_of(await save_consultation_notes_handler({"notes": notes}))

    assert output.startswith("✅ Consultation notes saved, committed and pushed to remote:")
    saved = sorted((training_repo / "notes").glob("*.md"))
    assert len(saved) == 1
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.md", saved[0].name)
    content = saved[0].read_text()
    assert content.startswith("# Consultation Notes\nDate: ")
    assert notes in content
    # ...and it landed in the remote, as its own commit
    assert f"notes/{saved[0].name}" in remote_files(git_remote)
    assert remote_file(git_remote, f"notes/{saved[0].name}") == content


@pytest.mark.xfail(strict=True, reason=(
    "Known issue: save_* doesn't pull before committing, so if the remote moved "
    "ahead (another device pushed) the push is rejected and the clone diverges."
))
async def test_save_after_remote_moved_ahead_still_pushes(training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-10-08-00-00.md": "From another device\n"})

    output = text_of(await save_consultation_notes_handler({"notes": "New note"}))

    assert "pushed to remote" in output


async def test_saved_note_can_be_read_back(training_repo):
    await save_consultation_notes_handler({"notes": "Increase mileage gradually, 40km/week"})

    output = text_of(await read_consultation_notes_handler({"all": True}))

    assert output.startswith("Found 1 consultation note(s)")
    assert "40km/week" in output


async def test_save_requires_notes(training_repo):
    assert text_of(await save_consultation_notes_handler({})) == "❌ Error: No notes provided"


async def test_save_without_repo_configured():
    output = text_of(await save_consultation_notes_handler({"notes": "Test note"}))
    assert NOT_CONFIGURED in output


async def test_save_when_repo_path_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "training_repo_path", str(tmp_path / "deleted"))

    output = text_of(await save_consultation_notes_handler({"notes": "x"}))

    assert "path no longer exists" in output


# --- read ----------------------------------------------------------------------

async def test_read_without_range_returns_guidance(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({}))

    assert "list_consultation_notes" in output
    assert "Note 1" not in output


async def test_read_all(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({"all": True}))

    assert "Found 8 consultation note(s)" in output
    for i in range(8):
        assert f"Note {i + 1}" in output
    # newest first
    assert output.index("Note 8") < output.index("Note 1")


async def test_read_picks_up_notes_pushed_elsewhere_and_says_so(training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-15-08-00-00.md": "From the other laptop\n"})

    output = text_of(await read_consultation_notes_handler({"all": True}))

    assert "From the other laptop" in output
    assert "notes/2024-01-15-08-00-00.md" in output  # git pull's summary is surfaced


async def test_read_since_until_range(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({"since": "2024-01-17", "until": "2024-01-19"}))

    assert "Found 3 consultation note(s)" in output
    for i in (2, 3, 4):
        assert f"Note {i + 1}" in output
    for i in (0, 1, 5, 6, 7):
        assert f"Note {i + 1}" not in output


async def test_read_open_ended_since(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({"since": "2024-01-21"}))

    assert "Found 2 consultation note(s)" in output


async def test_read_note_date(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({"note_date": "2024-01-16"}))

    assert "Found 1 consultation note(s)" in output
    assert "Note 2" in output
    assert "Note 1\n" not in output and "Note 3" not in output


async def test_read_range_without_matches(training_repo, git_remote):
    push_files(git_remote, eight_daily_notes())

    output = text_of(await read_consultation_notes_handler({"since": "2025-01-01"}))

    assert output == "ℹ️ No consultation notes found for that date range."


async def test_read_with_no_notes_yet(training_repo):
    output = text_of(await read_consultation_notes_handler({"all": True}))
    assert "No consultation notes saved yet" in output


async def test_read_without_repo_configured():
    assert NOT_CONFIGURED in text_of(await read_consultation_notes_handler({"all": True}))


# --- list ----------------------------------------------------------------------

async def test_list_is_a_dated_index_of_headlines(training_repo, git_remote):
    push_files(git_remote, {
        "notes/2024-01-15-08-00-00.md": (
            "# Consultation Notes\nDate: 2024-01-15 08:00:00\n\n"
            "Discussed marathon training plan and mileage buildup.\n"
        ),
        "notes/2024-01-20-08-00-00.md": (
            "# Consultation Notes\nDate: 2024-01-20 08:00:00\n\n"
            "========================================\nHEADLINE\n========================================\n"
            "Follow-up check-in, mileage on track.\n"
        ),
    })

    output = text_of(await list_consultation_notes_handler({}))

    assert "2 consultation note(s), spanning 2024-01-15 to 2024-01-20" in output
    assert "2024-01-15 — Discussed marathon training plan and mileage buildup." in output
    assert "2024-01-20 — Follow-up check-in, mileage on track." in output
    assert output.index("2024-01-20 —") < output.index("2024-01-15 —")


async def test_list_with_no_notes_yet(training_repo):
    assert "No consultation notes saved yet" in text_of(await list_consultation_notes_handler({}))


async def test_list_without_repo_configured():
    assert NOT_CONFIGURED in text_of(await list_consultation_notes_handler({}))


# --- search --------------------------------------------------------------------

async def test_search_finds_match_with_context(training_repo, git_remote):
    push_files(git_remote, {
        "notes/2024-01-15-08-00-00.md": "Discussed marathon training plan.\n\nMentioned some calf tightness after the long run.\n",
        "notes/2024-01-20-08-00-00.md": "Follow-up check-in, mileage on track. No issues to report.\n",
    })

    output = text_of(await search_consultation_notes_handler({"query": "calf"}))

    assert '1 match(es) for "calf" across 1 note(s)' in output
    assert "**2024-01-15**\nDiscussed marathon training plan.\nMentioned some calf tightness after the long run." in output
    assert "**2024-01-20**" not in output


async def test_search_across_notes_newest_first(training_repo, git_remote):
    push_files(git_remote, {
        "notes/2024-01-15-08-00-00.md": "Race goal: sub-4 marathon in spring.\n",
        "notes/2024-02-10-08-00-00.md": "Revisited the race goal, still on track.\n",
    })

    output = text_of(await search_consultation_notes_handler({"query": "race goal"}))

    assert "2 match(es)" in output
    assert "across 2 note(s)" in output
    assert output.index("**2024-02-10**") < output.index("**2024-01-15**")


async def test_search_merges_nearby_matches_into_one_snippet(training_repo, git_remote):
    lines = [f"line {i}" for i in range(20)]
    lines[5] = "knee sore"
    lines[7] = "knee better"
    lines[18] = "knee fine"
    push_files(git_remote, {"notes/2024-01-15-08-00-00.md": "\n".join(lines)})

    output = text_of(await search_consultation_notes_handler({"query": "knee"}))

    assert "2 match(es)" in output
    assert "line 3\nline 4\nknee sore\nline 6\nknee better\nline 8\nline 9" in output


async def test_search_is_case_insensitive(training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-15-08-00-00.md": "Achilles felt tight during warmup.\n"})

    output = text_of(await search_consultation_notes_handler({"query": "ACHILLES"}))

    assert "1 match(es)" in output


async def test_search_without_matches(training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-15-08-00-00.md": "Easy week, nothing notable.\n"})

    output = text_of(await search_consultation_notes_handler({"query": "hamstring"}))

    assert "No matches" in output
    assert "list_consultation_notes" in output


@pytest.mark.parametrize("query", ["", "   ", None])
async def test_search_requires_query(training_repo, query):
    output = text_of(await search_consultation_notes_handler({"query": query}))
    assert output == "❌ Error: 'query' is required."


async def test_search_with_no_notes_yet(training_repo):
    assert "No consultation notes saved yet" in text_of(await search_consultation_notes_handler({"query": "x"}))


async def test_search_without_repo_configured():
    assert NOT_CONFIGURED in text_of(await search_consultation_notes_handler({"query": "calf"}))
