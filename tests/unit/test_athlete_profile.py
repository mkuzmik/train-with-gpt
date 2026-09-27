"""Unit tests for the athlete profile tools (save_athlete_profile,
read_athlete_profile, build_athlete_profile).

save/read run against a real git clone of a local bare remote. All profile
content here is made up.
"""

import asyncio

from tests.support import (
    as_oauth_user,
    assert_clean_and_in_sync,
    git,
    push_files,
    race_on_commit,
    race_runs,
    referenced_tool_names,
    remote_file,
    remote_files,
    text_of,
)
from train_with_gpt.config import config
from train_with_gpt.server import list_tools
from train_with_gpt.tools import (
    build_athlete_profile_handler,
    read_athlete_profile_handler,
    save_athlete_profile_handler,
)
from train_with_gpt.tools.save_athlete_profile import PROFILE_MAX_CHARS, PROFILE_SECTIONS

PROFILE = (
    "## Background\n- Synthetic runner, training since 2019.\n\n"
    "## Race results\n| Date | Event | Distance | Time |\n|---|---|---|---|\n"
    "| 2025-10-12 | Example 10k | 10 km | 45:05 |\n\n"
    "## Health\n- Pattern: ferritin drops below 40 without supplementation.\n"
)


async def _save(content: str = PROFILE) -> str:
    return text_of(await save_athlete_profile_handler({"content": content}))


async def _read() -> str:
    return text_of(await read_athlete_profile_handler({}))


# --- save / read ----------------------------------------------------------------------

async def test_save_writes_commits_and_pushes_to_the_personal_path(training_repo, git_remote):
    output = await _save()

    assert output.startswith("✅ Athlete profile saved, committed and pushed to remote:")
    content = (training_repo / "athlete-profile.md").read_text()
    assert content.startswith("# Athlete profile\nSaved: ")
    assert PROFILE.strip() in content
    assert remote_file(git_remote, "athlete-profile.md") == content
    assert "Update athlete profile" in git(git_remote, "log", "--format=%s", "main")


async def test_saved_profile_can_be_read_back(training_repo):
    await _save()

    output = await _read()

    assert "Example 10k" in output
    assert "ferritin" in output


async def test_saving_replaces_the_whole_profile(training_repo):
    await _save("## Background\n- Old background\n")
    await _save("## Background\n- New background\n")

    output = await _read()

    assert "New background" in output
    assert "Old background" not in output


async def test_a_title_sent_by_the_model_is_not_duplicated(training_repo):
    await _save("# Athlete Profile\n\n" + PROFILE)

    assert (training_repo / "athlete-profile.md").read_text().count("# Athlete profile") == 1


async def test_read_pulls_updates_from_the_remote(training_repo, git_remote):
    push_files(git_remote, {"athlete-profile.md": "# Athlete profile\n\n## Background\n- Edited on GitHub\n"})

    assert "Edited on GitHub" in await _read()


async def test_save_racing_another_device_is_last_writer_wins(training_repo, git_remote):
    race_on_commit(training_repo, git_remote, {"athlete-profile.md": "# Athlete profile\n\nFrom the phone"})

    output = await _save()

    assert race_runs(training_repo) == 1
    assert "pushed to remote" in output
    assert PROFILE.strip() in remote_file(git_remote, "athlete-profile.md")
    assert_clean_and_in_sync(training_repo)


async def test_concurrent_saves_leave_one_complete_version(training_repo, git_remote):
    results = await asyncio.gather(_save("## Background\n- From the phone\n"), _save("## Background\n- From the desktop\n"))

    assert all("pushed to remote" in result for result in results)
    remote = remote_file(git_remote, "athlete-profile.md")
    assert ("From the phone" in remote) != ("From the desktop" in remote)
    assert_clean_and_in_sync(training_repo)


async def test_save_requires_content(training_repo):
    assert await _save("") == "❌ Error: No profile content provided"
    assert await _save("   \n") == "❌ Error: No profile content provided"


async def test_an_oversized_profile_is_refused_and_not_saved(training_repo, git_remote):
    output = await _save("## Background\n" + "x" * PROFILE_MAX_CHARS)

    assert "NOT saved" in output
    assert "consultation notes" in output
    assert not (training_repo / "athlete-profile.md").exists()
    assert "athlete-profile.md" not in remote_files(git_remote)


