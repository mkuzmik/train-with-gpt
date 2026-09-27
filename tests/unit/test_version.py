"""train_with_gpt.__version__ follows pyproject.toml (via package metadata), never a second copy."""

import importlib
import importlib.metadata

import train_with_gpt


def test_version_matches_installed_package():
    assert train_with_gpt.__version__ == importlib.metadata.version("train-with-gpt")


def test_version_is_read_from_package_metadata(monkeypatch):
    real_version = importlib.metadata.version

    def fake_version(name):
        return "9.8.7" if name == "train-with-gpt" else real_version(name)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    try:
        importlib.reload(train_with_gpt)
        assert train_with_gpt.__version__ == "9.8.7"
    finally:
        monkeypatch.undo()
        importlib.reload(train_with_gpt)
    assert train_with_gpt.__version__ == real_version("train-with-gpt")
