"""Unit tests for the training-repo sync helpers (git_pull, git_save_file).

Real git repos in tmp dirs, with a local bare repo as the remote (no
subprocess mocks). Other writers are other clones pushing to that remote;
`race_on_commit` makes one push between our commit and our push.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.support import (
    assert_clean_and_in_sync,
    clone,
    git,
    push_files,
    race_on_commit,
    race_runs,
    remote_file,
    remote_files,
)
from train_with_gpt import helpers
from train_with_gpt.helpers import GIT_SAVE_ATTEMPTS, GitSyncError, git_pull, git_pull_and_read, git_save_file


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


@pytest.fixture
def no_backoff(monkeypatch):
    monkeypatch.setattr(helpers.time, "sleep", lambda seconds: None)


def commit_locally(repo, path, content, message="Local change"):
    """A commit in `repo` that never reached the remote (e.g. its push failed)."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, "add", path)
    git(repo, "commit", "--quiet", "-m", message)


# --- git_pull --------------------------------------------------------------------

def test_git_pull_up_to_date_returns_none(training_repo):
    assert git_pull(training_repo) is None


def test_git_pull_reports_incoming_changes(training_repo, git_remote):
    push_files(git_remote, {"goals.md": "from another device\n"})

    output = git_pull(training_repo)

    assert output == "Pulled updates from the remote: goals.md"
    assert (training_repo / "goals.md").read_text() == "from another device\n"


def test_git_pull_without_remote_is_silent(local_repo):
    assert git_pull(local_repo) is None


def test_git_pull_reports_other_failures(training_repo, git_remote, tmp_path):
    git_remote.rename(tmp_path / "moved.git")  # remote vanished

    result = git_pull(training_repo)

    assert result.startswith("(Note: git pull had issues - ")


def test_git_pull_recovers_a_diverged_clone_keeping_local_commits(training_repo, git_remote):
    # A local commit whose push failed, and the remote moved on meanwhile -
    # a plain `git pull` refuses to reconcile these, forever.
    commit_locally(training_repo, "notes/2024-01-10-08-00-00.md", "Unpushed note\n")
    push_files(git_remote, {"notes/2024-01-11-08-00-00.md": "From another device\n"})

    output = git_pull(training_repo)

    assert "notes/2024-01-11-08-00-00.md" in output
    assert (training_repo / "notes/2024-01-10-08-00-00.md").read_text() == "Unpushed note\n"
    assert (training_repo / "notes/2024-01-11-08-00-00.md").read_text() == "From another device\n"
    # rebased on top of the remote: just ahead now, no longer diverged
    assert git(training_repo, "rev-list", "--count", "HEAD..@{upstream}").strip() == "0"
    assert git(training_repo, "rev-list", "--count", "@{upstream}..HEAD").strip() == "1"


def test_git_pull_parks_conflicting_local_commits_on_a_branch(training_repo, git_remote):
    commit_locally(training_repo, "goals.md", "Local goals\n")
    push_files(git_remote, {"goals.md": "Remote goals\n"})

    output = git_pull(training_repo)

    assert "1 local commit(s) conflicted" in output
    branch = output.split("moved to local branch '")[1].split("'")[0]
    assert git(training_repo, "show", f"{branch}:goals.md") == "Local goals\n"
    assert (training_repo / "goals.md").read_text() == "Remote goals\n"
    assert_clean_and_in_sync(training_repo)


def test_git_pull_stashes_uncommitted_edits_that_would_block_recovery(training_repo, git_remote):
    # personal checkout: an unpushed goals commit plus an uncommitted edit on
    # top of it, while the remote got different goals
    commit_locally(training_repo, "goals.md", "Local goals\n")
    (training_repo / "goals.md").write_text("Local goals, still editing\n")
    push_files(git_remote, {"goals.md": "Remote goals\n"})

    output = git_pull(training_repo)

    assert "moved to local branch 'unsynced-" in output
    assert "Uncommitted edits were stashed" in output
    assert git(training_repo, "stash", "show", "-p", "stash@{0}").count("Local goals, still editing") == 1
    assert (training_repo / "goals.md").read_text() == "Remote goals\n"
    assert_clean_and_in_sync(training_repo)


