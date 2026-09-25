"""Tests for configuration management.

IMPORTANT: Config is global state - tests must be isolated!

Test Coverage:
- Initialization with None values
- Save and load operations
- File-based configuration
- Environment variable overrides

When adding new config fields:
1. Update test_config_initialization to check new field
2. Update test_config_save_and_load to test saving new field
3. Update test_config_load_from_file to test loading new field
4. If field can be overridden by env var, add to test_config_env_vars_override_file

Always use temporary directories and patch CONFIG_FILE to avoid modifying real config.

See TESTING.md for detailed guidelines.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from train_with_gpt.config import Config


def test_config_initialization():
    """Test that Config initializes with None values."""
    config = Config()
    assert config.intervals_api_key is None
    assert config.training_repo_path is None


def test_config_save_and_load():
    """Test saving and loading configuration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.json"

        with patch('train_with_gpt.config.CONFIG_FILE', config_file):
            config = Config()

            # Save config
            config.save(
                intervals_api_key="test_key",
                training_repo_path="/tmp/test"
            )

            # Verify file was created
            assert config_file.exists()

            # Load config
            with open(config_file, 'r') as f:
                data = json.load(f)

            assert data["intervalsApiKey"] == "test_key"
            assert data["trainingRepoPath"] == "/tmp/test"


def test_config_load_from_file():
    """Test loading configuration from file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.json"
        config_dir = Path(tmpdir)

        # Create config file
        config_data = {
            "intervalsApiKey": "file_key",
            "trainingRepoPath": "/tmp/training"
        }

        with open(config_file, 'w') as f:
            json.dump(config_data, f)

        with patch('train_with_gpt.config.CONFIG_FILE', config_file), \
             patch('train_with_gpt.config.CONFIG_DIR', config_dir):
            config = Config()
            config.load()

            assert config.intervals_api_key == "file_key"
            assert config.training_repo_path == "/tmp/training"


def test_config_env_vars_override_file():
    """Test that environment variables override config file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.json"
        config_dir = Path(tmpdir)

        # Create config file
        config_data = {
            "intervalsApiKey": "file_key",
        }

        with open(config_file, 'w') as f:
            json.dump(config_data, f)

        with patch('train_with_gpt.config.CONFIG_FILE', config_file), \
             patch('train_with_gpt.config.CONFIG_DIR', config_dir), \
             patch.dict('os.environ', {
                 'INTERVALS_API_KEY': 'env_key',
             }):
            config = Config()
            config.load()

            # Env vars should override file
            assert config.intervals_api_key == "env_key"
