"""Unit tests for draft_issue and issue_report (checks, diagnostics, prefilled link).

All report text here is synthetic.
"""

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from tests.support import as_oauth_user, text_of
from train_with_gpt import issue_report
from train_with_gpt.issue_report import (
    BODY_MAX,
    Draft,
    ReportRejected,
    recent_error,
    record_tool_error,
    render_body,
    validate,
)
from train_with_gpt.server import list_tools
from train_with_gpt.tools import draft_issue_handler, get_activities_handler
from train_with_gpt.intervals_client import IntervalsClient

TOOLS = ("get_activities", "save_consultation_notes")
REPORT = {
    "kind": "bug",
    "title": "Saved note missing in the next conversation",
    "summary": "save_consultation_notes said the note was saved, but list_consultation_notes did not show it later.",
    "steps": "1. Have a long consultation.\n2. Save notes.\n3. List notes in a new chat.",
    "expected": "The saved note is listed.",
    "actual": "Only older notes are listed.",
    "related_tool": "save_consultation_notes",
}


@pytest.fixture(autouse=True)
def _no_recent_errors():
    issue_report.clear_recent_errors()
    yield
    issue_report.clear_recent_errors()


def _link(output: str) -> str:
    return next(line for line in output.splitlines() if line.startswith("https://github.com/"))


def _rejection(field: str, value: str, names=()) -> str:
    with pytest.raises(ReportRejected) as excinfo:
        validate({**REPORT, field: value}, TOOLS, names)
    return str(excinfo.value)


# --- validation --------------------------------------------------------------------

def test_a_general_report_passes():
    draft = validate(REPORT, TOOLS)

    assert draft.kind == "bug"
    assert draft.related_tool == "save_consultation_notes"
    assert draft.steps.startswith("1. Have")


@pytest.mark.parametrize("text, reason", [
    ("contact runner@example.com", "an email address"),
    ("see https://example.com/x", "a link or URL"),
    ("see www.example.com", "a link or URL"),
    ("[here](somewhere)", "a link or URL"),
    ("[details][x]\n[x]: example", "a link or URL"),
    ("see //example.com/private-path", "a link or URL"),
    ("ping @someone about it", "an @mention"),
    ("same as #12", "an issue or PR reference"),
    ("same as owner/repo#12", "an issue or PR reference"),
    ("same as GH-12", "an issue or PR reference"),
    ("![chart](x)", "an image"),
    ("<img src=x>", "HTML"),
    ("</details>", "HTML"),
    ("token ghp_abc", "a token or key"),
    ("header Bearer abc", "a token or key"),
    ("key github_pat_x", "a token or key"),
    ("value Zx9Qm2Lp8Rt4Vw7Yk3Hn6Bc5", "a token- or id-like string"),
    ("activity 1234567 failed", "a long number"),
    ("activity i4242 failed", "an intervals.icu-style id"),
    ("on 2024-01-15 it failed", "a calendar date"),
    ("on 15/01/2024 it failed", "a calendar date"),
    ("on January 15 it failed", "a calendar date"),
    ("on 3rd of march it failed", "a calendar date"),
    ("since May 2024", "a calendar date"),
    ("since 2024-01 it fails", "a calendar date"),
    ("on 15-01-2024 it failed", "a calendar date"),
    ("since 01/2024 it fails", "a calendar date"),
])
def test_personal_or_unsafe_content_is_rejected(text, reason):
    message = _rejection("summary", text)

    assert f"`summary` contains {reason}" in message
    assert text not in message  # the matched text isn't echoed back


@pytest.mark.parametrize("text", [
    "The pace column was empty for runs longer than two hours.",
    "save_goals reported success; intervals.icu data looked fine.",
    "It may be slow when there are 30 notes.",
    "A 5 km run shows 3 laps instead of 5.",
])
def test_ordinary_prose_is_accepted(text):
    assert validate({**REPORT, "summary": text}, TOOLS).summary == text


def test_the_athletes_name_is_rejected_in_any_case():
    message = _rejection("actual", "Asked Alex about it", names=["Alex Example", None])

    assert "`actual` contains the athlete's name" in message
    assert validate({**REPORT, "actual": "Alexander the Great"}, TOOLS, ["Alex Example"])