def test_git_pull_and_read_reads_under_the_repo_lock(training_repo):
    note, locked = git_pull_and_read(training_repo, lambda: helpers._repo_lock(training_repo).locked())

    assert note is None
    assert locked


def test_git_pull_keeps_uncommitted_edits(training_repo, git_remote):
    # the personal/stdio path: the clone is the user's own checkout
    (training_repo / "README.md").write_text("my local edit\n")
    push_files(git_remote, {"goals.md": "remote\n"})

    git_pull(training_repo)

    assert (training_repo / "README.md").read_text() == "my local edit\n"
    assert (training_repo / "goals.md").read_text() == "remote\n"


# --- git_save_file ------------------------------------------------------------------

def test_save_writes_commits_and_pushes(training_repo, git_remote):
    status = git_save_file(training_repo, "goals.md", "goal\n", "Update goals")

    assert status == " and pushed to remote"
    assert (training_repo / "goals.md").read_text() == "goal\n"
    assert remote_file(git_remote, "goals.md") == "goal\n"
    assert git(git_remote, "log", "-1", "--format=%s", "main").strip() == "Update goals"


def test_save_creates_parent_directories(training_repo, git_remote):
    git_save_file(training_repo, "notes/42/a.md", "note\n", "Add note")

    assert remote_file(git_remote, "notes/42/a.md") == "note\n"


def test_save_only_commits_the_given_path(training_repo, git_remote):
    (training_repo / "scratch.txt").write_text("not for commit\n")

    git_save_file(training_repo, "goals.md", "goal\n", "Update goals")

    assert "scratch.txt" not in remote_files(git_remote)


def test_save_without_remote_keeps_changes_locally(local_repo):
    status = git_save_file(local_repo, "goals.md", "goal\n", "Update goals")

    assert "Could not push (no remote configured)" in status
    assert git(local_repo, "log", "-1", "--format=%s").strip() == "Update goals"


def test_save_when_remote_unreachable_keeps_the_commit(training_repo, git_remote, tmp_path):
    git_remote.rename(tmp_path / "moved.git")

    status = git_save_file(training_repo, "goals.md", "goal\n", "Update goals")

    assert "Could not push to remote" in status
    assert "kept locally; the next save will try to push it again" in status
    assert git(training_repo, "log", "-1", "--format=%s").strip() == "Update goals"


def test_save_does_not_retry_a_push_the_remote_refuses_for_good(training_repo, git_remote):
    attempts = git_remote / "push-attempts"
    hook = git_remote / "hooks" / "pre-receive"
    hook.write_text(f"#!/bin/sh\necho x >> '{attempts}'\necho 'branch is protected' >&2\nexit 1\n")
    hook.chmod(0o755)

    status = git_save_file(training_repo, "goals.md", "goal\n", "Update goals")

    assert "Could not push to remote" in status and "branch is protected" in status
    assert attempts.read_text().count("x") == 1  # no pointless retries
    assert "goals.md" not in remote_files(git_remote)
    assert git(training_repo, "log", "-1", "--format=%s").strip() == "Update goals"  # kept locally


def test_resaving_unchanged_content_pushes_the_pending_commit(training_repo, git_remote, tmp_path):
    moved = tmp_path / "moved.git"
    git_remote.rename(moved)
    git_save_file(training_repo, "goals.md", "goal\n", "Update goals")  # push fails
    moved.rename(git_remote)

    status = git_save_file(training_repo, "goals.md", "goal\n", "Update goals")  # retry, same content

    assert status == " and pushed to remote"
    assert remote_file(git_remote, "goals.md") == "goal\n"
    assert_clean_and_in_sync(training_repo)


def test_unpushed_commit_goes_out_with_the_next_save(training_repo, git_remote, tmp_path):
    moved = tmp_path / "moved.git"
    git_remote.rename(moved)
    git_save_file(training_repo, "notes/a.md", "first\n", "First")  # push fails
    moved.rename(git_remote)
    push_files(git_remote, {"notes/b.md": "other device\n"})

    status = git_save_file(training_repo, "notes/c.md", "third\n", "Third")

    assert status == " and pushed to remote"
    assert {"notes/a.md", "notes/b.md", "notes/c.md"} <= set(remote_files(git_remote))
    assert_clean_and_in_sync(training_repo)


