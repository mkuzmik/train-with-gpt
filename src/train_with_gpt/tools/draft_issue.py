"""draft_issue tool: a bug report or improvement idea about the connector.

Personal (stdio) server: it returns a GitHub link with the report prefilled,
and the user files it under their own account.

Hosted server: hosted users may not have a GitHub account and shouldn't file
publicly under their name, so the report is saved privately in the server's
training repo (reports/<user_id>/), where the operator triages it and, when
warranted, writes a public issue. No GitHub token is needed. See issue #32.
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
    training_repo_not_configured_message,
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


def _stored_names(user_id: str) -> list:
    """The hosted athlete's stored names (Strava, intervals.icu), for the name check."""
    from .. import store

    try:
        user = store.get_user(user_id) or {}
        connection = store.get_intervals_connection(user_id) or {}
    except Exception:  # the store is a convenience here; never block a report on it
        return []
    return [user.get("name"), connection.get("athlete_name")]


def _hosted_data_source(user_id: str) -> str:
    from .. import store

    try:
        connected = bool(store.get_intervals_connection(user_id))
    except Exception:
        connected = False
    return "strava, intervals.icu (wellness)" if connected else "strava"


async def draft_issue_handler(arguments: dict) -> list[TextContent]:
    """Handle draft_issue tool calls."""
    if not reporting_enabled():
        return [TextContent(type="text", text="❌ Error: Reporting issues is turned off on this server.")]

    from ..self_test import registered_tool_names

    user_id = current_user_id()
    try:
        draft = validate(arguments, await registered_tool_names(), _stored_names(user_id) if user_id else ())
    except ReportRejected as e:
        return [TextContent(type="text", text=f"❌ {e}")]

    if user_id:
        diagnostics = {
            "Version": version_string(),
            "Transport": "http (hosted)",
            "Data source": _hosted_data_source(user_id),
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
    """Save the report to reports/<user_id>/ in the training repo, for the operator."""
    try:
        if not config.training_repo_path:
            return [TextContent(type="text", text=training_repo_not_configured_message())]
        repo_path = Path(config.training_repo_path)
        if not repo_path.exists():
            return [TextContent(type="text", text=f"❌ Error: {save_error_for_caller('', user_id)}")]

        now = datetime.now()
        reports_dir = repo_path / "reports" / user_id
        today = now.strftime("%Y-%m-%d")
        sent_today = len(list(reports_dir.glob(f"{today}-*.md"))) if reports_dir.exists() else 0
        if sent_today >= HOSTED_REPORTS_PER_DAY:
            return [TextContent(type="text", text=(
                f"❌ The report was not saved: the limit is {HOSTED_REPORTS_PER_DAY} reports a day. "
                "Please try again tomorrow."
            ))]

        relative_path = f"reports/{user_id}/{now.strftime('%Y-%m-%d-%H-%M-%S')}-{secrets.token_hex(2)}.md"
        push_status = await asyncio.to_thread(
            git_save_file, repo_path, relative_path, f"# {title}\n\n{body}", f"Add report - {now.strftime('%Y-%m-%d %H:%M')}"
        )
        push_status = save_status_for_caller(push_status, user_id)
        return [TextContent(type="text", text=(
            f"✅ Report saved for the server's operator{push_status}. It is private; the operator "
            "reviews reports and may turn this one into a public GitHub issue. Show the user this "
            f"text verbatim:\n\n**Title:** {title}\n\n{body}"
        ))]

    except GitSyncError as e:
        return [TextContent(type="text", text=f"❌ Error: The report was not saved. {save_error_for_caller(str(e), user_id)}")]

    except Exception as e:
        print(f"Error saving report: {type(e).__name__}", file=sys.stderr)
        return [TextContent(type="text", text=f"❌ Error: The report was not saved. {save_error_for_caller(str(e), user_id)}")]