async def test_a_profile_at_the_limit_is_saved(training_repo):
    body = "## Background\n"
    output = await _save(body + "x" * (PROFILE_MAX_CHARS - len(body)))

    assert output.startswith("✅ Athlete profile saved")


async def test_read_before_any_profile_is_saved_points_to_the_build(training_repo):
    output = await _read()

    assert "No athlete profile saved yet" in output
    assert "build_athlete_profile" in output


async def test_tools_without_repo_configured():
    assert "Training repository not configured" in await _save()
    assert "Training repository not configured" in await _read()


async def test_hosted_user_without_repo_is_pointed_to_the_operator():
    with as_oauth_user("1005"):
        for output in (await _save(), await _read()):
            assert "contact the server's operator" in output
            assert "setup_training_repo" not in output


async def test_read_when_repo_path_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "training_repo_path", str(tmp_path / "deleted"))
    assert "path no longer exists" in await _read()


# --- per user -------------------------------------------------------------------------

async def test_profiles_are_per_oauth_user(training_repo, git_remote):
    with as_oauth_user("1001"):
        await _save("## Background\n- Alice: trail runner\n")
    with as_oauth_user("1002"):
        await _save("## Background\n- Bob: cyclist\n")

    files = remote_files(git_remote)
    assert "athlete/1001.md" in files and "athlete/1002.md" in files
    assert "athlete-profile.md" not in files

    with as_oauth_user("1001"):
        alice = await _read()
    with as_oauth_user("1003"):
        nobody = await _read()
    personal = await _read()

    assert "trail runner" in alice and "cyclist" not in alice
    assert "No athlete profile saved yet" in nobody
    assert "No athlete profile saved yet" in personal


async def test_hosted_read_does_not_list_other_users_files_pulled_by_the_sync(training_repo, git_remote):
    with as_oauth_user("1001"):
        await _save()
    push_files(git_remote, {"athlete/2002.md": "# Athlete profile\nsomeone else\n"})

    with as_oauth_user("1001"):
        output = await _read()

    assert "2002" not in output
    assert "Pulled updates" not in output


# --- build guidance ---------------------------------------------------------------------

async def test_build_guidance_has_the_three_phases_and_the_rules():
    output = text_of(await build_athlete_profile_handler({}))

    for phase in ("## Phase 1: Interview", "## Phase 2: Evidence", "## Phase 3: Discussion"):
        assert phase in output
    for section in PROFILE_SECTIONS:
        assert f"`## {section}`" in output
    assert "ONE question at a time" in output
    assert "confirmed" in output and "contradicted" in output and "not in the data" in output
    assert "PBs are race results" in output
    assert "newest statement wins" in output
    assert "never raw lab panels" in output
    assert "tell the athlete where the profile is" in output


async def test_build_guidance_only_uses_existing_tools():
    registered = {tool.name for tool in await list_tools()}
    referenced = referenced_tool_names(text_of(await build_athlete_profile_handler({})))

    assert {"get_activities", "search_consultation_notes", "save_athlete_profile"} <= referenced
    assert referenced <= registered, referenced - registered


# --- a failed sync ---------------------------------------------------------------------

async def test_missing_profile_after_a_failed_sync_keeps_the_warning(training_repo, tmp_path):
    # The remote is unreachable: a profile saved from another device may be missing here.
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    output = await _read()
    with as_oauth_user("1001"):
        hosted = await _read()

    assert "No athlete profile saved yet" in output
    assert "git pull had issues" in output
    assert "No athlete profile saved yet" in hosted
    assert "couldn't be fully synced" in hosted and "profile" in hosted.split("No athlete")[0]
    assert str(tmp_path) not in hosted


async def test_hosted_user_without_repo_is_told_the_profile_is_unavailable_too():
    with as_oauth_user("1005"):
        assert "the athlete profile" in await _read()


async def test_save_description_allows_health_patterns_but_not_raw_panels():
    from train_with_gpt.tools import save_athlete_profile_tool

    description = save_athlete_profile_tool().description
    assert "no raw lab values" not in description
    assert "recurring patterns such as" in description and "no raw lab panels" in description