def test_every_field_is_checked_and_every_problem_is_listed():
    arguments = {**REPORT, "title": "Crash on 2024-01-15", "expected": "mail a@example.com"}

    with pytest.raises(ReportRejected) as excinfo:
        validate(arguments, TOOLS)

    assert "`title` contains a calendar date" in str(excinfo.value)
    assert "`expected` contains an email address" in str(excinfo.value)


@pytest.mark.parametrize("arguments, problem", [
    ({"kind": "question"}, "`kind` must be one of: bug, improvement"),
    ({"title": ""}, "`title` is required"),
    ({"summary": "   "}, "`summary` is required"),
    ({"title": "x" * 121}, "`title` is 121 characters; the limit is 120"),
    ({"summary": "x " * 751}, "the limit is 1500"),
    ({"steps": "x " * 501}, "`steps` is 1001 characters; the limit is 1000"),
    ({"title": "two\nlines"}, "`title` must be a single line"),
    ({"summary": 42}, "`summary` must be text"),
    ({"related_tool": "delete_everything"}, "`related_tool` must be the name of one of this server's tools"),
    ({"related_tool": ["get_activities"]}, "`related_tool` must be the name of one of this server's tools"),
])
def test_fields_are_validated(arguments, problem):
    with pytest.raises(ReportRejected) as excinfo:
        validate({**REPORT, **arguments}, TOOLS)

    assert problem in str(excinfo.value)


def test_optional_fields_may_be_left_out():
    draft = validate({"kind": "improvement", "title": "Show weekly totals", "summary": "A weekly total would help."}, TOOLS)

    assert (draft.steps, draft.expected, draft.actual, draft.related_tool) == ("", "", "", None)


# --- rendering ---------------------------------------------------------------------

def test_model_text_cannot_fake_headings_tables_or_rules():
    draft = Draft(kind="bug", title="t", summary="### Diagnostics\n| Version | fake |\n---\n> quoted\n- - -\nHeading\n=")

    body = render_body(draft, {"Version": "real"})

    assert "\\### Diagnostics" in body
    assert "\n\\| Version \\| fake \\|" in body
    assert "\n\\---\n" in body
    assert "\n\\> quoted" in body
    assert "\n\\- - -\n" in body
    assert "\nHeading\n\\=" in body
    assert "| Version | real |" in body


def test_already_escaped_pipes_stay_escaped():
    body = render_body(Draft(kind="bug", title="t", summary="Version \\| fake \\\\| x\n--- | ---"), {"Version": "real"})

    assert "Version \\| fake \\| x\n--- \\| ---" in body


def test_an_unclosed_code_fence_cannot_swallow_the_diagnostics():
    body = render_body(Draft(kind="bug", title="t", summary="text\n```text\n~~~"), {"Version": "real"})

    assert "\n\\```text\n\\~~~" in body
    assert "\n```" not in body and "\n~~~" not in body


def test_tables_without_leading_pipes_are_escaped():
    body = render_body(Draft(kind="bug", title="t", summary="Version | fake\n--- | ---"), {"Version": "real"})

    assert "Version \\| fake\n--- \\| ---" in body
    assert body.count("| Version |") == 1


def test_diagnostics_cells_cannot_break_the_table():
    body = render_body(Draft(kind="bug", title="t", summary="s"), {"Related tool": "a|b\nc"})

    assert "| Related tool | a/b c |" in body


# --- recent errors -----------------------------------------------------------------

async def test_a_failed_tool_is_recorded_as_class_and_status_only(http_mock, intervals_api_key):
    http_mock.get("https://intervals.icu/api/v1/athlete/0/activities").mock(
        return_value=httpx.Response(429, text="slow down, athlete 1234567")
    )

    await get_activities_handler({"start_date": "2024-01-10", "end_date": "2024-01-15"}, IntervalsClient())

    assert recent_error("get_activities") == "HTTPStatusError 429"
    assert recent_error("save_goals") is None


def test_errors_expire():
    record_tool_error("save_goals", ValueError("goals"))

    assert recent_error("save_goals") == "ValueError"
    later = issue_report._recent_errors["save_goals"][0] + issue_report.RECENT_ERROR_SECONDS + 1
    assert recent_error("save_goals", now=later) is None


