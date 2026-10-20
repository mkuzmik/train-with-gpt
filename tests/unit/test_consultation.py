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
    for tool in ("read_goals", "list_consultation_notes", "read_consultation_notes",
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
    assert "get_resting_heart_rate or get_weight_data" in output
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


async def test_saying_new_never_onboards_an_athlete_with_saved_history(training_repo):
    output = await _start()
    rules = output.split("## Step 1: Choose the path")[1].split("**Here")[0]
    path_a = output.split("## Path A")[1].split("## Goal-Setting")[0]

    # Path A is chosen by the facts; the athlete's words can't override saved history.
    assert "Path A - New athlete (onboarding):** only when there are no saved goals, no profile and\n  no notes" in rules
    assert "or the athlete says they're new" not in rules
    assert "explicitly confirm" in rules
    assert "Only for an athlete with no saved goals, profile or notes" in path_a


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


async def test_stdio_without_an_intervals_key_is_not_reported_as_connected(monkeypatch):
    from train_with_gpt.config import config
    monkeypatch.setattr(config, "intervals_api_key", None)

    output = text_of(await start_consultation_handler({}, IntervalsClient(), IntervalsClient()))

    assert "connected (intervals.icu)" not in output
    assert "INTERVALS_API_KEY" in output
    assert "no API key is configured" in output
    assert "the sleep/HRV/resting-HR/weight tools will fail" in output
    # The data-sources guidance doesn't advertise the tools that would fail...
    assert "**Recovery Metrics (intervals.icu wellness data):**" not in output
    assert "**Training Activities (intervals.icu):**" not in output
    # ...and tells the model to skip the paths' activity steps.
    assert "skip every get_activities" in output
    assert "get_resting_heart_rate and get_weight_data step" in output


# The intervals.icu page after the Strava login only exists when the server
# can encrypt the key (TOKEN_ENCRYPTION_KEY); without it, reconnecting can't help.
async def test_hosted_without_the_intervals_step_does_not_suggest_reconnecting(monkeypatch):
    from train_with_gpt.config import config
    monkeypatch.setattr(config, "token_encryption_key", None)

    output = await _start(_strava, _strava)

    assert "**Recovery Metrics: not connected.**" in output
    assert "reconnect" not in output
    assert "operator" in output


async def test_hosted_with_the_intervals_step_explains_how_to_connect(monkeypatch):
    from cryptography.fernet import Fernet
    from train_with_gpt.config import config
    monkeypatch.setattr(config, "token_encryption_key", Fernet.generate_key().decode())

    output = await _start(_strava, _strava)

    assert "disconnect and reconnect this connector" in output


# Hosted users share the server's notes repo: a storage error's detail (server
# paths, git output naming other users' files) stays in the server log.
@pytest.mark.parametrize("breakage", ["missing", "not_git", "sync_error"])
async def test_hosted_storage_errors_do_not_show_server_details(training_repo, tmp_path, monkeypatch, breakage):
    from train_with_gpt.config import config
    from train_with_gpt.helpers import GitSyncError
    from train_with_gpt.tools import start_consultation as module

    if breakage == "missing":
        secret = str(training_repo / "gone")
        monkeypatch.setattr(config, "training_repo_path", secret)
    elif breakage == "not_git":
        secret = str(tmp_path / "plain-dir")
        (tmp_path / "plain-dir").mkdir()
        monkeypatch.setattr(config, "training_repo_path", secret)
    else:
        secret = "notes/2002/2026-06-01-06-00-00.md"

        def broken(*args, **kwargs):
            raise GitSyncError(f"rebase failed on {secret}")
        monkeypatch.setattr(module, "git_pull_and_read", broken)

    with as_oauth_user("2001"):
        output = await _start(_strava, _strava)

    assert secret not in output
    assert "- **Notes storage:** unavailable" in output
    assert "contact the server's operator" in output
    assert "the server can't tell" in output


@pytest.mark.parametrize("data, wellness, activities, recovery", [
    pytest.param(_intervals, _intervals, "intervals.icu", "connected (intervals.icu)", id="stdio"),
    pytest.param(_strava, _strava, "Strava", "not connected", id="hosted"),
    pytest.param(_strava, _intervals, "Strava", "connected (intervals.icu)", id="hosted+intervals"),
])
async def test_facts_name_the_connected_sources(data, wellness, activities, recovery):
    output = await _start(data, wellness)

    assert f"- **Activities source:** {activities}" in output
    assert f"- **Recovery data (sleep, HRV, resting HR, body weight):** {recovery}" in output


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
                 "search_consultation_notes", "save_consultation_notes",
                 "build_athlete_profile", "save_athlete_profile"}


