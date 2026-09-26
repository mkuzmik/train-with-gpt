"""Unit tests for helpers.py (the git sync helpers are in test_git_sync.py)."""

from pathlib import Path

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from tests.support import as_oauth_user
from train_with_gpt.helpers import (
    calculate_zone_distribution,
    current_user_id,
    extract_note_headline,
    training_repo_not_configured_message,
    user_scoped_goals_file,
    user_scoped_notes_dir,
)


# --- user scoping -------------------------------------------------------------

def test_user_scoped_paths_for_oauth_user():
    repo = Path("/repo")
    assert user_scoped_notes_dir(repo, "42") == (repo / "notes" / "42", "notes/42")
    assert user_scoped_goals_file(repo, "42") == (repo / "goals" / "42.md", "goals/42.md")


def test_user_scoped_paths_for_personal_path():
    repo = Path("/repo")
    assert user_scoped_notes_dir(repo, None) == (repo / "notes", "notes")
    assert user_scoped_goals_file(repo, None) == (repo / "goals.md", "goals.md")


def test_current_user_id_is_none_without_an_authenticated_request():
    assert current_user_id() is None


def test_current_user_id_is_the_access_token_subject():
    token = AccessToken(token="t", client_id="claude", scopes=[], subject="1001")
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        assert current_user_id() == "1001"
    finally:
        auth_context_var.reset(reset)


def test_repo_not_configured_message_on_the_personal_path_points_to_setup():
    message = training_repo_not_configured_message()

    assert message.startswith("❌ Error: Training repository not configured.")
    assert "setup_training_repo" in message


def test_repo_not_configured_message_for_an_oauth_user_points_to_the_operator():
    with as_oauth_user("1001"):
        message = training_repo_not_configured_message()

    assert message.startswith("❌ Error: This server's notes storage isn't set up")
    assert "contact the server's operator" in message
    assert "setup_training_repo" not in message


# --- extract_note_headline ------------------------------------------------------

def test_headline_skips_standard_header_and_date():
    text = "# Consultation Notes\nDate: 2024-01-15 08:00:00\n\nDiscussed marathon plan.\n"
    assert extract_note_headline(text) == "Discussed marathon plan."


def test_headline_skips_banners_markdown_headers_and_caps_titles():
    text = (
        "# Consultation Notes\nDate: 2024-01-20\n\n"
        "========================================\nHEADLINE\n"
        "========================================\n## Summary\n"
        "Follow-up check-in, mileage on track.\n"
    )
    assert extract_note_headline(text) == "Follow-up check-in, mileage on track."


def test_headline_joins_prose_lines():
    assert extract_note_headline("First line.\nSecond line.\n") == "First line. Second line."


def test_headline_truncates_on_a_word_boundary():
    headline = extract_note_headline("alpha beta gamma " * 10, max_length=50)
    assert headline.endswith("…")
    assert len(headline) <= 51
    assert headline[:-1].split(" ")[-1] in ("alpha", "beta", "gamma")


def test_headline_placeholder_for_empty_note():
    assert extract_note_headline("# Consultation Notes\nDate: x\n\n") == "(no summary available)"


# --- calculate_zone_distribution --------------------------------------------------

def test_zone_distribution_buckets_each_sample():
    # Boundaries are zone upper bounds (inclusive); above the last is the top zone.
    assert calculate_zone_distribution([100, 120, 121, 150, 200, None], [120, 150]) == {1: 2, 2: 2, 3: 1}


def test_zone_distribution_empty_inputs():
    assert calculate_zone_distribution([], [120]) == {}
    assert calculate_zone_distribution([100], []) == {}