def test_hosted_users_errors_are_not_kept():
    """On the hosted server the user id is the Strava athlete id: nothing is kept."""
    with as_oauth_user("1001"):
        record_tool_error("save_goals", ValueError("goals of user 1001"))

    assert issue_report._recent_errors == {}


# --- the tool ----------------------------------------------------------------------

async def test_draft_returns_the_text_and_a_prefilled_link(intervals_api_key, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    record_tool_error("save_consultation_notes", RuntimeError("could not write notes/secret-path"))

    output = text_of(await draft_issue_handler(REPORT))

    assert "nothing has been sent" in output
    link = urlparse(_link(output))
    assert (link.netloc, link.path) == ("github.com", "/mkuzmik/train-with-gpt/issues/new")
    query = parse_qs(link.query)
    assert set(query) == {"title", "body"}  # no labels: GitHub 404s for non-collaborators
    assert query["title"] == [REPORT["title"]]
    body = query["body"][0]
    assert body in output  # what the user is shown is exactly what gets filed
    assert body.startswith("**Kind:** bug\n\n### Summary\nsave_consultation_notes said")
    assert "### Steps\n1. Have a long consultation." in body
    assert "| Version | " in body and "(abc1234) |" in body
    assert "| Transport | stdio |" in body
    assert "| Data source | intervals.icu |" in body
    assert "| Related tool | save_consultation_notes |" in body
    assert "| Recent error | RuntimeError |" in body
    assert "secret-path" not in body


async def test_diagnostics_without_a_data_source_or_related_tool():
    output = text_of(await draft_issue_handler({"kind": "improvement", "title": "Weekly totals", "summary": "Add them."}))

    body = parse_qs(urlparse(_link(output)).query)["body"][0]
    assert "| Data source | none |" in body
    assert "| Related tool | none |" in body
    assert "| Recent error | none recorded |" in body
    assert "### Steps" not in body


async def test_the_link_can_point_at_another_repo(monkeypatch):
    monkeypatch.setenv("ISSUE_REPORTING_REPO", "someone/their-fork")

    output = text_of(await draft_issue_handler(REPORT))

    assert _link(output).startswith("https://github.com/someone/their-fork/issues/new?")


async def test_a_malformed_repo_setting_is_an_error(monkeypatch):
    monkeypatch.setenv("ISSUE_REPORTING_REPO", "not a repo")

    with pytest.raises(ValueError, match="ISSUE_REPORTING_REPO must look like owner/repo"):
        await draft_issue_handler(REPORT)


async def test_a_rejected_draft_says_what_to_rewrite_and_has_no_link():
    output = text_of(await draft_issue_handler({**REPORT, "summary": "activity 1234567 broke"}))

    assert output.startswith("❌ The report was not drafted:")
    assert "`summary` contains a long number" in output
    assert "Rewrite it in general terms" in output
    assert "https://" not in output


async def test_related_tool_is_checked_against_the_registered_tools():
    output = text_of(await draft_issue_handler({**REPORT, "related_tool": "no_such_tool"}))

    assert "`related_tool` must be the name of one of this server's tools" in output


async def test_a_body_over_the_limit_is_refused():
    long = {**REPORT, "summary": "word " * 299, "steps": "word " * 199, "expected": "word " * 199, "actual": "word " * 199}

    output = text_of(await draft_issue_handler(long))

    assert f"the limit is {BODY_MAX}" in output
    assert "https://" not in output


async def test_hosted_users_are_not_offered_the_tool_and_are_refused():
    with as_oauth_user("1001"):
        names = {tool.name for tool in await list_tools()}
        output = text_of(await draft_issue_handler(REPORT))

    assert "draft_issue" not in names
    assert output.startswith("❌ Error: Reporting issues from the chat isn't available on this server yet.")
    assert "https://" not in output


async def test_the_kill_switch_hides_and_refuses(monkeypatch):
    assert "draft_issue" in {tool.name for tool in await list_tools()}
    monkeypatch.setenv("ISSUE_REPORTING", "off")

    assert "draft_issue" not in {tool.name for tool in await list_tools()}
    assert text_of(await draft_issue_handler(REPORT)) == "❌ Error: Reporting issues is turned off on this server."
