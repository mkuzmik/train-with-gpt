"""Unit tests for the guidance tools: start_consultation (the single entry point) and get_current_date."""

from datetime import datetime

import pytest

from tests.support import as_oauth_user, push_files, referenced_tool_names, text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.server import list_tools
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import get_current_date_handler, start_consultation_handler


def _strava():
    return StravaClient(access_token="a", refresh_token="r", expires_at=0)


def _intervals():
    return IntervalsClient(api_key="synthetic-key")


# The (data, wellness) client pairs server.py resolves, per transport.
STDIO = pytest.param(_intervals, _intervals, id="stdio")
HOSTED = pytest.param(_strava, _strava, id="hosted")
HOSTED_WITH_INTERVALS = pytest.param(_strava, _intervals, id="hosted+intervals")


async def _registered_tool_names() -> set[str]:
    return {tool.name for tool in await list_tools()}


async def test_start_consultation_points_at_the_context_tools(training_repo):
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))

    assert output.startswith("🏃 Training Consultation")
    for tool in ("get_current_date", "read_goals", "list_consultation_notes", "read_consultation_notes",
                 "search_consultation_notes", "get_activities", "save_goals", "save_consultation_notes"):
        assert tool in output
    assert "coach" in output.lower()
    assert "{data_sources}" not in output


async def test_start_consultation_carries_both_paths_and_the_goal_setting_guide():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))

    assert "## Step 1: Choose the path" in output
    assert "## Path A: Onboarding a New Athlete" in output
    assert "## Path B: Consultation with a Returning Athlete" in output
    assert "## Goal-Setting Conversation" in output
    assert "ASK ONE QUESTION AT A TIME" in output
    assert "You decide which path fits" in output
    assert "ask ONE short question rather than guessing" in output


async def test_start_consultation_on_stdio_names_intervals_for_everything():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))

    assert "**Training Activities (intervals.icu):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "**get_hrv_data**" in output
    assert "Strava" not in output


async def test_start_consultation_for_a_hosted_user_names_strava_and_no_wellness():
    output = text_of(await start_consultation_handler({}, _strava(), _strava()))

    assert "**Training Activities (Strava):**" in output
    assert "Training Activities (intervals.icu)" not in output
    assert "intervals.icu wellness data" not in output
    assert "**Recovery Metrics: not connected.**" in output
    assert "**get_hrv_data**" not in output
    assert "Consider recovery metrics alongside training data" not in output


async def test_start_consultation_for_a_hosted_user_with_intervals_connected():
    output = text_of(await start_consultation_handler({}, _strava(), _intervals()))

    assert "**Training Activities (Strava):**" in output
    assert "**Recovery Metrics (intervals.icu wellness data):**" in output
    assert "not connected" not in output


@pytest.mark.parametrize("data, wellness", [STDIO, HOSTED, HOSTED_WITH_INTERVALS])
async def test_start_consultation_only_references_registered_tools(data, wellness, training_repo):
    output = text_of(await start_consultation_handler({}, data(), wellness()))

    referenced = referenced_tool_names(output)
    assert {"get_activities", "read_goals"} <= referenced
    assert referenced <= await _registered_tool_names()


async def test_discuss_goals_is_gone():
    assert "discuss_goals" not in await _registered_tool_names()
    with as_oauth_user("4242"):
        assert "discuss_goals" not in await _registered_tool_names()

    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))
    assert "discuss_goals" not in output


# --- facts about the caller ----------------------------------------------------------

NOTE = "# Consultation Notes\nDate: synthetic\n\nEasy week.\n"


async def _start(data=_intervals, wellness=_intervals) -> str:
    return text_of(await start_consultation_handler({}, data(), wellness()))


async def test_new_athlete_has_no_goals_and_no_notes(training_repo):
    output = await _start()

    assert "- **Notes storage:** set up" in output
    assert "- **Saved goals:** none" in output
    assert "- **Consultation notes:** none" in output
    assert "this looks like a NEW athlete** (Path A)" in output


async def test_returning_athlete_sees_goals_and_note_count(training_repo, git_remote):
    # Written from another device: start_consultation syncs before looking.
    push_files(git_remote, {
        "goals.md": "# Training Goals\nSub-50 10k\n",
        "notes/2026-01-05-07-00-00.md": NOTE,
        "notes/2026-02-10-18-30-00.md": NOTE,
    })

    output = await _start()

    assert "- **Saved goals:** yes" in output
    assert "- **Consultation notes:** 2, most recent 2026-02-10" in output
    assert "this is a RETURNING athlete** (Path B)" in output
    assert "NEW athlete" not in output


async def test_notes_without_goals_is_returning_and_offers_goal_setting(training_repo, git_remote):
    push_files(git_remote, {"notes/2026-03-01-09-00-00.md": NOTE})

    output = await _start()

    assert "- **Saved goals:** none" in output
    assert "- **Consultation notes:** 1, most recent 2026-03-01" in output
    assert "RETURNING athlete without goals" in output
    assert "offer the goal-setting conversation" in output


async def test_goals_without_notes_is_flagged_as_ambiguous(training_repo, git_remote):
    push_files(git_remote, {"goals.md": "# Training Goals\nFirst marathon\n"})

    output = await _start()

    assert "- **Saved goals:** yes" in output
    assert "- **Consultation notes:** none" in output
    assert "ambiguous" in output
    assert "ask the athlete" in output


