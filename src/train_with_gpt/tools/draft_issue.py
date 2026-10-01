"""draft_issue tool: a bug report or improvement idea about the connector.

Personal (stdio) server: it returns a GitHub link with the report prefilled,
and the user files it under their own account.

Hosted server: hosted users may not have a GitHub account and shouldn't file
publicly under their name, so the report is saved privately in the server's
training repo (reports/<timestamp>-<random>.md), where the operator triages
it and, when warranted, writes a public issue. No GitHub token is needed. The
path and the text carry no user id: on the hosted server it is the Strava
athlete id, which isn't stored anywhere new (Strava API policy). See #32.
"""

import asyncio
import secrets
import sys
from datetime import datetime
from pathlib import Path

from mcp.types import TextContent, Tool

from ..config import config
from ..helpers import (
    GitSyncError,
    current_user_id,
    git_save_file,
    save_error_for_caller,
    save_status_for_caller,
)
from ..issue_report import (
    BODY_MAX,
    URL_MAX,
    KINDS,
    ReportRejected,
    issue_repo,
    prefilled_issue_url,
    recent_error,
    render_body,
    reporting_enabled,
    validate,
    version_string,
)


# Saved reports per hosted user per day.
HOSTED_REPORTS_PER_DAY = 5


def draft_issue_available() -> bool:
    """Whether list_tools offers draft_issue."""
    return reporting_enabled()


def draft_issue_tool() -> Tool:
    """Return the draft_issue tool definition."""
    return Tool(
        name="draft_issue",
        description=(
            "Report a bug or suggest an improvement about this connector (not about training). "
            "On a personal (local) server it returns the exact text and a link that opens "
            "GitHub's new-issue form with it filled in: nothing is sent, the user files it under "
            "their own GitHub account, and the issue is PUBLIC. On a hosted server it saves the "
            "report privately for the server's operator, who may turn it into a public issue.\n\n"
            "Use it when the user asks to report a problem or suggest an improvement. After a "
            "tool error, a clearly wrong result or a missing capability you may offer once per "
            "problem (\"Want me to write a bug report?\"). Before calling it, show the user the "
            "report you'll send and call it only after they agree: on a hosted server the call "
            "itself saves the report.\n\n"
            "Write in general terms about the connector's behaviour, e.g. \"a note saved at the "
            "end of a long consultation was missing the next day\", never the note itself. Never "
            "include personal data: no names, ids, dates, places, health details, goal or note "
            "text, values from the athlete's data, error messages, links or @mentions. The "
            "server rejects some patterns mechanically (emails, links, mentions, long numbers "
            "and ids, dates, token-like strings) and says what to rewrite, but it can't detect "
            "names, places or health details in prose: leaving those out is up to you, and the "
            "user must check the text. The server adds version and error diagnostics itself.\n\n"
            "Show the user the returned text (and link, if any) verbatim. Never claim a report "
            "was filed on GitHub: on a personal server the user files it, on a hosted server "
            "it is saved for the operator."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(KINDS)},
                "title": {"type": "string", "description": "One line, at most 120 characters."},
                "summary": {"type": "string", "description": "What happened or what is missing, in general terms."},
                "steps": {"type": "string", "description": "Optional: steps to reproduce, in general terms."},
                "expected": {"type": "string", "description": "Optional: what should have happened."},
                "actual": {"type": "string", "description": "Optional: what happened instead, described qualitatively."},
                "related_tool": {
                    "type": "string",
                    "description": "Optional: name of this server's tool the report is about.",
                },
            },
            "required": ["kind", "title", "summary"],
        },
    )


REPORT_NOT_SAVED = "❌ Error: The report was not saved"

# One lock per hosted user, held from the daily-cap check to the end of the
# save, so concurrent calls can't all pass the cap. Single-process server.
_report_locks: dict[str, asyncio.Lock] = {}
# user id -> (date, reports saved that day). In memory only, so the athlete id
# is never written to the repo; a restart resets the count, which is fine for
# a cap meant to stop a runaway model, not a determined user.
_reports_today: dict[str, tuple[str, int]] = {}


def clear_report_counts() -> None:
    _reports_today.clear()


def _hosted_athlete(user_id: str) -> tuple[list, str]:
    """The athlete's stored names (for the name check) and data source kind.
    Raises if the store can't be read: the name check must not be skipped."""
    from .. import store

    user = store.get_user(user_id) or {}
    connection = store.get_intervals_connection(user_id) or {}
    names = [user.get("name"), connection.get("athlete_name")]
    return names, "strava, intervals.icu (wellness)" if connection else "strava"


