"""Unit tests for the self-test checklist (self_test.py) and its CLI.

Real git against local bare remotes (tests/support.py); intervals.icu and
Strava stubbed with respx. All credentials are fake.
"""

import asyncio
import time

import pytest
from httpx import Response

from tests.support import clone, git, push_files, remote_file, remote_files
from train_with_gpt import self_test, store
from train_with_gpt.config import config
from train_with_gpt.self_test import FAIL, PASS, WARN, format_report, main, run_self_test, sanitize

INTERVALS = "https://intervals.icu/api/v1"
STRAVA_API = "https://www.strava.com/api/v3"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

FAKE_STRAVA_ACCESS = "fake-strava-access-SECRET-a1b2c3"
FAKE_STRAVA_REFRESH = "fake-strava-refresh-SECRET-d4e5f6"
FAKE_REMOTE_TOKEN = "fake-remote-token-SECRET-778899"


def by_name(report):
    return {check.name: check for check in report.checks}


@pytest.fixture
def git_sha(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")


@pytest.fixture
def intervals_ok(http_mock, intervals_api_key):
    """A working personal intervals.icu account: 2 activities, some wellness."""
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(200, json={"id": "i1", "name": "Test"}))
    http_mock.get(f"{INTERVALS}/athlete/0/activities").mock(return_value=Response(200, json=[
        {"id": "i1", "type": "Run", "start_date": "2024-01-15T07:00:00Z"},
        {"id": "i2", "type": "Ride", "start_date": "2024-01-16T07:00:00Z"},
    ]))
    http_mock.get(f"{INTERVALS}/athlete/0/wellness").mock(return_value=Response(200, json=[{"id": "2024-01-15"}]))
    return http_mock


@pytest.fixture
def strava_user(db, strava_app_credentials, http_mock):
    """An OAuth'd Strava user (fake tokens) with a working Strava API."""
    store.upsert_user("4242", "strava", "Test Athlete", FAKE_STRAVA_ACCESS, FAKE_STRAVA_REFRESH, int(time.time()) + 3600)
    http_mock.get(f"{STRAVA_API}/athlete").mock(return_value=Response(200, json={"id": 4242}))
    http_mock.get(f"{STRAVA_API}/athlete/activities").mock(return_value=Response(200, json=[{"id": 1}]))
    return "4242"


# --- all checks ------------------------------------------------------------------

async def test_all_checks_pass(intervals_ok, training_repo, git_remote, git_sha):
    report = await run_self_test(None)

    assert [(c.name, c.status) for c in report.checks] == [
        ("Data source auth", PASS), ("Data reads", PASS), ("Repo read", PASS),
        ("Repo write", PASS), ("Build info", PASS), ("Tools registered", PASS),
    ]
    checks = by_name(report)
    assert "intervals.icu, key authenticates" in checks["Data source auth"].detail
    assert "activities in the last 7 days: 2" in checks["Data reads"].detail
    assert "wellness: data returned" in checks["Data reads"].detail
    assert "clean" in checks["Repo read"].detail and "at origin/main" in checks["Repo read"].detail
    assert "verified on origin/main" in checks["Repo write"].detail
    assert "GIT_SHA abc1234" in checks["Build info"].detail and "mcp " in checks["Build info"].detail
    assert "self_test" in checks["Tools registered"].detail and "save_goals" in checks["Tools registered"].detail

    marker = remote_file(git_remote, "selftest/local.md")
    assert f"run_id: {report.run_id}" in marker and "git_sha: abc1234" in marker

    output = format_report(report)
    assert output.startswith("## Self-test: PASS\n")
    assert output.count("| PASS |") == 6
    assert output.endswith("Overall: PASS")


async def test_data_reads_return_counts_only(intervals_ok, training_repo):
    report = await run_self_test(None)

    output = format_report(report)
    assert "Ride" not in output and "2024-01-16" not in output


async def test_missing_git_sha_is_a_warning(intervals_ok, training_repo, monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)

    report = await run_self_test(None)

    assert by_name(report)["Build info"].status == WARN
    assert "GIT_SHA unknown" in by_name(report)["Build info"].detail
    assert not report.failed
    assert format_report(report).startswith("## Self-test: PASS with 1 warning(s)")


