"""Unit tests for Config: real JSON files in tmp dirs, real env vars.

When adding a config field: cover its default, loading it from the file,
saving it (if save() supports it) and, if it has one, its env var override.
"""

import json

import pytest

from train_with_gpt import config as config_module
from train_with_gpt.config import Config


@pytest.fixture
def config_file(tmp_path):
    return tmp_path / "train-with-gpt" / "config.json"


def write_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_defaults_are_none(config_file):
    config = Config(config_file)
    assert config.intervals_api_key is None
    assert config.training_repo_path is None
    assert config.client_id is None
    assert config.client_secret is None
    assert config.token_encryption_key is None


def test_load_without_file_leaves_everything_unset(config_file):
    config = Config(config_file)
    config.load()
    assert (config.intervals_api_key, config.training_repo_path, config.client_id, config.client_secret) == (
        None, None, None, None,
    )


def test_load_from_file(config_file):
    write_config(config_file, {
        "intervalsApiKey": "file_key",
        "trainingRepoPath": "/tmp/training",
        "clientId": "file-client-id",
        "clientSecret": "file-client-secret",
        "tokenEncryptionKey": "file_fernet_key",
    })

    config = Config(config_file)
    config.load()

    assert config.token_encryption_key == "file_fernet_key"
    assert config.intervals_api_key == "file_key"
    assert config.training_repo_path == "/tmp/training"
    assert config.client_id == "file-client-id"
    assert config.client_secret == "file-client-secret"


def test_env_vars_override_file(config_file, monkeypatch):
    write_config(config_file, {
        "intervalsApiKey": "file_key",
        "trainingRepoPath": "/file/repo",
        "clientId": "file-client-id",
        "clientSecret": "file-client-secret",
        "tokenEncryptionKey": "file_fernet_key",
    })
    monkeypatch.setenv("INTERVALS_API_KEY", "env_key")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "env_fernet_key")
    monkeypatch.setenv("TRAINING_REPO_PATH", "/env/repo")
    monkeypatch.setenv("STRAVA_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "env-client-secret")

    config = Config(config_file)
    config.load()

    assert config.intervals_api_key == "env_key"
    assert config.training_repo_path == "/env/repo"
    assert config.client_id == "env-client-id"
    assert config.client_secret == "env-client-secret"
    assert config.token_encryption_key == "env_fernet_key"


def test_invalid_json_file_is_ignored(config_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{not json")

    config = Config(config_file)
    config.load()

    assert config.intervals_api_key is None


def test_save_creates_file_and_updates_instance(config_file):
    config = Config(config_file)

    config.save(intervals_api_key="test_key", training_repo_path="/tmp/test")

    assert json.loads(config_file.read_text()) == {
        "intervalsApiKey": "test_key",
        "trainingRepoPath": "/tmp/test",
    }
    assert config.intervals_api_key == "test_key"
    assert config.training_repo_path == "/tmp/test"


def test_save_preserves_unrelated_keys(config_file):
    write_config(config_file, {"clientId": "keep-me", "trainingRepoPath": "/old"})

    Config(config_file).save(training_repo_path="/new")

    assert json.loads(config_file.read_text()) == {"clientId": "keep-me", "trainingRepoPath": "/new"}


def test_save_then_load_round_trips(config_file):
    Config(config_file).save(training_repo_path="/tmp/repo")

    reloaded = Config(config_file)
    reloaded.load()

    assert reloaded.training_repo_path == "/tmp/repo"


def test_default_path_is_the_module_config_file():
    # (The hermetic conftest fixture points CONFIG_FILE into the test's tmp HOME.)
    assert Config().get_config_path() == str(config_module.CONFIG_FILE)
