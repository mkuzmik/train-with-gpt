"""Tests for MCP server tools."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from train_with_gpt.server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools():
    """Test that list_tools returns all expected tools."""
    tools = await list_tools()
    tool_names = [t.name for t in tools]
    
    assert "connect_strava" in tool_names
    assert "get_last_week_activities" in tool_names
    assert "analyze_activity" in tool_names
    assert "setup_training_repo" in tool_names
    assert "discuss_goals" in tool_names
    assert "save_goals" in tool_names
    assert "read_goals" in tool_names


@pytest.mark.asyncio
async def test_setup_training_repo_success():
    """Test setting up a training repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()
        git_dir = repo_path / ".git"
        git_dir.mkdir()
        
        with patch('train_with_gpt.server.config') as mock_config:
            result = await call_tool("setup_training_repo", {
                "repo_path": str(repo_path)
            })
            
            assert len(result) == 1
            assert "✅" in result[0].text
            assert str(repo_path) in result[0].text
            mock_config.save.assert_called_once_with(training_repo_path=str(repo_path))


@pytest.mark.asyncio
async def test_setup_training_repo_not_exists():
    """Test setting up a non-existent repository."""
    result = await call_tool("setup_training_repo", {
        "repo_path": "/nonexistent/path"
    })
    
    assert len(result) == 1
    assert "❌" in result[0].text
    assert "does not exist" in result[0].text


@pytest.mark.asyncio
async def test_setup_training_repo_not_git():
    """Test setting up a directory that's not a git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await call_tool("setup_training_repo", {
            "repo_path": tmpdir
        })
        
        assert len(result) == 1
        assert "❌" in result[0].text
        assert "Not a git repository" in result[0].text


@pytest.mark.asyncio
async def test_save_goals_without_repo_configured():
    """Test saving goals when no repository is configured."""
    with patch('train_with_gpt.server.config') as mock_config:
        mock_config.training_repo_path = None
        
        result = await call_tool("save_goals", {
            "goals_text": "Test goal"
        })
        
        assert len(result) == 1
        assert "❌" in result[0].text
        assert "not configured" in result[0].text


@pytest.mark.asyncio
async def test_save_goals_success():
    """Test successfully saving goals."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        with patch('train_with_gpt.server.config') as mock_config, \
             patch('subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            mock_run.return_value = MagicMock(returncode=0)
            
            result = await call_tool("save_goals", {
                "goals_text": "Run 5k in under 20 minutes"
            })
            
            assert len(result) == 1
            assert "✅" in result[0].text
            
            # Verify file was written
            goals_file = repo_path / "goals.md"
            assert goals_file.exists()
            content = goals_file.read_text()
            assert "Run 5k in under 20 minutes" in content
            assert "Training Goals" in content


@pytest.mark.asyncio
async def test_read_goals_without_repo_configured():
    """Test reading goals when no repository is configured."""
    with patch('train_with_gpt.server.config') as mock_config:
        mock_config.training_repo_path = None
        
        result = await call_tool("read_goals", {})
        
        assert len(result) == 1
        assert "❌" in result[0].text
        assert "not configured" in result[0].text


@pytest.mark.asyncio
async def test_read_goals_file_not_exists():
    """Test reading goals when file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        with patch('train_with_gpt.server.config') as mock_config, \
             patch('subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr=b"no tracking information"
            )
            
            result = await call_tool("read_goals", {})
            
            assert len(result) == 1
            assert "No goals saved yet" in result[0].text


@pytest.mark.asyncio
async def test_read_goals_success():
    """Test successfully reading goals."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        goals_file = repo_path / "goals.md"
        goals_file.write_text("# Training Goals\n\nRun 5k in under 20 minutes")
        
        with patch('train_with_gpt.server.config') as mock_config, \
             patch('subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            # Make git pull raise CalledProcessError with "no tracking" message
            mock_run.side_effect = [
                MagicMock(returncode=1, stderr="no tracking information for the current branch")
            ]
            
            result = await call_tool("read_goals", {})
            
            assert len(result) == 1
            assert "Training Goals" in result[0].text
            assert "Run 5k in under 20 minutes" in result[0].text


@pytest.mark.asyncio
async def test_discuss_goals_returns_guidance():
    """Test that discuss_goals returns guidance text."""
    result = await call_tool("discuss_goals", {})
    
    assert len(result) == 1
    assert "Training Goal Setting Framework" in result[0].text
    assert "get_last_week_activities" in result[0].text
    assert "ASK ONE QUESTION AT A TIME" in result[0].text