# --- data source -----------------------------------------------------------------

async def test_data_source_401_fails_but_every_check_still_runs(http_mock, intervals_api_key, training_repo, git_remote):
    http_mock.get(f"{INTERVALS}/athlete/0").mock(return_value=Response(401, json={"error": "unauthorized"}))
    http_mock.get(f"{INTERVALS}/athlete/0/activities").mock(return_value=Response(401))

    report = await run_self_test(None)

    checks = by_name(report)
    assert checks["Data source auth"].status == FAIL
    assert checks["Data source auth"].detail == "HTTPStatusError: HTTP 401 from intervals.icu/api/v1/athlete/0"
    assert checks["Data reads"].status == FAIL
    assert checks["Repo read"].status == PASS and checks["Repo write"].status == PASS
    assert len(report.checks) == 6
    assert "selftest/local.md" in remote_files(git_remote)
    output = format_report(report)
    assert "FAIL - 2 of 6 checks failed: Data source auth, Data reads" in output
    assert intervals_api_key not in output


async def test_no_data_source_configured(training_repo):
    report = await run_self_test(None)

    assert by_name(report)["Data source auth"].detail == "ValueError: INTERVALS_API_KEY not configured"


async def test_strava_user(strava_user, training_repo, git_remote, git_sha):
    report = await run_self_test(strava_user)

    checks = by_name(report)
    assert not report.failed, format_report(report)
    assert checks["Data source auth"].detail == (
        "activities: Strava, token valid; wellness: none (Strava has no wellness data)"
    )
    assert checks["Data reads"].detail == "activities in the last 7 days: 1; wellness: not available (Strava)"
    assert "selftest/4242.md" in remote_files(git_remote)
    assert report.user == "4242"


async def test_strava_expired_token_is_refreshed(strava_user, http_mock, training_repo):
    store.update_user_tokens(strava_user, FAKE_STRAVA_ACCESS, FAKE_STRAVA_REFRESH, int(time.time()) - 10)
    http_mock.post(STRAVA_TOKEN_URL).mock(return_value=Response(200, json={
        "access_token": "fake-rotated-access-SECRET", "refresh_token": "fake-rotated-refresh-SECRET",
        "expires_at": int(time.time()) + 3600,
    }))

    report = await run_self_test(strava_user)

    assert "Strava, token refreshed and valid" in by_name(report)["Data source auth"].detail
    assert store.get_user(strava_user)["access_token"] == "fake-rotated-access-SECRET"
    assert "SECRET" not in format_report(report)


async def test_unknown_user(db, training_repo):
    report = await run_self_test("999")

    assert by_name(report)["Data source auth"].detail == "ValueError: No stored Strava credentials for user 999"


async def test_no_secrets_in_output(strava_user, http_mock, training_repo, monkeypatch):
    """Fake tokens, API keys and URL credentials must never be echoed back."""
    monkeypatch.setattr(config, "intervals_api_key", "fake-intervals-key-SECRET-445566")
    http_mock.get(f"{STRAVA_API}/athlete").mock(side_effect=RuntimeError(
        f"boom Authorization: Bearer {FAKE_STRAVA_ACCESS} refresh_token={FAKE_STRAVA_REFRESH}"
    ))
    http_mock.get(f"{STRAVA_API}/athlete/activities").mock(side_effect=ValueError(
        f"https://user:{FAKE_REMOTE_TOKEN}@example.invalid/x?access_token=fake-intervals-key-SECRET-445566"
    ))
    git(training_repo, "remote", "set-url", "origin",
        f"https://x-access-token:{FAKE_REMOTE_TOKEN}@127.0.0.1:9/training-context.git")

    report = await run_self_test(strava_user)

    output = format_report(report)
    assert by_name(report)["Data source auth"].status == FAIL
    assert by_name(report)["Data source auth"].detail.startswith("RuntimeError: boom")
    for secret in (FAKE_STRAVA_ACCESS, FAKE_STRAVA_REFRESH, FAKE_REMOTE_TOKEN, "fake-intervals-key-SECRET-445566"):
        assert secret not in output
    assert "SECRET" not in output


