"""draft_issue tool: draft a bug report or improvement idea for the user to file.

Only offered on the personal (stdio) server for now: it returns a GitHub link
with the report prefilled, and the user files it under their own account. The
hosted server needs a confirmation page and a server-side token first (see
GitHub issue #32), so there the tool is hidden and refuses.
"""

from mcp.types import TextContent, Tool

from ..config import config
from ..helpers import current_user_id
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


def draft_issue_available() -> bool:
    """Whether list_tools offers draft_issue to the current caller."""
    return reporting_enabled() and not current_user_id()


def draft_issue_tool() -> Tool:
    """Return the draft_issue tool definition."""
    return Tool(
        name="draft_issue",
        description=(
            "Draft a bug report or improvement idea about this connector (not about training) "
            "for the user to review and file on GitHub. Nothing is sent: it returns the exact "
            "text and a link that opens GitHub's new-issue form with it filled in; the user "
            "files it under their own GitHub account, and the issue is PUBLIC.\n\n"
            "Use it when the user asks to report a problem or suggest an improvement. After a "
            "tool error, a clearly wrong result or a missing capability you may offer once per "
            "problem (\"Want me to draft a bug report?\"), and call this only after the user "
            "agrees.\n\n"
            "Write in general terms about the connector's behaviour, e.g. \"a note saved at the "
            "end of a long consultation was missing the next day\", never the note itself. Never "
            "include personal data: no names, ids, dates, places, health details, goal or note "
            "text, values from the athlete's data, error messages, links or @mentions. The "
            "server rejects some patterns mechanically (emails, links, mentions, long numbers "
            "and ids, dates, token-like strings) and says what to rewrite, but it can't detect "
            "names, places or health details in prose: leaving those out is up to you, and the "
            "user must check the text before filing it. The server adds version and error "
            "diagnostics itself.\n\n"
            "Show the user the returned text and link verbatim, and say that they send it by "
            "opening the link; never claim the report was filed."
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


async def draft_issue_handler(arguments: dict) -> list[TextContent]:
    """Handle draft_issue tool calls."""
    if not reporting_enabled():
        return [TextContent(type="text", text="❌ Error: Reporting issues is turned off on this server.")]
    if current_user_id():
        return [TextContent(type="text", text=(
            "❌ Error: Reporting issues from the chat isn't available on this server yet. "
            "Please tell the server's operator directly."
        ))]

    from ..self_test import registered_tool_names

    try:
        draft = validate(arguments, await registered_tool_names())
    except ReportRejected as e:
        return [TextContent(type="text", text=f"❌ {e}")]

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
