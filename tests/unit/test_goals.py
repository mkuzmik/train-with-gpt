"""Unit tests for the goals tools (discuss_goals, save_goals, read_goals).

save/read run against a real git clone of a local bare remote.
"""

from tests.support import push_files, remote_file, text_of
from train_with_gpt.config import config
from train_with_gpt.tools import discuss_goals_handler, read_goals_handler, save_goals_handler

GOALS = "## Marathon Goal\n- Run under 4 hours\n- Build to 60km/week"


async def test_discuss_goals_returns_the_framework():
    output = text_of(await discuss_goals_handler({}))

    assert output.startswith("# Training Goal Setting Framework")
    assert "ASK ONE QUESTION AT A TIME" in output
    assert "save_goals" in output


async def test_save_goals_writes_commits_and_pushes(training_repo, git_remote):
    output = text_of(await save_goals_handler({"goals_text": GOALS}))

    assert output.startswith("✅ Goals saved, committed and pushed to remote:")
    content = (training_repo / "goals.md").read_text()
    assert content.startswith("# Training Goals\nSaved: ")
    assert GOALS in content
    assert remote_file(git_remote, "goals.md") == content


async def test_saved_goals_can_be_read_back(training_repo):
    await save_goals_handler({"goals_text": GOALS})

    output = text_of(await read_goals_handler({}))

    assert "Marathon Goal" in output
    assert "4 hours" in output


async def test_saving_new_goals_replaces_the_old_ones(training_repo):
    await save_goals_handler({"goals_text": "Old goal: 10k"})
    await save_goals_handler({"goals_text": "New goal: half marathon"})

    output = text_of(await read_goals_handler({}))

    assert "half marathon" in output
    assert "10k" not in output


async def test_read_goals_pulls_updates_from_the_remote(training_repo, git_remote):
    push_files(git_remote, {"goals.md": "# Training Goals\n\nUpdated on another device\n"})

    output = text_of(await read_goals_handler({}))

    assert "Updated on another device" in output


async def test_save_goals_requires_text(training_repo):
    assert text_of(await save_goals_handler({"goals_text": ""})) == "❌ Error: No goals provided"


async def test_save_goals_without_repo_configured():
    output = text_of(await save_goals_handler({"goals_text": "Test goals"}))
    assert "Training repository not configured" in output


async def test_read_goals_without_repo_configured():
    assert "Training repository not configured" in text_of(await read_goals_handler({}))


async def test_read_goals_when_repo_path_is_gone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "training_repo_path", str(tmp_path / "deleted"))
    assert "path no longer exists" in text_of(await read_goals_handler({}))


async def test_read_goals_before_any_are_saved(training_repo):
    assert "No goals saved yet" in text_of(await read_goals_handler({}))