def test_sanitize():
    assert sanitize("see https://u:pw@host.example/p?token=abc#frag now") == "see https://***@host.example/p now"
    assert sanitize("Bearer abc.def and api_key=xyz") == "Bearer *** and api_key=***"
    assert sanitize("the key hunter2 leaked", ["hunter2"]) == "the key *** leaked"
    assert sanitize("x" * 1000).endswith("…") and len(sanitize("x" * 1000)) == 301


# --- repo read -------------------------------------------------------------------

async def test_no_remote_configured(intervals_ok, tmp_path, monkeypatch):
    repo = tmp_path / "local-only"
    repo.mkdir()
    git(repo, "init", "--quiet")
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "--quiet", "-m", "init")
    monkeypatch.setattr(config, "training_repo_path", str(repo))

    report = await run_self_test(None)

    checks = by_name(report)
    assert checks["Repo read"].status == WARN
    assert "no remote configured" in checks["Repo read"].detail
    assert checks["Repo write"].status == FAIL
    assert checks["Repo write"].detail.startswith("saved but not pushed:")
    assert "no remote configured" in checks["Repo write"].detail


async def test_training_repo_not_configured(intervals_ok):
    report = await run_self_test(None)

    for name in ("Repo read", "Repo write"):
        assert by_name(report)[name].status == FAIL
        assert "Training repository not configured" in by_name(report)[name].detail


async def test_dirty_clone_fails(intervals_ok, training_repo):
    (training_repo / "README.md").write_text("edited but never committed\n")

    report = await run_self_test(None)

    assert by_name(report)["Repo read"].status == FAIL
    assert "1 uncommitted change(s) to tracked files" in by_name(report)["Repo read"].detail


async def test_clone_ahead_of_remote_fails_read_then_write_pushes_it(intervals_ok, training_repo, git_remote):
    """A commit whose push failed earlier: read reports it, the write check pushes it."""
    (training_repo / "notes").mkdir()
    (training_repo / "notes" / "2024-01-10.md").write_text("synthetic note\n")
    git(training_repo, "add", "notes")
    git(training_repo, "commit", "--quiet", "-m", "Earlier save whose push failed")
    push_files(git_remote, {"other.md": "from another device\n"})

    report = await run_self_test(None)

    checks = by_name(report)
    assert checks["Repo read"].status == FAIL
    assert "1 local commit(s) not pushed" in checks["Repo read"].detail
    assert checks["Repo write"].status == PASS
    assert "notes/2024-01-10.md" in remote_files(git_remote)


async def test_conflicting_divergence_is_parked_and_warned(intervals_ok, training_repo, git_remote):
    (training_repo / "README.md").write_text("local version\n")
    git(training_repo, "commit", "--quiet", "-am", "Local edit")
    push_files(git_remote, {"README.md": "remote version\n"})

    report = await run_self_test(None)

    read = by_name(report)["Repo read"]
    assert read.status == WARN
    assert "conflicted" in read.detail and "unsynced-" in read.detail
    assert by_name(report)["Repo write"].status == PASS


async def test_unsynced_branches_warn(intervals_ok, training_repo):
    git(training_repo, "branch", "unsynced-20240101-000000-abcd")

    report = await run_self_test(None)

    read = by_name(report)["Repo read"]
    assert read.status == WARN
    assert "1 unsynced-* branch(es) with parked commits: unsynced-20240101-000000-abcd" in read.detail
    assert not report.failed


# --- repo write ------------------------------------------------------------------

async def test_remote_unreachable_is_saved_but_not_pushed(intervals_ok, training_repo, tmp_path):
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    report = await run_self_test(None)

    write = by_name(report)["Repo write"]
    assert write.status == FAIL
    assert write.detail.startswith("saved but not pushed:")
    assert "Could not push to remote" in write.detail
    assert by_name(report)["Repo read"].status == FAIL


