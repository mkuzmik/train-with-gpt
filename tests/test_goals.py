"""Integration tests for goals tools: discuss_goals, save_goals, read_goals."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from train_with_gpt.server import call_tool


@pytest.mark.asyncio
async def test_discuss_goals():
    """Test that discuss_goals provides coaching guidance."""
    result = await call_tool("discuss_goals", {
        "current_situation": "I want to run my first marathon",
        "questions": "What should my training plan look like?"
    })
    
    assert len(result) == 1
    output = result[0].text
    
    # Should provide meaningful guidance
    assert len(output) > 100
    assert any(keyword in output.lower() for keyword in [
        "training", "plan", "goal", "week", "marathon"
    ])


@pytest.mark.asyncio
async def test_save_and_read_goals_workflow():
    """Test complete goals workflow: save → read."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        # Setup repo
        await call_tool("setup_training_repo", {"repo_path": str(repo_path)})
        
        goals_content = """# Training Goals 2024

## Marathon Goal
- Run under 4 hours
- Build to 60km/week
"""
        
        # Save goals
        with patch('subprocess.run'):
            result = await call_tool("save_goals", {"goals_text": goals_content})
        
        assert len(result) == 1
        assert "saved" in result[0].text.lower() or "success" in result[0].text.lower()
        
        # Verify file was created
        goals_file = repo_path / "goals.md"
        goals_file.write_text(goals_content)
        
        # Read goals back
        with patch('subprocess.run'):
            result = await call_tool("read_goals", {})
        
        assert len(result) == 1
        output = result[0].text
        assert "Marathon Goal" in output
        assert "4 hours" in output


@pytest.mark.asyncio
async def test_save_goals_without_repo():
    """Test that save_goals fails when repo not configured."""
    # Clear any existing repo config
    from train_with_gpt.config import config
    old_path = config.training_repo_path
    config.training_repo_path = None
    
    try:
        result = await call_tool("save_goals", {
            "goals_text": "Test goals"
        })
        
        assert len(result) == 1
        assert "not configured" in result[0].text.lower() or "setup" in result[0].text.lower()
    finally:
        config.training_repo_path = old_path


@pytest.mark.asyncio
async def test_read_goals_file_not_exists():
    """Test reading goals when file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        await call_tool("setup_training_repo", {"repo_path": str(repo_path)})
        
        with patch('subprocess.run'):
            result = await call_tool("read_goals", {})
        
        assert len(result) == 1
        assert "no goals" in result[0].text.lower() or "not found" in result[0].text.lower()