def test_save_with_no_changes_is_reported(training_repo):
    git_save_file(training_repo, "goals.md", "goal\n", "first")

    status = git_save_file(training_repo, "goals.md", "goal\n", "second")

    assert status == "\n\n(No changes to commit - content unchanged)"


def test_save_after_another_clone_pushed_a_different_file(training_repo, git_remote):
    push_files(git_remote, {"notes/2024-01-10-08-00-00.md": "From another device\n"})

    status = git_save_file(training_repo, "notes/2024-01-11-08-00-00.md", "Mine\n", "Add note")

    assert status == " and pushed to remote"
    assert {"notes/2024-01-10-08-00-00.md", "notes/2024-01-11-08-00-00.md"} <= set(remote_files(git_remote))
    assert_clean_and_in_sync(training_repo)


def test_save_retries_when_a_concurrent_push_lands_first(training_repo, git_remote, no_backoff):
    race_on_commit(training_repo, git_remote, {"notes/other.md": "Racing writer"})

    status = git_save_file(training_repo, "notes/mine.md", "Mine\n", "Add note")

    assert race_runs(training_repo) == 1  # our first push really was rejected
    assert status == " and pushed to remote"
    assert remote_file(git_remote, "notes/mine.md") == "Mine\n"
    assert remote_file(git_remote, "notes/other.md") == "Racing writer(concurrent push 0)\n"
    assert_clean_and_in_sync(training_repo)


def test_save_racing_a_write_to_the_same_file_is_last_writer_wins(training_repo, git_remote, no_backoff):
    race_on_commit(training_repo, git_remote, {"goals.md": "Goals from another device"})

    status = git_save_file(training_repo, "goals.md", "My new goals\n", "Update goals")

    assert status == " and pushed to remote"
    assert remote_file(git_remote, "goals.md") == "My new goals\n"
    assert_clean_and_in_sync(training_repo)


def test_save_gives_up_after_bounded_retries_and_says_so(training_repo, git_remote, no_backoff):
    race_on_commit(training_repo, git_remote, {"notes/other.md": "Racing writer"}, times=100)

    with pytest.raises(GitSyncError, match="NOT saved"):
        git_save_file(training_repo, "notes/mine.md", "Mine\n", "Add note")

    assert race_runs(training_repo) == GIT_SAVE_ATTEMPTS
    assert "notes/mine.md" not in remote_files(git_remote)
    assert not (training_repo / "notes/mine.md").exists()
    assert_clean_and_in_sync(training_repo)


def test_save_parks_conflicting_old_local_commits_and_still_saves(training_repo, git_remote):
    commit_locally(training_repo, "goals.md", "Stale local goals\n")
    push_files(git_remote, {"goals.md": "Remote goals\n"})

    status = git_save_file(training_repo, "goals.md", "New goals\n", "Update goals")

    assert status.startswith(" and pushed to remote")
    assert "moved to local branch 'unsynced-" in status
    assert remote_file(git_remote, "goals.md") == "New goals\n"
    assert_clean_and_in_sync(training_repo)


def test_concurrent_saves_in_one_process_are_serialized(training_repo, git_remote):
    paths = [f"notes/n{i}.md" for i in range(6)]

    with ThreadPoolExecutor(max_workers=len(paths)) as pool:
        statuses = list(pool.map(lambda p: git_save_file(training_repo, p, f"{p}\n", f"Add {p}"), paths))

    assert statuses == [" and pushed to remote"] * len(paths)
    assert set(paths) <= set(remote_files(git_remote))
    assert_clean_and_in_sync(training_repo)


def test_concurrent_saves_and_pulls_share_the_lock(training_repo, git_remote):
    other = clone(git_remote, training_repo.parent / "other-device")

    def save(i):
        return git_save_file(training_repo, f"notes/n{i}.md", f"{i}\n", f"Add {i}")

    def pull(_):
        return git_pull(training_repo)

    with ThreadPoolExecutor(max_workers=8) as pool:
        saves = [pool.submit(save, i) for i in range(4)]
        pulls = [pool.submit(pull, i) for i in range(4)]
        assert [f.result() for f in saves] == [" and pushed to remote"] * 4
        assert all(f.result() is None or f.result().startswith("Pulled updates") for f in pulls)

    git(other, "pull", "--quiet")
    assert sorted(p.name for p in (other / "notes").glob("*.md")) == [f"n{i}.md" for i in range(4)]