async def test_marker_is_overwritten_not_added(intervals_ok, training_repo, git_remote):
    first = await run_self_test(None)
    second = await run_self_test(None)

    assert not first.failed and not second.failed
    assert [p for p in remote_files(git_remote) if p.startswith("selftest/")] == ["selftest/local.md"]
    assert f"run_id: {second.run_id}" in remote_file(git_remote, "selftest/local.md")
    commits = git(git_remote, "log", "--format=%s", "main", "--", "selftest/local.md").splitlines()
    assert commits == [f"Self-test run {second.run_id}", f"Self-test run {first.run_id}"]


async def test_notes_and_goals_are_untouched(strava_user, training_repo, git_remote):
    push_files(git_remote, {
        "notes/4242/2024-01-10-08-00-00.md": "# Consultation Notes\n\nsynthetic\n",
        "goals/4242.md": "# Training Goals\n\nsynthetic\n",
        "goals.md": "root goals\n",
    })
    before = git(git_remote, "rev-parse", "main").strip()

    await run_self_test(strava_user)
    await run_self_test(strava_user)

    changed = git(git_remote, "diff", "--name-only", before, "main").split()
    assert changed == ["selftest/4242.md"]
    assert git(training_repo, "status", "--porcelain") == ""


async def test_push_verified_independently(intervals_ok, training_repo, monkeypatch):
    """If git_save_file said "pushed" but the remote doesn't have it, the check fails."""
    monkeypatch.setattr(self_test, "git_save_file", lambda *args: " and pushed to remote")

    report = await run_self_test(None)

    write = by_name(report)["Repo write"]
    assert write.status == FAIL
    assert "does not contain run" in write.detail


async def test_marker_overwritten_by_a_concurrent_run_still_passes(intervals_ok, training_repo, git_remote, monkeypatch):
    """Another self-test pushing its marker between our push and our verify
    doesn't turn our successful push into a FAIL."""
    real_save = self_test.git_save_file

    def save_then_race(*args):
        status = real_save(*args)
        push_files(git_remote, {"selftest/local.md": "- run_id: someotherrun\n"}, "Self-test run someotherrun")
        return status

    monkeypatch.setattr(self_test, "git_save_file", save_then_race)

    report = await run_self_test(None)

    write = by_name(report)["Repo write"]
    assert write.status == PASS, write.detail
    assert "history" in write.detail


async def test_git_sync_error_is_not_saved(intervals_ok, training_repo, monkeypatch):
    def refuse(*args):
        raise self_test.GitSyncError("The remote kept changing while saving, so this was NOT saved")

    monkeypatch.setattr(self_test, "git_save_file", refuse)

    report = await run_self_test(None)

    assert by_name(report)["Repo write"].detail.startswith("not saved: The remote kept changing")


# --- runner ----------------------------------------------------------------------

async def test_a_check_that_hangs_times_out(intervals_ok, training_repo, monkeypatch):
    async def hang(ctx):
        await asyncio.sleep(10)

    monkeypatch.setitem(self_test.TIMEOUTS, "tools", 0.05)
    monkeypatch.setattr(self_test, "check_tools", hang)
    monkeypatch.setattr(self_test, "CHECKS", [(n, k, hang if k == "tools" else c) for n, k, c in self_test.CHECKS])

    report = await run_self_test(None)

    assert by_name(report)["Tools registered"].status == FAIL
    assert by_name(report)["Tools registered"].detail == "timed out after 0.05s"
    assert by_name(report)["Repo write"].status == PASS


async def test_pipes_in_details_do_not_break_the_table(intervals_ok, training_repo, monkeypatch):
    async def piped(ctx):
        return PASS, "a | b\nc"

    monkeypatch.setattr(self_test, "CHECKS", [("Piped", "tools", piped)])

    output = format_report(await run_self_test(None))

    assert "| 1 | Piped | PASS |" in output and "a / b c |" in output


# --- prompt ----------------------------------------------------------------------

async def test_every_tool_is_classified_for_the_prompt():
    """New tools must be added to READ_ONLY_TOOLS (+ NOT_IN_PROMPT) or WRITE_TOOLS."""
    names = set(await self_test.registered_tool_names())
    read_only = set(self_test.READ_ONLY_TOOLS) | set(self_test.READ_ONLY_TOOLS_NOT_IN_PROMPT)
    write = set(self_test.WRITE_TOOLS)

    assert not read_only & write
    assert names == read_only | write


