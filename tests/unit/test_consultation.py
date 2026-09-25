"""Integration tests for start_consultation and get_current_date tools."""

import pytest
import re

from train_with_gpt.server import call_tool


@pytest.mark.asyncio
async def test_start_consultation():
    """Test that start_consultation provides coaching instructions."""
    result = await call_tool("start_consultation", {})
    
    assert len(result) == 1
    output = result[0].text
    
    # Should include instructions
    assert "consultation" in output.lower()
    assert "get_current_date" in output
    assert "read_goals" in output
    assert "read_consultation_notes" in output
    # Should mention coaching role
    assert "coach" in output.lower() or "role" in output.lower()


@pytest.mark.asyncio
async def test_get_current_date():
    """Test get_current_date returns valid date information."""
    result = await call_tool("get_current_date", {})
    
    assert len(result) == 1
    output = result[0].text
    
    # Should contain date in YYYY-MM-DD format
    assert re.search(r'\d{4}-\d{2}-\d{2}', output)
    
    # Should contain day of week
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    assert any(day in output for day in days)
