"""Tests for MCP server tools.

IMPORTANT: When modifying or adding tools, update these tests!

Test Coverage:
- Tool listing (test_list_tools)
- setup_training_repo: success, validation errors
- save_goals: success, missing repo, git operations
- read_goals: success, missing repo, missing file, git pull
- discuss_goals: guidance content
- save_consultation_notes: success, missing repo, git operations
- read_consultation_notes: success, missing repo, limit parameter

When adding a new tool:
1. Add tool name to test_list_tools
2. Add test_{tool_name}_success for happy path
3. Add test_{tool_name}_error_case for each error condition
4. Mock all external dependencies (httpx, subprocess, filesystem)
5. Use temporary directories for file operations

See TESTING.md for detailed guidelines.
"""

import json
import subprocess
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
    assert "save_consultation_notes" in tool_names
    assert "read_consultation_notes" in tool_names


@pytest.mark.asyncio
async def test_setup_training_repo_success():
    """Test setting up a training repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "test-repo"
        repo_path.mkdir()
        git_dir = repo_path / ".git"
        git_dir.mkdir()
        
        with patch('train_with_gpt.tools.setup_training_repo.config') as mock_config:
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
    with patch('train_with_gpt.tools.save_goals.config') as mock_config:
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
        
        with patch('train_with_gpt.tools.save_goals.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
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
    with patch('train_with_gpt.tools.read_goals.config') as mock_config:
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
        
        with patch('train_with_gpt.tools.read_goals.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
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
        
        with patch('train_with_gpt.tools.read_goals.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            # Make git pull raise CalledProcessError with "no tracking" message
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git', 'pull'], stderr=b"no tracking information for the current branch")
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


@pytest.mark.asyncio
async def test_save_consultation_notes_without_repo_configured():
    """Test saving consultation notes when no repository is configured."""
    with patch('train_with_gpt.tools.save_consultation_notes.config') as mock_config:
        mock_config.training_repo_path = None
        
        result = await call_tool("save_consultation_notes", {
            "notes": "Test consultation"
        })
        
        assert len(result) == 1
        assert "❌" in result[0].text
        assert "not configured" in result[0].text


@pytest.mark.asyncio
async def test_save_consultation_notes_success():
    """Test successfully saving consultation notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        with patch('train_with_gpt.tools.save_consultation_notes.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            mock_run.return_value = MagicMock(returncode=0)
            
            result = await call_tool("save_consultation_notes", {
                "notes": "Discussed interval training plan"
            })
            
            assert len(result) == 1
            assert "✅" in result[0].text
            assert "Consultation notes saved" in result[0].text
            
            # Verify notes directory was created
            notes_dir = repo_path / "notes"
            assert notes_dir.exists()
            
            # Verify a timestamped file was created
            note_files = list(notes_dir.glob("*.md"))
            assert len(note_files) == 1
            
            # Verify content
            content = note_files[0].read_text()
            assert "Consultation Notes" in content
            assert "Discussed interval training plan" in content


@pytest.mark.asyncio
async def test_read_consultation_notes_without_repo_configured():
    """Test reading consultation notes when no repository is configured."""
    with patch('train_with_gpt.tools.read_consultation_notes.config') as mock_config:
        mock_config.training_repo_path = None
        
        result = await call_tool("read_consultation_notes", {})
        
        assert len(result) == 1
        assert "❌" in result[0].text
        assert "not configured" in result[0].text


@pytest.mark.asyncio
async def test_read_consultation_notes_no_notes():
    """Test reading consultation notes when none exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        
        with patch('train_with_gpt.tools.read_consultation_notes.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git', 'pull'], stderr=b"no tracking information")
            ]
            
            result = await call_tool("read_consultation_notes", {})
            
            assert len(result) == 1
            assert "No consultation notes saved yet" in result[0].text


@pytest.mark.asyncio
async def test_read_consultation_notes_success():
    """Test successfully reading consultation notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        notes_dir = repo_path / "notes"
        notes_dir.mkdir()
        
        # Create test notes
        note1 = notes_dir / "2026-01-01-10-00-00.md"
        note1.write_text("# Consultation Notes\nDate: 2026-01-01 10:00:00\n\nFirst consultation")
        
        note2 = notes_dir / "2026-01-02-10-00-00.md"
        note2.write_text("# Consultation Notes\nDate: 2026-01-02 10:00:00\n\nSecond consultation")
        
        with patch('train_with_gpt.tools.read_consultation_notes.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            # Mock git pull to return CalledProcessError with "no tracking" message
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git', 'pull'], stderr=b"no tracking information")
            ]
            
            result = await call_tool("read_consultation_notes", {})
            
            assert len(result) == 1
            assert "Found 2 consultation note(s)" in result[0].text
            assert "First consultation" in result[0].text
            assert "Second consultation" in result[0].text
            # Most recent should be first
            first_pos = result[0].text.find("Second consultation")
            second_pos = result[0].text.find("First consultation")
            assert first_pos < second_pos


@pytest.mark.asyncio
async def test_read_consultation_notes_with_limit():
    """Test reading consultation notes with limit parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        notes_dir = repo_path / "notes"
        notes_dir.mkdir()
        
        # Create 3 test notes
        for i in range(3):
            note = notes_dir / f"2026-01-0{i+1}-10-00-00.md"
            note.write_text(f"# Consultation Notes\nDate: 2026-01-0{i+1}\n\nConsultation {i+1}")
        
        with patch('train_with_gpt.tools.read_consultation_notes.config') as mock_config, \
             patch('train_with_gpt.helpers.subprocess.run') as mock_run:
            mock_config.training_repo_path = str(repo_path)
            # Mock git pull to return CalledProcessError with "no tracking" message
            mock_run.side_effect = [
                subprocess.CalledProcessError(1, ['git', 'pull'], stderr=b"no tracking information")
            ]
            
            result = await call_tool("read_consultation_notes", {"limit": 2})
            
            assert len(result) == 1
            assert "Found 2 consultation note(s) (showing 2 most recent)" in result[0].text
            assert "Consultation 3" in result[0].text
            assert "Consultation 2" in result[0].text
            assert "Consultation 1" not in result[0].text

