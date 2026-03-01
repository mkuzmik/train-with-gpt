"""Integration tests for setup_training_repo tool."""

import pytest
import tempfile
from pathlib import Path

from train_with_gpt.server import call_tool


@pytest.mark.asyncio
async def test_setup_training_repo_success():
    """Test successful repository setup."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        result = await call_tool("setup_training_repo", {
            "repo_path": str(repo_path)
        })
        
        assert len(result) == 1
        assert str(repo_path) in result[0].text
        assert "success" in result[0].text.lower() or "configured" in result[0].text.lower()


@pytest.mark.asyncio
async def test_setup_training_repo_not_exists():
    """Test setup with non-existent path."""
    result = await call_tool("setup_training_repo", {
        "repo_path": "/nonexistent/path/to/repo"
    })
    
    assert len(result) == 1
    assert "does not exist" in result[0].text.lower()


@pytest.mark.asyncio
async def test_setup_training_repo_not_git():
    """Test setup with non-git directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await call_tool("setup_training_repo", {
            "repo_path": tmpdir
        })
        
        assert len(result) == 1
        assert "not a git repository" in result[0].text.lower()
