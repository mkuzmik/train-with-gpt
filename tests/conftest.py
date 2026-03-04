"""Shared test fixtures."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def training_repo():
    """Create a temporary training repository and configure it."""
    from train_with_gpt.config import config
    
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        # Save original value
        old_repo_path = config.training_repo_path
        
        # Set the repo path for tests (don't save to disk)
        config.training_repo_path = str(repo_path)
        
        try:
            yield repo_path
        finally:
            # Restore original value
            config.training_repo_path = old_repo_path