async def test_without_storage_the_guidance_never_suggests_goals_or_notes_tools():
    stdio = await _start()
    with as_oauth_user("1004"):
        hosted = await _start(_strava, _strava)

    for output in (stdio, hosted):
        storage_tools = STORAGE_TOOLS | {"read_athlete_profile"}
        assert not referenced_tool_names(output) & storage_tools, referenced_tool_names(output) & storage_tools
        assert "- **Athlete profile:**" not in output
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


# --- a failed sync makes the facts uncertain -------------------------------------------

async def test_a_failed_sync_does_not_confidently_label_the_athlete(training_repo, tmp_path):
    from tests.support import git
    # The remote is unreachable: the local clone may be missing goals/notes saved elsewhere.
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    output = await _start()

    assert "- **Saved goals:** none" in output  # still shown, from the local copy
    assert "NEW athlete** (Path A)" not in output
    assert "couldn't be synced" in output
    assert "ask ONE question" in output


async def test_a_successful_sync_with_a_warning_still_labels_the_athlete(training_repo, monkeypatch):
    from train_with_gpt.tools import start_consultation as module
    real = module.git_pull_and_read

    def with_warning(repo_path, read):
        _, value = real(repo_path, read)
        return "⚠️ 1 local commit(s) conflicted with newer changes on the remote.", value
    monkeypatch.setattr(module, "git_pull_and_read", with_warning)

    assert "NEW athlete** (Path A)" in await _start()


# --- athlete profile ------------------------------------------------------------------

PROFILE = "# Athlete profile\nSaved: synthetic\n\n## Background\n- Made-up runner since 2019.\n\n## Constraints\n- Rests on Wednesdays.\n"


async def test_a_saved_profile_is_included_in_full(training_repo, git_remote):
    push_files(git_remote, {
        "athlete-profile.md": PROFILE,
        "goals.md": "# Training Goals\nSub-50 10k\n",
        "notes/2026-01-05-07-00-00.md": NOTE,
    })

    output = await _start()

    assert "- **Athlete profile:** yes (full text below)" in output
    assert "## Athlete profile (saved)" in output
    assert PROFILE.strip() in output
    assert "use it as the baseline" in output
    assert "save_athlete_profile" in referenced_tool_names(output)
    # the profile comes before the guidance, right after the facts
    assert output.index("Made-up runner") < output.index("## Step 1: Choose the path")
    assert "No athlete profile yet" not in output


async def test_new_athlete_has_no_profile_and_onboarding_builds_it(training_repo):
    output = await _start()
    path_a = output.split("## Path A")[1].split("## Goal-Setting")[0]

    assert "- **Athlete profile:** none" in output
    assert "## Athlete profile (saved)" not in output
    assert "NEW athlete** (Path A)" in output
    assert "No athlete profile yet" not in output  # the build is part of onboarding
    assert "**build_athlete_profile**" in path_a
    assert path_a.index("build_athlete_profile") < path_a.index("save_goals")


async def test_returning_athlete_without_a_profile_is_offered_one(training_repo, git_remote):
    push_files(git_remote, {
        "goals.md": "# Training Goals\nSub-50 10k\n",
        "notes/2026-01-05-07-00-00.md": NOTE,
    })

    output = await _start()

    assert "- **Athlete profile:** none" in output
    assert "RETURNING athlete** (Path B)" in output
    assert "**No athlete profile yet:**" in output
    assert "offer to build one (**build_athlete_profile**). Offer, don't force it" in output


async def test_a_profile_alone_is_an_unfinished_onboarding_not_a_new_athlete(training_repo, git_remote):
    push_files(git_remote, {"athlete-profile.md": PROFILE})

    output = await _start()

    assert "- **Saved goals:** none" in output
    assert "- **Athlete profile:** yes" in output
    assert "NEW athlete" not in output
    assert "onboarding was probably cut short" in output
    assert "goal-setting conversation" in output


async def test_the_profile_is_per_oauth_user(training_repo, git_remote):
    push_files(git_remote, {
        "athlete/1001.md": PROFILE,
        "athlete-profile.md": "# Athlete profile\n\n## Background\n- Personal-path athlete.\n",
    })

    with as_oauth_user("1001"):
        own = await _start(_strava, _strava)
    with as_oauth_user("1002"):
        other = await _start(_strava, _strava)

    assert "Made-up runner" in own and "Personal-path athlete" not in own
    assert "- **Athlete profile:** none" in other
    assert "Made-up runner" not in other and "Personal-path athlete" not in other
    assert "1001" not in other


