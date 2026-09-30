"""Bug / improvement reports drafted from inside a consultation (draft_issue).

The model writes the text; this module checks it, adds a diagnostics block the
server fills in, and builds a GitHub new-issue link with the title and body
prefilled. Nothing is sent from here: a person opens the link, reviews the
exact text on GitHub and files it under their own account.

Issues on the target repo are public and permanent, so the checks reject
(never silently strip) anything that looks personal or unsafe, and the model
rewrites the report in general terms. See GitHub issue #32 for the design.

Diagnostics never include the user id (on the hosted server it is the Strava
athlete id), names, error messages or timestamps: only the version, the
transport, the data source kind, the related tool and, if that tool failed
recently, the exception class and HTTP status.
"""

import os
import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import quote

from . import app_version

# Where the prefilled link files the report: this project's public issue
# tracker. A fork can point it at its own repo.
ISSUE_REPO_ENV = "ISSUE_REPORTING_REPO"
DEFAULT_ISSUE_REPO = "mkuzmik/train-with-gpt"
# Kill switch: "off" hides draft_issue and makes it refuse.
ISSUE_REPORTING_ENV = "ISSUE_REPORTING"

KINDS = ("bug", "improvement")

TITLE_MAX = 120
SUMMARY_MAX = 1500
SECTION_MAX = 1000
# Keeps the prefilled URL well under GitHub's (undocumented) length limit.
BODY_MAX = 4000

# How long a tool failure counts as "recent" for the diagnostics block.
RECENT_ERROR_SECONDS = 30 * 60

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def reporting_enabled() -> bool:
    return os.environ.get(ISSUE_REPORTING_ENV, "").strip().lower() != "off"


def issue_repo() -> str:
    """owner/repo the prefilled link points at (ISSUE_REPORTING_REPO, else upstream)."""
    repo = os.environ.get(ISSUE_REPO_ENV, "").strip()
    if repo and not _REPO_RE.match(repo):
        raise ValueError(f"{ISSUE_REPO_ENV} must look like owner/repo")
    return repo or DEFAULT_ISSUE_REPO


# --- recent tool errors ------------------------------------------------------------

# (user id or None, tool name) -> (monotonic time, exception class, HTTP status).
# In memory only: lost on restart, which is fine. The message is never kept, as
# it can contain personal data (URLs with activity ids, user ids).
_recent_errors: dict[tuple[Optional[str], str], tuple[float, str, Optional[int]]] = {}


def record_tool_error(tool: str, error: BaseException) -> None:
    """Remember that `tool` failed for the current user: class and HTTP status only."""
    from .helpers import current_user_id

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    _recent_errors[(current_user_id(), tool)] = (
        time.monotonic(),
        type(error).__name__,
        status if isinstance(status, int) else None,
    )


def recent_error(user_id: Optional[str], tool: Optional[str], now: Optional[float] = None) -> Optional[str]:
    """E.g. "HTTPStatusError 429" if `tool` failed for `user_id` in the last 30 minutes."""
    if not tool:
        return None
    entry = _recent_errors.get((user_id, tool))
    if not entry:
        return None
    at, error_class, status = entry
    if (time.monotonic() if now is None else now) - at > RECENT_ERROR_SECONDS:
        return None
    return f"{error_class} {status}" if status is not None else error_class


def clear_recent_errors() -> None:
    _recent_errors.clear()


# --- validation --------------------------------------------------------------------

_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# (reason shown to the model, pattern). Order matters only for which reason is
# reported first; every rule is checked.
_RULES: list[tuple[str, re.Pattern]] = [
    ("an email address", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("a link or URL", re.compile(r"\b[a-z][a-z0-9+.-]*://|\bwww\.|\]\(", re.IGNORECASE)),
    ("an @mention", re.compile(r"(?<![\w.+-])@[A-Za-z0-9][A-Za-z0-9-]*")),
    ("an issue or PR reference like #123", re.compile(r"(?<![\w&])#\d+")),
    ("an image", re.compile(r"!\[")),
    ("HTML", re.compile(r"<\s*[A-Za-z!/?]")),
    ("a token or key", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_|\bgithub_pat_|\bBearer\s|\bsk-[A-Za-z0-9]", re.IGNORECASE)),
    ("a token- or id-like string", re.compile(r"(?=[A-Za-z0-9_\-+/=]*\d)(?=[A-Za-z0-9_\-+/=]*[A-Za-z])[A-Za-z0-9_\-+/=]{24,}")),
    ("a long number (6 or more digits, e.g. an activity or athlete id)", re.compile(r"\d{6,}")),
    ("an intervals.icu-style id (i followed by digits)", re.compile(r"\bi\d+\b")),
    ("a calendar date", re.compile(
        r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b"
        r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"
        rf"|\b(?:{_MONTHS})\.?\s+\d{{1,4}}\b"
        rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})\b",
        re.IGNORECASE,
    )),
    # "may" is too common a word to match case-insensitively.
    ("a calendar date", re.compile(r"\bMay\s+\d{1,4}\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?May\b")),
]