async def draft_issue_handler(arguments: dict) -> list[TextContent]:
    """Handle draft_issue tool calls."""
    if not reporting_enabled():
        return [TextContent(type="text", text="❌ Error: Reporting issues is turned off on this server.")]

    from ..self_test import registered_tool_names

    user_id = current_user_id()
    names, data_source = (), None
    if user_id:
        try:
            names, data_source = _hosted_athlete(user_id)
        except Exception as e:  # fail closed: never save without the name check
            print(f"Error reading the store for a report: {type(e).__name__}", file=sys.stderr)
            return [TextContent(type="text", text=f"{REPORT_NOT_SAVED}: the server couldn't check it just now. Please try again later.")]
    try:
        draft = validate(arguments, await registered_tool_names(), names)
    except ReportRejected as e:
        return [TextContent(type="text", text=f"❌ {e}")]

    if user_id:
        diagnostics = {
            "Version": version_string(),
            "Transport": "http (hosted)",
            "Data source": data_source,
            "Related tool": draft.related_tool or "none",
            # Not kept on the hosted server: the user id is the Strava athlete id.
            "Recent error": "not recorded on the hosted server",
        }
    else:
        diagnostics = {
            "Version": version_string(),
            "Transport": "stdio",
            "Data source": "intervals.icu" if config.intervals_api_key else "none",
            "Related tool": draft.related_tool or "none",
            "Recent error": recent_error(draft.related_tool) or "none recorded",
        }
    body = render_body(draft, diagnostics)
    if len(body) > BODY_MAX:
        return [TextContent(type="text", text=(
            f"❌ The report was not drafted: it is {len(body)} characters with diagnostics; "
            f"the limit is {BODY_MAX}. Shorten it."
        ))]

    if user_id:
        return await _save_hosted_report(user_id, draft.title, body)

    url = prefilled_issue_url(issue_repo(), draft.title, body)
    if len(url) > URL_MAX:
        return [TextContent(type="text", text=(
            f"❌ The report was not drafted: its link would be {len(url)} characters once "
            f"encoded (non-English text counts several times); the limit is {URL_MAX}. Shorten it."
        ))]
    return [TextContent(type="text", text=(
        "📝 Draft report (nothing has been sent). Show the user this text verbatim:\n\n"
        f"**Title:** {draft.title}\n\n{body}\n"
        f"To send it, open this link, check the text on GitHub and press \"Create\". "
        f"The issue will be public, under the user's own GitHub account:\n{url}"
    ))]


async def _save_hosted_report(user_id: str, title: str, body: str) -> list[TextContent]:
    """Save the report to reports/<timestamp>-<random>.md in the training repo, for
    the operator. Never put the user id (the Strava athlete id) in the path or text."""
    if not config.training_repo_path or not Path(config.training_repo_path).exists():
        return [TextContent(type="text", text=(
            f"{REPORT_NOT_SAVED}: this server's report storage isn't set up. Please tell the "
            "server's operator about the problem directly."
        ))]
    async with _report_locks.setdefault(user_id, asyncio.Lock()):
        return await _save_hosted_report_locked(user_id, Path(config.training_repo_path), title, body)


async def _save_hosted_report_locked(user_id: str, repo_path: Path, title: str, body: str) -> list[TextContent]:
    try:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        day, sent_today = _reports_today.get(user_id, (today, 0))
        if day != today:
            sent_today = 0
        if sent_today >= HOSTED_REPORTS_PER_DAY:
            return [TextContent(type="text", text=(
                f"❌ The report was not saved: the limit is {HOSTED_REPORTS_PER_DAY} reports a day. "
                "Please try again tomorrow."
            ))]

        relative_path = f"reports/{now.strftime('%Y-%m-%d-%H-%M-%S')}-{secrets.token_hex(4)}.md"
        content = f"# {title}\n\n{body}"
        push_status = await asyncio.to_thread(
            git_save_file, repo_path, relative_path, content, f"Add report - {now.strftime('%Y-%m-%d %H:%M')}"
        )
        _reports_today[user_id] = (today, sent_today + 1)
        push_status = save_status_for_caller(push_status, user_id)
        return [TextContent(type="text", text=(
            f"✅ Report saved for the server's operator{push_status}. It is private; the operator "
            "reviews reports and may turn this one into a public GitHub issue. Show the user this "
            f"text verbatim; it is exactly what was saved:\n\n{content}"
        ))]

    except GitSyncError as e:
        return [TextContent(type="text", text=f"{REPORT_NOT_SAVED}. {save_error_for_caller(str(e), user_id)}")]

    except Exception as e:
        print(f"Error saving report: {type(e).__name__}", file=sys.stderr)
        return [TextContent(type="text", text=f"{REPORT_NOT_SAVED}. {save_error_for_caller(str(e), user_id)}")]
