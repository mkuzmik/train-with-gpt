"""Unit tests for activity-source helpers."""

import pytest

from train_with_gpt.activity_source import strava_id_error


@pytest.mark.parametrize("activity_id", ["123", 123, " 123 ", "+123"])
def test_ids_int_accepts_are_strava_ids(activity_id):
    """Same rule the Strava paths had before: whatever int() parses."""
    assert strava_id_error(activity_id) is None


@pytest.mark.parametrize("activity_id", ["i123", "²", "", "12a"])
def test_ids_int_rejects_get_the_source_hint(activity_id):
    assert "source='intervals_icu'" in strava_id_error(activity_id)