async def test_facts_are_per_oauth_user(training_repo, git_remote):
    push_files(git_remote, {
        "goals/1001.md": "# Training Goals\nTrail 50k\n",
        "notes/1001/2026-04-01-08-00-00.md": NOTE,
        "goals.md": "# Training Goals\npersonal user\n",
        "notes/2026-04-02-08-00-00.md": NOTE,
    })

    with as_oauth_user("1001"):
        returning = await _start(_strava, _strava)
    with as_oauth_user("1002"):
        new = await _start(_strava, _strava)

    assert "- **Consultation notes:** 1, most recent 2026-04-01" in returning
    assert "RETURNING athlete** (Path B)" in returning
    assert "- **Saved goals:** none" in new and "- **Consultation notes:** none" in new
    assert "NEW athlete" in new


async def test_stdio_without_notes_storage_offers_setup():
    output = await _start()

    assert "- **Notes storage:** not set up on this server" in output
    assert "**setup_training_repo**" in output
    assert "the server can't tell" in output
    assert "- **Saved goals:**" not in output


async def test_hosted_without_notes_storage_points_to_the_operator():
    with as_oauth_user("1003"):
        output = await _start(_strava, _strava)

    assert "- **Notes storage:** not set up on this server" in output
    assert "contact the server's operator" in output
    assert "setup_training_repo" not in output


async def test_missing_repo_path_degrades_gracefully(training_repo, monkeypatch):
    from train_with_gpt.config import config
    monkeypatch.setattr(config, "training_repo_path", str(training_repo / "gone"))

    output = await _start()

    assert "- **Notes storage:** unavailable (Training repository path no longer exists" in output
    assert "the server can't tell" in output
    assert "## Path A" in output and "## Path B" in output


async def test_a_directory_that_is_not_a_git_repo_is_not_reported_as_set_up(tmp_path, monkeypatch):
    from train_with_gpt.config import config
    plain = tmp_path / "plain-dir"
    (plain / "notes").mkdir(parents=True)
    (plain / "goals.md").write_text("# Training Goals\nSynthetic\n")
    monkeypatch.setattr(config, "training_repo_path", str(plain))

    output = await _start()

    assert f"- **Notes storage:** unavailable (Not a git repository: {plain})" in output
    assert "- **Saved goals:**" not in output
    assert "the server can't tell" in output


async def test_storage_error_degrades_gracefully(training_repo, monkeypatch):
    from train_with_gpt.tools import start_consultation as module

    def broken(*args, **kwargs):
        raise OSError("disk on fire")
    monkeypatch.setattr(module, "git_pull_and_read", broken)

    output = await _start()

    assert "- **Notes storage:** unavailable (disk on fire)" in output
    assert "the server can't tell" in output


@pytest.mark.parametrize("data, wellness, activities, recovery", [
    pytest.param(_intervals, _intervals, "intervals.icu", "connected (intervals.icu)", id="stdio"),
    pytest.param(_strava, _strava, "Strava", "not connected", id="hosted"),
    pytest.param(_strava, _intervals, "Strava", "connected (intervals.icu)", id="hosted+intervals"),
])
async def test_facts_name_the_connected_sources(data, wellness, activities, recovery):
    output = await _start(data, wellness)

    assert f"- **Activities source:** {activities}" in output
    assert f"- **Recovery data (sleep, HRV, resting HR):** {recovery}" in output


def _formatted(moment: datetime) -> str:
    return moment.strftime(f"%A, %B {moment.day}, %Y (%Y-%m-%d)")


async def test_get_current_date_is_today():
    before = datetime.now()
    output = text_of(await get_current_date_handler({}))
    after = datetime.now()

    # (either side of the call, in case it straddled midnight)
    assert any(f"📅 Current date: {_formatted(moment)}\n" in output for moment in (before, after))


# --- no notes storage: no goals/notes tool is suggested ------------------------------

STORAGE_TOOLS = {"read_goals", "save_goals", "list_consultation_notes", "read_consultation_notes",
                 "search_consultation_notes", "save_consultation_notes"}


async def test_without_storage_the_guidance_never_suggests_goals_or_notes_tools():
    stdio = await _start()
    with as_oauth_user("1004"):
        hosted = await _start(_strava, _strava)

    for output in (stdio, hosted):
        assert not referenced_tool_names(output) & STORAGE_TOOLS, referenced_tool_names(output) & STORAGE_TOOLS
        assert "(no notes storage)" in output
        assert "can't be saved in this chat" in output
        assert "get_activities" in referenced_tool_names(output)


async def test_with_storage_the_guidance_uses_the_goals_and_notes_tools(training_repo):
    assert STORAGE_TOOLS <= referenced_tool_names(await _start())


# --- the sync summary never leaks other users' files ----------------------------------

async def test_hosted_facts_do_not_list_other_users_files_pulled_by_the_sync(training_repo, git_remote):
    push_files(git_remote, {
        "goals/2002.md": "# Training Goals\nsomeone else\n",
        "notes/2002/2026-06-01-06-00-00.md": NOTE,
    })

    with as_oauth_user("2001"):
        output = await _start(_strava, _strava)

    assert "2002" not in output
    assert "Pulled updates" not in output
    assert "NEW athlete" in output


def test_sync_fact_keeps_warnings_but_not_the_update_list():
    from train_with_gpt.tools.start_consultation import _sync_fact

    note = "⚠️ 1 local commit(s) conflicted with newer changes.\n\nPulled updates from the remote: goals/2002.md"

    assert _sync_fact(None, hosted=True) is None
    assert _sync_fact("Pulled updates from the remote: goals/2002.md", hosted=False) is None
    assert _sync_fact(note, hosted=False) == "⚠️ 1 local commit(s) conflicted with newer changes."
    hosted = _sync_fact(note, hosted=True)
    assert "couldn't be fully synced" in hosted and "2002" not in hosted
