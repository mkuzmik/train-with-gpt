"""Unit tests for the guidance tools: start_consultation and get_current_date."""

from datetime import datetime

from tests.support import text_of
from train_with_gpt.tools import get_current_date_handler, start_consultation_handler


async def test_start_consultation_points_at_the_context_tools():
    output = text_of(await start_consultation_handler({}))

    assert output.startswith("🏃 Starting Training Consultation Session")
    for tool in ("get_current_date", "read_goals", "list_consultation_notes", "read_consultation_notes",
                 "search_consultation_notes", "get_activities"):
        assert tool in output
    assert "coach" in output.lower()


def _formatted(moment: datetime) -> str:
    return moment.strftime(f"%A, %B {moment.day}, %Y (%Y-%m-%d)")


async def test_get_current_date_is_today():
    before = datetime.now()
    output = text_of(await get_current_date_handler({}))
    after = datetime.now()

    # (either side of the call, in case it straddled midnight)
    assert any(f"📅 Current date: {_formatted(moment)}\n" in output for moment in (before, after))
