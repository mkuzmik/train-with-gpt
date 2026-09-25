"""Unit tests for setup_training_repo: real directories, real config file."""

import json

from tests.support import git, text_of
from train_with_gpt.config import config
from train_with_gpt.tools import setup_training_repo_handler


async def test_setup_persists_repo_path_to_config_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "--quiet")

    output = text_of(await setup_training_repo_handler({"repo_path": str(repo)}))

    assert output.startswith(f"✅ Training repository configured: {repo}")
    assert config.training_repo_path == str(repo)
    assert json.loads(config.config_file.read_text()) == {"trainingRepoPath": str(repo)}


async def test_setup_expands_user_home(hermetic):
    repo = hermetic / "training"
    repo.mkdir()
    git(repo, "init", "--quiet")

    text_of(await setup_training_repo_handler({"repo_path": "~/training"}))

    assert config.training_repo_path == str(repo)


async def test_setup_requires_path():
    assert text_of(await setup_training_repo_handler({})) == "❌ Error: No repository path provided"


async def test_setup_with_missing_path(tmp_path):
    output = text_of(await setup_training_repo_handler({"repo_path": str(tmp_path / "nope")}))

    assert "Path does not exist" in output
    assert config.training_repo_path is None
    assert not config.config_file.exists()


async def test_setup_with_a_file_instead_of_a_directory(tmp_path):
    (tmp_path / "file.txt").write_text("x")

    output = text_of(await setup_training_repo_handler({"repo_path": str(tmp_path / "file.txt")}))

    assert "Path is not a directory" in output


async def test_setup_with_non_git_directory(tmp_path):
    output = text_of(await setup_training_repo_handler({"repo_path": str(tmp_path)}))

    assert "Not a git repository" in output
    assert config.training_repo_path is None