async def test_goal_setting_keeps_athlete_facts_out_of_the_goals(training_repo):
    output = await _start()
    goal_setting = output.split("## Goal-Setting Conversation")[1].split("## Path B")[0]

    assert "belong in the athlete profile, not the goals" in goal_setting
    assert "shin splints" not in goal_setting
    summary = goal_setting.split("**Then** write")[1]
    assert "current best" not in summary
    assert "gap to close" not in summary


async def test_save_goals_description_sends_athlete_facts_to_the_profile():
    tool = next(tool for tool in await list_tools() if tool.name == "save_goals")

    assert "save_athlete_profile" in tool.description
    assert "current state" not in tool.inputSchema["properties"]["goals_text"]["description"]


async def test_a_failed_sync_qualifies_the_included_profile(training_repo, git_remote, tmp_path):
    from tests.support import git
    push_files(git_remote, {"athlete-profile.md": PROFILE})
    git(training_repo, "pull", "--quiet")
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    output = await _start()

    assert "Made-up runner" in output  # still shown, from the local copy
    assert "the profile, goals and notes above) come from a possibly out-of-date copy" in output
    assert "Don't build or save an athlete profile in this chat" in output


async def test_a_failed_sync_never_offers_to_build_a_profile(training_repo, git_remote, tmp_path):
    from tests.support import git
    push_files(git_remote, {"goals.md": "# Training Goals\nSub-50 10k\n", "notes/2026-01-05-07-00-00.md": NOTE})
    git(training_repo, "pull", "--quiet")
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    output = await _start()

    assert "- **Athlete profile:** none" in output
    assert "No athlete profile yet" not in output
    assert "Don't build or save an athlete profile in this chat" in output


# --- saved context: goals and notes are included, within a budget ----------------------

def _note(day: str, body: str) -> str:
    return f"# Consultation Notes\nDate: {day}\n\n{body}\n"


def _days_ago(days: int) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days)).isoformat()


async def test_today_is_in_the_facts(training_repo):
    before = datetime.now()
    output = await _start()
    after = datetime.now()

    assert any(f"- **Today:** {_formatted(moment)}, by the server's clock" in output for moment in (before, after))


async def test_today_is_in_the_facts_without_storage_or_an_intervals_key(monkeypatch):
    from train_with_gpt.config import config
    monkeypatch.setattr(config, "intervals_api_key", None)

    output = text_of(await start_consultation_handler({}, IntervalsClient(), IntervalsClient()))

    assert "- **Today:** " in output


async def test_saved_goals_are_included_in_full(training_repo, git_remote):
    push_files(git_remote, {"goals.md": "# Training Goals\nSynthetic 10k under 45 minutes in spring.\n"})

    output = await _start()

    assert "- **Saved goals:** yes (below)" in output
    assert "## Goals (saved)" in output
    assert "Synthetic 10k under 45 minutes in spring." in output
    assert output.index("Synthetic 10k") < output.index("## Step 1: Choose the path")
    assert "the goals are cut here" not in output


async def test_long_goals_are_cut_with_a_marker(training_repo, git_remote):
    from train_with_gpt.tools.start_consultation import GOALS_BUDGET
    push_files(git_remote, {"goals.md": "# Training Goals\n" + "Synthetic goal line.\n" * 400})

    output = await _start()
    goals = output.split("----- goals -----")[1].split("----- end of goals -----")[0]

    assert len(goals) < GOALS_BUDGET + 200
    assert "the goals are cut here to keep this short: read them in full with **read_goals**" in goals


async def test_recent_notes_are_included_in_full_newest_first(training_repo, git_remote):
    push_files(git_remote, {
        f"notes/{_days_ago(9)}-07-00-00.md": _note("a", "Oldest synthetic note: easy week."),
        f"notes/{_days_ago(5)}-07-00-00.md": _note("b", "Middle synthetic note: calf niggle, skip hills."),
        f"notes/{_days_ago(1)}-07-00-00.md": _note("c", "Newest synthetic note: tempo went well."),
    })

    output = await _start()

    assert f"- **Consultation notes:** 3, most recent {_days_ago(1)} (the latest 3 in full below" in output
    assert "## Recent consultation notes (the latest 3 of 3, newest first)" in output
    newest, middle, oldest = (output.index(text) for text in ("tempo went well", "calf niggle", "easy week"))
    assert newest < middle < oldest < output.index("## Step 1: Choose the path")
    assert "## Older consultation notes" not in output


