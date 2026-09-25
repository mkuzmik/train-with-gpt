"""Unit tests for helpers.py, using real git repos in tmp dirs (no subprocess mocks)."""

from pathlib import Path

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from tests.support import clone, git, remote_file, remote_files
from train_with_gpt.helpers import (
    calculate_zone_distribution,
    current_user_id,
    extract_note_headline,
    git_add_commit_push,
    git_pull,
    user_scoped_goals_file,
    user_scoped_notes_dir,
)


@pytest.fixture
def local_repo(tmp_path):
    """A git repo with one commit and no remote at all."""
    repo = tmp_path / "local"
    repo.mkdir()
    git(repo, "init", "--quiet")
    (repo / "README.md").write_text("hi\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "--quiet", "-m", "init")
    return repo


# --- user scoping -------------------------------------------------------------

def test_user_scoped_paths_for_oauth_user():
    repo = Path("/repo")
    assert user_scoped_notes_dir(repo, "42") == (repo / "notes" / "42", "notes/42")
    assert user_scoped_goals_file(repo, "42") == (repo / "goals" / "42.md", "goals/42.md")


def test_user_scoped_paths_for_personal_path():
    repo = Path("/repo")
    assert user_scoped_notes_dir(repo, None) == (repo / "notes", "notes")
    assert user_scoped_goals_file(repo, None) == (repo / "goals.md", "goals.md")


def test_current_user_id_is_none_without_an_authenticated_request():
    assert current_user_id() is None


def test_current_user_id_is_the_access_token_subject():
    token = AccessToken(token="t", client_id="claude", scopes=[], subject="1001")
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        assert current_user_id() == "1001"
    finally:
        auth_context_var.reset(reset)


# --- extract_note_headline ------------------------------------------------------

def test_headline_skips_standard_header_and_date():
    text = "# Consultation Notes\nDate: 2024-01-15 08:00:00\n\nDiscussed marathon plan.\n"
    assert extract_note_headline(text) == "Discussed marathon plan."


def test_headline_skips_banners_markdown_headers_and_caps_titles():
    text = (
        "# Consultation Notes\nDate: 2024-01-20\n\n"
        "========================================\nHEADLINE\n"
        "========================================\n## Summary\n"
        "Follow-up check-in, mileage on track.\n"
    )
    assert extract_note_headline(text) == "Follow-up check-in, mileage on track."


def test_headline_joins_prose_lines():
    assert extract_note_headline("First line.\nSecond line.\n") == "First line. Second line."


def test_headline_truncates_on_a_word_boundary():
    headline = extract_note_headline("alpha beta gamma " * 10, max_length=50)
    assert headline.endswith("…")
    assert len(headline) <= 51
    assert headline[:-1].split(" ")[-1] in ("alpha", "beta", "gamma")


def test_headline_placeholder_for_empty_note():
    assert extract_note_headline("# Consultation Notes\nDate: x\n\n") == "(no summary available)"


# --- calculate_zone_distribution --------------------------------------------------

def test_zone_distribution_buckets_each_sample():
    # Boundaries are zone upper bounds (inclusive); above the last is the top zone.
    assert calculate_zone_distribution([100, 120, 121, 150, 200, None], [120, 150]) == {1: 2, 2: 2, 3: 1}


def test_zone_distribution_empty_inputs():
    assert calculate_zone_distribution([], [120]) == {}
    assert calculate_zone_distribution([100], []) == {}


# --- git_pull --------------------------------------------------------------------

def test_git_pull_up_to_date_returns_none(training_repo):
    assert git_pull(training_repo) is None


def test_git_pull_reports_incoming_changes(training_repo, git_remote, tmp_path):
    other = clone(git_remote, tmp_path / "other-device")
    (other / "goals.md").write_text("from another device\n")
    git(other, "add", "goals.md")
    git(other, "commit", "--quiet", "-m", "remote change")
    git(other, "push", "--quiet")

    output = git_pull(training_repo)

    assert output and "goals.md" in output
    assert (training_repo / "goals.md").read_text() == "from another device\n"


def test_git_pull_without_remote_is_silent(local_repo):
    assert git_pull(local_repo) is None


def test_git_pull_reports_other_failures(training_repo, git_remote, tmp_path):
    git_remote.rename(tmp_path / "moved.git")  # remote vanished

    result = git_pull(training_repo)

    assert result.startswith("(Note: git pull had issues - ")


# --- git_add_commit_push ------------------------------------------------------------

def test_commit_and_push_to_remote(training_repo, git_remote):
    (training_repo / "goals.md").write_text("goal\n")

    status = git_add_commit_push(training_repo, "goals.md", "Update goals")

    assert status == " and pushed to remote"
    assert remote_file(git_remote, "goals.md") == "goal\n"
    assert git(git_remote, "log", "-1", "--format=%s", "main").strip() == "Update goals"


def test_commit_only_adds_the_given_path(training_repo, git_remote):
    (training_repo / "goals.md").write_text("goal\n")
    (training_repo / "scratch.txt").write_text("not for commit\n")

    git_add_commit_push(training_repo, "goals.md", "Update goals")

    assert "scratch.txt" not in remote_files(git_remote)


def test_commit_without_remote_keeps_changes_locally(local_repo):
    (local_repo / "goals.md").write_text("goal\n")

    status = git_add_commit_push(local_repo, "goals.md", "Update goals")

    assert "Could not push (no remote configured)" in status
    assert git(local_repo, "log", "-1", "--format=%s").strip() == "Update goals"


def test_push_failure_is_reported_but_commit_kept(training_repo, git_remote, tmp_path):
    git_remote.rename(tmp_path / "moved.git")
    (training_repo / "goals.md").write_text("goal\n")

    status = git_add_commit_push(training_repo, "goals.md", "Update goals")

    assert "Could not push to remote" in status
    assert git(training_repo, "log", "-1", "--format=%s").strip() == "Update goals"


def test_commit_with_no_changes_is_reported(training_repo):
    (training_repo / "goals.md").write_text("goal\n")
    git_add_commit_push(training_repo, "goals.md", "first")

    status = git_add_commit_push(training_repo, "goals.md", "second")

    assert status == "\n\n(No changes to commit - content unchanged)"