def test_prompt_never_asks_to_call_a_write_tool():
    from train_with_gpt.tools.self_test import self_test_prompt_result

    text = self_test_prompt_result().messages[0].content.text
    call_list = text.split("2. Then call")[1].split("3. Do NOT")[0]
    for tool in ("save_goals", "save_consultation_notes", "setup_training_repo"):
        assert tool not in call_list
        assert tool in text.split("3. Do NOT")[1]  # named as forbidden


def test_descriptions_do_not_overstate_write_isolation():
    """self_test pushes its marker (and any pending commits) and syncs notes/goals, so the
    user-facing text must not promise it never touches them or never writes."""
    from train_with_gpt.tools.self_test import self_test_prompt, self_test_tool

    tool_description = self_test_tool().description
    assert "never notes or goals" not in tool_description
    assert "never creates or edits notes or goals" in tool_description
    assert "pending" in tool_description

    prompt_description = self_test_prompt().description
    assert "Never calls a write tool" not in prompt_description
    assert "marker file" in prompt_description


# --- CLI -------------------------------------------------------------------------

def test_cli_exits_zero_when_all_checks_pass(intervals_ok, training_repo, git_sha, capsys):
    assert main([]) == 0
    assert "Overall: PASS" in capsys.readouterr().out


def test_cli_exits_non_zero_when_a_check_fails(training_repo, capsys):
    assert main([]) == 1  # no intervals.icu key configured
    assert "Overall: FAIL" in capsys.readouterr().out


def test_cli_for_a_user_id(strava_user, training_repo, git_remote, capsys):
    assert main(["--user-id", strava_user]) == 0
    assert "user 4242" in capsys.readouterr().out
    assert "selftest/4242.md" in remote_files(git_remote)


def test_cli_rejects_a_path_like_user_id(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--user-id", "../notes"])
    assert exit_info.value.code == 2


async def test_a_hung_repo_read_skips_the_write(intervals_ok, training_repo, git_remote, monkeypatch):
    """asyncio can't stop a git worker thread, so don't start another save next to it."""
    async def hang(ctx):
        await asyncio.sleep(10)

    monkeypatch.setitem(self_test.TIMEOUTS, "repo_read", 0.05)
    monkeypatch.setattr(self_test, "CHECKS", [(n, k, hang if k == "repo_read" else c) for n, k, c in self_test.CHECKS])

    report = await run_self_test(None)

    assert "may still be running" in by_name(report)["Repo read"].detail
    assert by_name(report)["Repo write"].status == FAIL
    assert by_name(report)["Repo write"].detail.startswith("not run:")
    assert "selftest/local.md" not in remote_files(git_remote)


async def test_untracked_files_are_not_reported_as_clean(intervals_ok, training_repo):
    (training_repo / "stray.txt").write_text("synthetic\n")

    report = await run_self_test(None)

    read = by_name(report)["Repo read"]
    assert read.status == WARN
    assert "1 untracked file(s)" in read.detail and "clean" not in read.detail


async def test_short_secrets_are_redacted_too(training_repo, monkeypatch):
    monkeypatch.setattr(config, "intervals_api_key", "k3y")

    async def echo(ctx):
        raise RuntimeError("leaked k3y here")

    monkeypatch.setattr(self_test, "CHECKS", [("Echo", "tools", echo)])

    report = await run_self_test(None)

    assert "k3y" not in format_report(report)


async def test_a_symlinked_marker_is_refused(intervals_ok, training_repo, git_remote):
    push_files(git_remote, {"goals.md": "root goals\n"})
    git(training_repo, "pull", "--quiet")
    (training_repo / "selftest").mkdir()
    (training_repo / "selftest" / "local.md").symlink_to(training_repo / "goals.md")

    report = await run_self_test(None)

    assert by_name(report)["Repo write"].detail == "not saved: selftest/local.md or its folder is a symlink"
    assert (training_repo / "goals.md").read_text() == "root goals\n"