async def test_notes_past_the_budget_go_to_the_index(training_repo, git_remote):
    from train_with_gpt.tools.start_consultation import NOTES_BUDGET
    files = {
        f"notes/{_days_ago(day)}-07-00-00.md": _note(str(day), f"Synthetic note {day} days ago. " + "x " * 1_500)
        for day in range(1, 21)
    }
    push_files(git_remote, files)

    output = await _start()
    recent = output.split("## Recent consultation notes")[1].split("## Older consultation notes")[0]
    index = output.split("## Older consultation notes (index: date and headline)")[1].split("## Step 1")[0]

    # every full note is whole, and they fit the budget (plus room the goals and profile don't use)
    assert "this note is cut here" not in recent
    assert len(recent) < NOTES_BUDGET + 9_000 + 1_000
    full = recent.count("----- note ")
    assert MIN_FULL <= full < 20
    assert f"Synthetic note {full} days ago" in recent
    assert f"Synthetic note {full + 1} days ago" not in recent
    # the next note is the first line of the index, its headline shortened
    first_line = index.strip().splitlines()[0]
    assert first_line.startswith(f"- {_days_ago(full + 1)} — Synthetic note {full + 1} days ago.")
    assert len(first_line) < 160
    assert "**search_consultation_notes**" in index and "**list_consultation_notes**" in index


MIN_FULL = 3


async def test_the_last_three_notes_are_always_included_even_if_huge(training_repo, git_remote):
    from train_with_gpt.tools.start_consultation import NOTES_BUDGET
    huge = "Synthetic huge note. " + "y " * 20_000
    push_files(git_remote, {
        f"notes/{_days_ago(3)}-07-00-00.md": _note("a", "Short third note."),
        f"notes/{_days_ago(2)}-07-00-00.md": _note("b", huge),
        f"notes/{_days_ago(1)}-07-00-00.md": _note("c", "Short newest note."),
        f"notes/{_days_ago(4)}-07-00-00.md": _note("d", "Fourth note, index only."),
    })

    output = await _start()
    recent = output.split("## Recent consultation notes")[1].split("## Older consultation notes")[0]

    assert recent.count("----- note ") == 3
    assert "Short newest note." in recent and "Short third note." in recent
    assert f"this note is cut here to keep this short: read it in full with **read_consultation_notes** (note_date={_days_ago(2)})" in recent
    assert len(recent) < NOTES_BUDGET + 9_000 + 1_000
    assert "Fourth note, index only." not in recent
    assert f"- {_days_ago(4)} — Fourth note, index only." in output


async def test_the_index_covers_90_days_and_counts_the_rest(training_repo, git_remote):
    push_files(git_remote, {
        f"notes/{_days_ago(1)}-07-00-00.md": _note("a", "One."),
        f"notes/{_days_ago(2)}-07-00-00.md": _note("b", "Two."),
        f"notes/{_days_ago(3)}-07-00-00.md": _note("c", "Three."),
        f"notes/{_days_ago(30)}-07-00-00.md": _note("d", "Thirty days: " + "z " * 12_000),
        f"notes/{_days_ago(120)}-07-00-00.md": _note("e", "Old synthetic note."),
        f"notes/{_days_ago(200)}-07-00-00.md": _note("f", "Older synthetic note."),
    })

    output = await _start()
    index = output.split("## Older consultation notes (index: date and headline)")[1].split("## Step 1")[0]

    assert f"- {_days_ago(30)} — Thirty days:" in index
    assert "Old synthetic note" not in index and "Older synthetic note" not in index
    assert f"Not listed: 2 older note(s), from {_days_ago(200)} to {_days_ago(120)}." in index


async def test_the_whole_reply_stays_within_budget_for_a_long_history(training_repo, git_remote):
    files = {
        f"notes/{_days_ago(day)}-07-00-00.md": _note(str(day), f"Synthetic note {day}. " + "w " * 1_000)
        for day in range(1, 366)
    }
    files["goals.md"] = "# Training Goals\n" + "Synthetic goal. " * 1_000
    files["athlete-profile.md"] = PROFILE
    push_files(git_remote, files)

    output = await _start()

    assert "- **Consultation notes:** 365" in output
    assert len(output) < 45_000  # ~32,000 of context plus the fixed guidance


