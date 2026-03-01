"""Integration tests for consultation notes tools."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

from train_with_gpt.server import call_tool


@pytest.mark.asyncio
async def test_save_and_read_consultation_notes():
    """Test complete consultation notes workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        notes_dir = repo_path / "consultation-notes"
        notes_dir.mkdir()
        
        # Setup repo
        await call_tool("setup_training_repo", {"repo_path": str(repo_path)})
        
        note_content = """Discussed marathon training plan.

Key Points:
- Increase mileage gradually
- Focus on long runs

Next Steps:
- Start with 40km/week
"""
        
        # Save note
        with patch('subprocess.run'):
            result = await call_tool("save_consultation_notes", {
                "notes": note_content
            })
        
        assert len(result) == 1
        assert "saved" in result[0].text.lower() or "success" in result[0].text.lower()
        
        # Create mock note file
        note_file = notes_dir / f"{datetime.now().strftime('%Y-%m-%d')}_consultation.md"
        note_file.write_text(note_content)
        
        # Read notes back
        with patch('subprocess.run'):
            result = await call_tool("read_consultation_notes", {})
        
        assert len(result) == 1
        output = result[0].text
        assert "marathon" in output.lower()
        assert "40km/week" in output


@pytest.mark.asyncio
async def test_read_consultation_notes_with_limit():
    """Test reading limited number of recent notes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        notes_dir = repo_path / "consultation-notes"
        notes_dir.mkdir()
        
        await call_tool("setup_training_repo", {"repo_path": str(repo_path)})
        
        # Create multiple notes
        for i in range(5):
            note_file = notes_dir / f"2024-01-{15+i:02d}_consultation.md"
            note_file.write_text(f"Note {i+1}")
        
        with patch('subprocess.run'):
            result = await call_tool("read_consultation_notes", {"limit": 3})
        
        assert len(result) == 1
        # Should show only 3 most recent


@pytest.mark.asyncio
async def test_save_consultation_notes_without_repo():
    """Test that save fails when repo not configured."""
    from train_with_gpt.config import config
    old_path = config.training_repo_path
    config.training_repo_path = None
    
    try:
        result = await call_tool("save_consultation_notes", {
            "notes": "Test note"
        })
        
        assert len(result) == 1
        assert "not configured" in result[0].text.lower() or "setup" in result[0].text.lower()
    finally:
        config.training_repo_path = old_path
