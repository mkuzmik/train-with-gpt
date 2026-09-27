"""The app's version: the release tag from TRAIN_WITH_GPT_VERSION, else a "+dev" placeholder."""

import importlib
import importlib.metadata

import train_with_gpt
from train_with_gpt import app_version

PLACEHOLDER = importlib.metadata.version("train-with-gpt")


def test_release_tag_from_env(monkeypatch):
    monkeypatch.setenv("TRAIN_WITH_GPT_VERSION", " v1.4.2\n")

    assert app_version() == "v1.4.2"


def test_without_env_the_package_version_is_marked_dev(monkeypatch):
    monkeypatch.delenv("TRAIN_WITH_GPT_VERSION", raising=False)

    assert app_version() == f"{PLACEHOLDER}+dev"


def test_blank_env_counts_as_unset(monkeypatch):
    monkeypatch.setenv("TRAIN_WITH_GPT_VERSION", "  ")

    assert app_version() == f"{PLACEHOLDER}+dev"


def test_dunder_version_follows_the_env_at_import(monkeypatch):
    monkeypatch.setenv("TRAIN_WITH_GPT_VERSION", "v3.2.1")
    try:
        importlib.reload(train_with_gpt)
        assert train_with_gpt.__version__ == "v3.2.1"
    finally:
        monkeypatch.undo()
        importlib.reload(train_with_gpt)
    assert train_with_gpt.__version__ == f"{PLACEHOLDER}+dev"