async def test_goals_and_notes_are_per_oauth_user(training_repo, git_remote):
    push_files(git_remote, {
        "goals/1001.md": "# Training Goals\nOwn synthetic goal\n",
        "notes/1001/2026-04-01-08-00-00.md": _note("a", "Own synthetic note."),
        "goals/1002.md": "# Training Goals\nOther synthetic goal\n",
        "notes/1002/2026-04-02-08-00-00.md": _note("b", "Other synthetic note."),
        "goals.md": "# Training Goals\nPersonal synthetic goal\n",
        "notes/2026-04-03-08-00-00.md": _note("c", "Personal synthetic note."),
    })

    with as_oauth_user("1001"):
        output = await _start(_strava, _strava)

    assert "Own synthetic goal" in output and "Own synthetic note." in output
    for other in ("Other synthetic", "Personal synthetic", "1002"):
        assert other not in output


async def test_returning_athletes_are_told_to_read_back_and_not_to_re_read(training_repo, git_remote):
    push_files(git_remote, {"goals.md": "# Training Goals\nSub-50 10k\n", "notes/2026-01-05-07-00-00.md": NOTE})

    output = await _start()
    path_b = output.split("## Path B")[1].split("## Important Reminders")[0]

    assert "don't call read_goals or read_consultation_notes to\nread it again" in path_b
    assert "**Then open with a read-back** (3-5 short lines), before any advice" in path_b
    assert "If something couldn't be loaded" in path_b
    assert "60 days" not in output


def test_fair_shares_keep_short_items_whole():
    from train_with_gpt.tools.start_consultation import _fair_shares

    assert _fair_shares([100, 50_000, 200], 9_000) == [100, 8_700, 200]
    assert _fair_shares([50_000, 50_000, 50_000], 9_000) == [3_000, 3_000, 3_000]
    assert _fair_shares([10, 20], 9_000) == [10, 20]


async def test_the_tool_description_says_to_call_it_first():
    tool = next(tool for tool in await list_tools() if tool.name == "start_consultation")

    assert tool.description.startswith("Call this first in any training conversation, before answering")
    assert len(tool.description) < 500


def test_the_server_tells_clients_to_start_with_start_consultation():
    from train_with_gpt.server import app

    instructions = app.create_initialization_options().instructions
    assert instructions and "call start_consultation before answering" in instructions


async def test_the_saved_context_costs_one_sync(training_repo, git_remote, monkeypatch):
    from train_with_gpt.tools import start_consultation as module
    push_files(git_remote, {"goals.md": "# Training Goals\nSub-50 10k\n", "notes/2026-01-05-07-00-00.md": NOTE,
                            "athlete-profile.md": PROFILE})
    real, calls = module.git_pull_and_read, []

    def counting(repo_path, read):
        calls.append(repo_path)
        return real(repo_path, read)
    monkeypatch.setattr(module, "git_pull_and_read", counting)

    output = await _start()

    assert len(calls) == 1
    assert "Sub-50 10k" in output and "Easy week." in output and "Made-up runner" in output


async def test_a_long_history_of_short_notes_stays_within_the_budget(training_repo, git_remote):
    # Delimiters and headers count too: with only the note text counted, a
    # year of one-line notes rendered at about twice the notes budget.
    from train_with_gpt.tools.start_consultation import INDEX_BUDGET, _notes_budget
    push_files(git_remote, {
        f"notes/{_days_ago(day)}-07-00-00-abc123.md": f"# Consultation Notes\nDate: {_days_ago(day)} 07:00\n\nOK.\n"
        for day in range(1, 366)
    })

    output = await _start()
    recent = output.split("use them, and don't re-read them.\n\n")[1].split("## Older consultation notes")[0]
    index = output.split("## Older consultation notes (index: date and headline)")[1].split("## Step 1")[0]

    assert recent.count("----- note ") >= 3
    assert len(recent) <= _notes_budget(None, None)
    assert len(index) <= INDEX_BUDGET + 500  # plus the "not listed" line and the pointers


async def test_only_the_notes_that_are_shown_are_read(training_repo, git_remote, monkeypatch):
    # Notes are read under the repo lock every hosted user shares: a long
    # history mustn't mean reading every note on each consultation.
    from pathlib import Path
    push_files(git_remote, {
        f"notes/{_days_ago(day)}-07-00-00.md": _note(str(day), f"Synthetic note {day}. " + "v " * 1_000)
        for day in range(1, 366)
    })
    notes_dir, real_open, opened = training_repo / "notes", Path.open, set()

    def tracking_open(self, *args, **kwargs):
        if self.parent == notes_dir:
            opened.add(self.name)
        return real_open(self, *args, **kwargs)
    monkeypatch.setattr(Path, "open", tracking_open)

    output = await _start()
    shown = output.count("----- note ") + output.count(f"\n- {_days_ago(0)[:2]}")

    assert "- **Consultation notes:** 365" in output
    assert len(opened) <= shown + 1  # the first note that didn't fit is read too
    assert len(opened) < 60
