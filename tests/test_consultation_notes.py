"""Integration tests for consultation notes tools."""

import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

from train_with_gpt.server import call_tool


@pytest.mark.asyncio
async def test_save_and_read_consultation_notes(training_repo):
    """Test complete consultation notes workflow."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

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

    # Read notes back (explicit full-history read)
    with patch('subprocess.run'):
        result = await call_tool("read_consultation_notes", {"all": True})

    assert len(result) == 1
    output = result[0].text
    assert "marathon" in output.lower()
    assert "40km/week" in output


@pytest.mark.asyncio
async def test_read_consultation_notes_no_range_returns_guidance(training_repo):
    """Calling without since/until/note_date/all should not dump everything."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

    for i in range(3):
        note_file = notes_dir / f"2024-01-{15+i:02d}_consultation.md"
        note_file.write_text(f"Note {i+1}")

    with patch('subprocess.run'):
        result = await call_tool("read_consultation_notes", {})

    assert len(result) == 1
    output = result[0].text
    assert "list_consultation_notes" in output
    for i in range(3):
        assert f"Note {i+1}" not in output


@pytest.mark.asyncio
async def test_read_consultation_notes_all(training_repo):
    """Test that all=true returns every note."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

    # Create multiple notes
    for i in range(8):
        note_file = notes_dir / f"2024-01-{15+i:02d}_consultation.md"
        note_file.write_text(f"Note {i+1}")

    with patch('subprocess.run'):
        result = await call_tool("read_consultation_notes", {"all": True})

    assert len(result) == 1
    output = result[0].text
    # Should show all 8 notes
    assert "Found 8 consultation note(s)" in output
    # Verify all notes are present
    for i in range(8):
        assert f"Note {i+1}" in output


@pytest.mark.asyncio
async def test_read_consultation_notes_since_until_range(training_repo):
    """Test that since/until filters to the matching date range only."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

    for i in range(8):
        note_file = notes_dir / f"2024-01-{15+i:02d}_consultation.md"
        note_file.write_text(f"Note {i+1}")

    with patch('subprocess.run'):
        result = await call_tool("read_consultation_notes", {
            "since": "2024-01-17",
            "until": "2024-01-19",
        })

    assert len(result) == 1
    output = result[0].text
    assert "Found 3 consultation note(s)" in output
    # 2024-01-17, 18, 19 -> Note 3, 4, 5
    for i in (2, 3, 4):
        assert f"Note {i+1}" in output
    for i in (0, 1, 5, 6, 7):
        assert f"Note {i+1}" not in output


@pytest.mark.asyncio
async def test_read_consultation_notes_note_date(training_repo):
    """Test that note_date returns only the note(s) from that exact date."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

    for i in range(3):
        note_file = notes_dir / f"2024-01-{15+i:02d}_consultation.md"
        note_file.write_text(f"Note {i+1}")

    with patch('subprocess.run'):
        result = await call_tool("read_consultation_notes", {"note_date": "2024-01-16"})

    assert len(result) == 1
    output = result[0].text
    assert "Found 1 consultation note(s)" in output
    assert "Note 2" in output
    assert "Note 1" not in output
    assert "Note 3" not in output


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


@pytest.mark.asyncio
async def test_list_consultation_notes(training_repo):
    """Test that list_consultation_notes returns a dated index with headlines."""
    repo_path = training_repo
    notes_dir = repo_path / "notes"
    notes_dir.mkdir()

    (notes_dir / "2024-01-15-08-00-00.md").write_text(
        "# Consultation Notes\nDate: 2024-01-15 08:00:00\n\nDiscussed marathon training plan and mileage buildup.\n"
    )
    (notes_dir / "2024-01-20-08-00-00.md").write_text(
        "# Consultation Notes\nDate: 2024-01-20 08:00:00\n\n"
        "========================================\nHEADLINE\n========================================\n"
        "Follow-up check-in, mileage on track.\n"
    )

    with patch('subprocess.run'):
        result = await call_tool("list_consultation_notes", {})

    assert len(result) == 1
    output = result[0].text
    assert "2 consultation note(s)" in output
    assert "spanning 2024-01-15 to 2024-01-20" in output
    assert "2024-01-15 —" in output
    assert "2024-01-20 —" in output
    assert "marathon training plan" in output
    assert "Follow-up check-in" in output


@pytest.mark.asyncio
async def test_list_consultation_notes_no_repo():
    """Test that list fails cleanly when repo not configured."""
    from train_with_gpt.config import config
    old_path = config.training_repo_path
    config.training_repo_path = None

    try:
        result = await call_tool("list_consultation_notes", {})
        assert len(result) == 1
        assert "not configured" in result[0].text.lower() or "setup" in result[0].text.lower()
    finally:
        config.training_repo_path = old_path