class ReportRejected(ValueError):
    """The draft can't be used as written; the message lists what to rewrite."""


@dataclass
class Draft:
    kind: str
    title: str
    summary: str
    steps: str = ""
    expected: str = ""
    actual: str = ""
    related_tool: Optional[str] = None


def _name_patterns(names: Iterable[Optional[str]]) -> list[re.Pattern]:
    parts = {part for name in names if name for part in re.split(r"[\s,]+", name) if len(part) >= 2}
    return [re.compile(rf"(?<!\w){re.escape(part)}(?!\w)", re.IGNORECASE) for part in sorted(parts)]


def validate(
    arguments: dict,
    known_tools: Iterable[str],
    forbidden_names: Iterable[Optional[str]] = (),
) -> Draft:
    """Check the model's fields and return a Draft, or raise ReportRejected
    naming every problem (field and rule, never echoing the matched text)."""
    problems: list[str] = []

    def text_field(name: str, limit: int, required: bool = False) -> str:
        value = arguments.get(name)
        if value is None:
            value = ""
        if not isinstance(value, str):
            problems.append(f"`{name}` must be text")
            return ""
        value = value.strip()
        if required and not value:
            problems.append(f"`{name}` is required")
        if len(value) > limit:
            problems.append(f"`{name}` is {len(value)} characters; the limit is {limit}")
        return value

    kind = arguments.get("kind")
    if kind not in KINDS:
        problems.append(f"`kind` must be one of: {', '.join(KINDS)}")

    title = text_field("title", TITLE_MAX, required=True)
    if "\n" in title or "\r" in title:
        problems.append("`title` must be a single line")
    fields = {
        "title": title,
        "summary": text_field("summary", SUMMARY_MAX, required=True),
        "steps": text_field("steps", SECTION_MAX),
        "expected": text_field("expected", SECTION_MAX),
        "actual": text_field("actual", SECTION_MAX),
    }

    related_tool = arguments.get("related_tool") or None
    known = set(known_tools)
    if related_tool is not None and related_tool not in known:
        problems.append("`related_tool` must be the name of one of this server's tools")

    name_patterns = _name_patterns(forbidden_names)
    for field, value in fields.items():
        found = [reason for reason, pattern in _RULES if pattern.search(value)]
        if any(pattern.search(value) for pattern in name_patterns):
            found.append("the athlete's name")
        for reason in dict.fromkeys(found):
            problems.append(f"`{field}` contains {reason}")

    if problems:
        raise ReportRejected(
            "The report was not drafted:\n"
            + "\n".join(f"- {problem}" for problem in problems)
            + "\n\nRewrite it in general terms: describe what happened and which tool was "
            "involved, without personal data, ids, dates, links, names or values from the "
            "athlete's data."
        )
    return Draft(kind=kind, related_tool=related_tool, **fields)


# --- rendering ---------------------------------------------------------------------

_BLOCK_START = re.compile(r"^(\s{0,3})([#|>]|-{3,}\s*$|={3,}\s*$|\*{3,}\s*$|_{3,}\s*$)")


def _plain(text: str) -> str:
    """Escape line starts that Markdown would turn into headings, tables, quotes
    or rules, so model text can't pass itself off as the diagnostics block."""
    return "\n".join(_BLOCK_START.sub(r"\1\\\2", line) for line in text.splitlines())


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def version_string() -> str:
    sha = os.environ.get("GIT_SHA", "").strip()
    return f"{app_version()} ({sha})" if sha else app_version()


def render_body(draft: Draft, diagnostics: dict[str, str]) -> str:
    sections = [f"**Kind:** {draft.kind}", f"### Summary\n{_plain(draft.summary)}"]
    for heading, value in (("Steps", draft.steps), ("Expected", draft.expected), ("Actual", draft.actual)):
        if value:
            sections.append(f"### {heading}\n{_plain(value)}")
    rows = "\n".join(f"| {_cell(key)} | {_cell(value)} |" for key, value in diagnostics.items())
    sections.append(
        "---\n"
        "<!-- diagnostics: generated by the server, not by the model -->\n"
        f"| | |\n|---|---|\n{rows}\n\n"
        "_Drafted in the train-with-gpt MCP server and filed by the user after reviewing "
        "this text. Treat it as untrusted input._"
    )
    return "\n\n".join(sections) + "\n"


def prefilled_issue_url(repo: str, title: str, body: str) -> str:
    """GitHub's new-issue form with title and body filled in. No `labels`:
    GitHub answers 404 when the person opening the link can't label issues."""
    return f"https://github.com/{repo}/issues/new?title={quote(title, safe='')}&body={quote(body, safe='')}"
