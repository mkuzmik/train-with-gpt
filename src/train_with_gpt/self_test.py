"""Post-deploy self-test: a fixed checklist the server runs for one user.

Shared by the `self_test` MCP tool (tools/self_test.py) and the
`train-with-gpt-selftest` CLI (`cli()` below), so both run exactly the same
checks:

1. Data source auth - Strava token (or refresh) / intervals.icu key
2. Data reads      - activity COUNT for the last 7 days, whether wellness came back
3. Repo read       - pull; clean, at @{upstream}, remote configured, unsynced-* branches
4. Repo write      - save selftest/<user>.md through git_save_file, then verify on the remote
5. Build info      - GIT_SHA, uptime, versions
6. Tools registered

Every check runs even if an earlier one failed, each under its own timeout.
Data reads return counts/status only and nothing is cached (Strava API
policy). Errors are reported as the exception class plus a sanitized message:
known secret values, URL credentials and query strings are redacted.
"""

import argparse
import asyncio
import importlib.metadata
import os
import platform
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

import httpx

from .config import config
from .helpers import GitSyncError, _git, _output, _repo_lock, git_pull_and_read, git_save_file
from .intervals_client import IntervalsClient
from .strava_client import StravaClient

# Roughly the server's start time: server.py imports this module at startup.
STARTED_AT = time.monotonic()

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# Seconds per check. Git checks allow for git_save_file's retries.
TIMEOUTS = {
    "data_auth": 30.0,
    "data_reads": 45.0,
    "repo_read": 60.0,
    "repo_write": 90.0,
    "build_info": 5.0,
    "tools": 5.0,
}

# Tools the "self-test" prompt may call. Anything that writes (notes, goals,
# config) is listed in WRITE_TOOLS and must never be called by the prompt; a
# unit test checks every registered tool is in exactly one of the two lists.
# analyze_activity/analyze_lap are left out of the prompt on purpose (they
# process a full Strava activity) - see READ_ONLY_TOOLS_NOT_IN_PROMPT.
READ_ONLY_TOOLS = {
    "get_current_date": "{}",
    "start_consultation": "{}",
    "discuss_goals": "{}",
    "read_goals": "{}",
    "list_consultation_notes": "{}",
    "read_consultation_notes": "{}",
    "search_consultation_notes": '{"query": "test"}',
    "get_activities": "{} (report only the number of activities)",
    "get_sleep_data": "the last 3 days (start_date/end_date)",
    "get_hrv_data": "the last 3 days (start_date/end_date)",
    "get_resting_heart_rate": "the last 3 days (start_date/end_date)",
}
READ_ONLY_TOOLS_NOT_IN_PROMPT = ("analyze_activity", "analyze_lap")
WRITE_TOOLS = ("save_goals", "save_consultation_notes", "setup_training_repo", "self_test")

_SAFE_MARKER_NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,127}$")


@dataclass
class CheckResult:
    name: str
    status: str
    seconds: float
    detail: str


@dataclass
class Report:
    run_id: str
    user: str
    started: datetime
    checks: list[CheckResult]

    @property
    def failed(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == WARN]


@dataclass
class _Context:
    user_id: Optional[str]
    run_id: str
    started: datetime
    in_server: bool
    # Set when a git check timed out: asyncio can't stop its worker thread,
    # which may still hold the repo lock and change the clone.
    git_still_running: bool = False
    secret_values: set = field(default_factory=set)
    _clients: dict = field(default_factory=dict)

    @property
    def marker_name(self) -> str:
        return self.user_id or "local"

    def data_client(self):
        if "data" not in self._clients:
            from .server import data_client_for

            self._clients["data"] = data_client_for(self.user_id)
            self._remember_secrets()
        return self._clients["data"]

    def wellness_client(self):
        if "wellness" not in self._clients:
            from .server import wellness_client_for

            self._clients["wellness"] = wellness_client_for(self.user_id)
            self._remember_secrets()
        return self._clients["wellness"]

    def _remember_secrets(self) -> None:
        for client in self._clients.values():
            if isinstance(client, StravaClient):
                self.secret_values.update((client.access_token, client.refresh_token))
            elif isinstance(client, IntervalsClient):
                self.secret_values.add(client.api_key)

    def all_secrets(self) -> list[str]:
        self._remember_secrets()  # tokens a refresh rotated in during the run
        values = self.secret_values | {
            config.client_secret, config.intervals_api_key, config.token_encryption_key,
        }
        # Every non-empty value, however short (a garbled report beats a
        # leaked secret); longest first, so one containing another goes whole.
        return sorted((v for v in values if v), key=len, reverse=True)


# --- Sanitizing ------------------------------------------------------------------

_URL_USERINFO = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")
_URL_QUERY = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^\s?#]*)[?#][^\s'\"]*")
_BEARER = re.compile(r"(?i)\bbearer\s+[^\s'\"]+")
_SECRET_PARAM = re.compile(
    r"(?i)\b(access_token|refresh_token|client_secret|api_key|apikey|password|token)=[^\s&'\"]+"
)
_MAX_DETAIL = 300


def sanitize(text: str, secret_values: list[str] = ()) -> str:
    """Strip credentials from a message that came from outside (exception, git)."""
    for value in secret_values:
        text = text.replace(value, "***")
    text = _URL_USERINFO.sub(r"\1***@", text)
    text = _URL_QUERY.sub(r"\1", text)
    text = _BEARER.sub("Bearer ***", text)
    text = _SECRET_PARAM.sub(r"\1=***", text)
    text = " ".join(text.split())
    return text if len(text) <= _MAX_DETAIL else text[:_MAX_DETAIL] + "…"


def describe_error(error: BaseException, secret_values: list[str] = ()) -> str:
    """Exception class plus a sanitized message (never headers, tokens or full URLs)."""
    if isinstance(error, httpx.HTTPStatusError):
        url = error.request.url
        return f"HTTPStatusError: HTTP {error.response.status_code} from {url.host}{url.path}"
    if isinstance(error, httpx.RequestError):
        try:
            where = f" ({error.request.url.host})"
        except RuntimeError:  # no request attached
            where = ""
        return f"{type(error).__name__}{where}: {sanitize(str(error), secret_values)}"
    message = sanitize(str(error), secret_values)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


# --- Checks --------------------------------------------------------------------------

async def check_data_source_auth(ctx: _Context) -> tuple[str, str]:
    data = ctx.data_client()
    parts = []
    if isinstance(data, StravaClient):
        before = data.access_token
        await data.get_athlete()  # response discarded: only "did it authenticate"
        parts.append("activities: Strava, token " + ("refreshed and valid" if data.access_token != before else "valid"))
    else:
        await data.get_athlete()
        parts.append("activities: intervals.icu, key authenticates")

    wellness = ctx.wellness_client()
    if wellness is data:
        parts.append("wellness: intervals.icu (same key)")
    elif isinstance(wellness, IntervalsClient):
        await wellness.get_athlete()
        parts.append("wellness: intervals.icu, key authenticates")
    else:
        parts.append("wellness: none (Strava has no wellness data)")
    return PASS, "; ".join(parts)


async def check_data_reads(ctx: _Context) -> tuple[str, str]:
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    oldest, newest = week_ago.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")

    data = ctx.data_client()
    if isinstance(data, StravaClient):
        activities = await data.get_all_activities(after=int(week_ago.timestamp()), before=int(now.timestamp()))
    else:
        activities = await data.get_activities(oldest=oldest, newest=newest)
    parts = [f"activities in the last 7 days: {len(activities)}"]
    del activities  # count only; nothing is kept

    wellness = ctx.wellness_client()
    if isinstance(wellness, IntervalsClient):
        rows = await wellness.get_wellness(oldest=oldest, newest=newest)
        parts.append(f"wellness: {'data returned' if rows else 'no data returned'}")
    else:
        parts.append("wellness: not available (Strava)")
    return PASS, "; ".join(parts)


def _repo_path() -> Path:
    if not config.training_repo_path:
        raise RuntimeError("Training repository not configured (TRAINING_REPO_PATH / setup_training_repo)")
    repo = Path(config.training_repo_path)
    if not repo.exists():
        raise RuntimeError(f"Training repository path does not exist: {repo}")
    if _git(repo, "rev-parse", "--git-dir").returncode != 0:
        raise RuntimeError(f"Training repository is not a git repository: {repo}")
    return repo


def _repo_state(repo: Path) -> dict:
    """A snapshot of the clone, taken under the repo lock (inside git_pull_and_read)."""
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    state = {
        "remotes": _git(repo, "remote").stdout.split(),
        "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "dirty": _git(repo, "status", "--porcelain", "--untracked-files=no").stdout.strip().splitlines(),
        "untracked": len(_git(repo, "ls-files", "--others", "--exclude-standard").stdout.splitlines()),
        "unsynced": _git(repo, "branch", "--list", "unsynced-*", "--format=%(refname:short)").stdout.split(),
        "head": _git(repo, "rev-parse", "--short", "HEAD").stdout.strip(),
        "behind": 0,
        "ahead": 0,
    }
    if state["upstream"]:
        counts = _git(repo, "rev-list", "--left-right", "--count", "@{upstream}...HEAD").stdout.split()
        if len(counts) == 2:
            state["behind"], state["ahead"] = int(counts[0]), int(counts[1])
    return state


async def check_repo_read(ctx: _Context) -> tuple[str, str]:
    repo = _repo_path()
    note, state = await asyncio.to_thread(git_pull_and_read, repo, lambda: _repo_state(repo))
    secret_values = ctx.all_secrets()
    fails, warns, info = [], [], []

    if note and "(Note:" in note:
        fails.append(f"pull failed: {sanitize(note, secret_values)}")
    elif note and "⚠️" in note:
        warns.append(sanitize(note.split("\n\n")[0], secret_values))
    elif note:
        info.append("pulled updates from the remote")

    if not state["remotes"]:
        warns.append("no remote configured (saves stay local)")
    elif not state["upstream"]:
        warns.append(f"remote {', '.join(state['remotes'])} configured, but the branch has no upstream")

    if state["dirty"]:
        fails.append(f"{len(state['dirty'])} uncommitted change(s) to tracked files")
    if state["ahead"] or state["behind"]:
        fails.append(
            f"not at {state['upstream']}: {state['ahead']} local commit(s) not pushed, "
            f"{state['behind']} remote commit(s) not pulled"
        )
    if state["unsynced"]:
        shown = ", ".join(state["unsynced"][:3]) + (" …" if len(state["unsynced"]) > 3 else "")
        warns.append(f"{len(state['unsynced'])} unsynced-* branch(es) with parked commits: {shown}")
    if state["untracked"]:
        warns.append(f"{state['untracked']} untracked file(s)")

    if not state["dirty"]:
        info.append("no uncommitted changes" if state["untracked"] else "clean")
    if state["upstream"] and not (state["ahead"] or state["behind"]):
        info.append(f"at {state['upstream']} ({state['head']})")
    if not state["unsynced"]:
        info.append("no unsynced-* branches")

    status = FAIL if fails else WARN if warns else PASS
    return status, "; ".join(fails + warns + info)


def _verify_on_remote(repo: Path, relative: str, run_id: str) -> tuple[str, str]:
    """Independently of git_save_file's own report: fetch and look for this run's marker."""
    with _repo_lock(repo):
        fetch = _git(repo, "fetch", "--quiet")
        if fetch.returncode != 0:
            return FAIL, f"push reported success, but fetching to verify failed: {_output(fetch)}"
        upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}").stdout.strip()
        if not upstream:  # `git show :path` would read the index, not the remote
            return FAIL, "push reported success, but the branch has no upstream to verify against"
        shown = _git(repo, "show", f"{upstream}:{relative}")
        if shown.returncode != 0 or run_id not in shown.stdout:
            return FAIL, f"push reported success, but {upstream}:{relative} does not contain run {run_id}"
        sha = _git(repo, "rev-parse", "--short", upstream).stdout.strip()
        return PASS, f"saved {relative}, pushed, verified on {upstream} ({sha})"


async def check_repo_write(ctx: _Context) -> tuple[str, str]:
    if ctx.git_still_running:
        return FAIL, "not run: the repo read check timed out and its git operation may still be running"
    repo = _repo_path()
    if not _SAFE_MARKER_NAME.match(ctx.marker_name):
        return FAIL, "user id is not usable as a file name"
    relative = f"selftest/{ctx.marker_name}.md"
    content = (
        "# train-with-gpt self-test marker\n\n"
        "Overwritten by every self-test run; safe to delete.\n\n"
        f"- run_id: {ctx.run_id}\n"
        f"- timestamp: {ctx.started.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"- git_sha: {git_sha()}\n"
    )
    try:
        status = await asyncio.to_thread(git_save_file, repo, relative, content, f"Self-test run {ctx.run_id}")
    except GitSyncError as e:
        return FAIL, f"not saved: {sanitize(str(e), ctx.all_secrets())}"
    if not status.startswith(" and pushed to remote"):
        return FAIL, f"saved but not pushed: {sanitize(status, ctx.all_secrets())}"
    verdict, detail = await asyncio.to_thread(_verify_on_remote, repo, relative, ctx.run_id)
    return verdict, sanitize(detail, ctx.all_secrets())


def git_sha() -> str:
    return os.environ.get("GIT_SHA") or "unknown"


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d{hours:02d}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{secs:02d}s"


def _machine_uptime() -> Optional[float]:
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


async def check_build_info(ctx: _Context) -> tuple[str, str]:
    sha = git_sha()
    parts = [f"GIT_SHA {sha}"]
    if ctx.in_server:
        parts.append(f"server uptime {_duration(time.monotonic() - STARTED_AT)}")
    else:
        parts.append("server uptime n/a (CLI run)")
    machine = _machine_uptime()
    if machine is not None:
        parts.append(f"machine uptime {_duration(machine)}")
    parts.append(f"Python {platform.python_version()}")
    for package in ("mcp", "train-with-gpt"):
        try:
            parts.append(f"{package} {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            parts.append(f"{package} ?")
    return (WARN if sha == "unknown" else PASS), "; ".join(parts)


async def registered_tool_names() -> list[str]:
    from .server import list_tools

    return [tool.name for tool in await list_tools()]


async def check_tools(ctx: _Context) -> tuple[str, str]:
    names = await registered_tool_names()
    return PASS, f"{len(names)}: {', '.join(names)}"


CHECKS: list[tuple[str, str, Callable[[_Context], Awaitable[tuple[str, str]]]]] = [
    ("Data source auth", "data_auth", check_data_source_auth),
    ("Data reads", "data_reads", check_data_reads),
    ("Repo read", "repo_read", check_repo_read),
    ("Repo write", "repo_write", check_repo_write),
    ("Build info", "build_info", check_build_info),
    ("Tools registered", "tools", check_tools),
]


# --- Running and reporting ------------------------------------------------------------

_GIT_CHECKS = ("repo_read", "repo_write")


async def _run_check(ctx: _Context, name: str, key: str, check) -> CheckResult:
    timeout = TIMEOUTS[key]
    start = time.monotonic()
    try:
        status, detail = await asyncio.wait_for(check(ctx), timeout)
    except asyncio.TimeoutError:
        status, detail = FAIL, f"timed out after {timeout:g}s"
        if key in _GIT_CHECKS:
            ctx.git_still_running = True
            detail += " (the git operation may still be running in the background)"
    except Exception as e:  # one check failing must not stop the others
        status, detail = FAIL, describe_error(e, ctx.all_secrets())
    return CheckResult(name, status, time.monotonic() - start, detail)


async def run_self_test(user_id: Optional[str], in_server: bool = True) -> Report:
    """Run every check for `user_id` (None: the personal/stdio configuration)."""
    ctx = _Context(
        user_id=user_id,
        run_id=secrets.token_hex(4),
        started=datetime.now(timezone.utc),
        in_server=in_server,
    )
    results = [await _run_check(ctx, name, key, check) for name, key, check in CHECKS]
    # Last line of defence: no known secret value anywhere in the output.
    secret_values = ctx.all_secrets()
    for result in results:
        for value in secret_values:
            result.detail = result.detail.replace(value, "***")
    return Report(run_id=ctx.run_id, user=ctx.marker_name, started=ctx.started, checks=results)


def format_report(report: Report) -> str:
    if report.failed:
        verdict = (
            f"FAIL - {len(report.failed)} of {len(report.checks)} checks failed: "
            + ", ".join(c.name for c in report.failed)
        )
    elif report.warnings:
        verdict = f"PASS with {len(report.warnings)} warning(s)"
    else:
        verdict = "PASS"
    lines = [
        f"## Self-test: {verdict}",
        "",
        f"Run {report.run_id} · user {report.user} · {report.started.strftime('%Y-%m-%d %H:%M:%S')} UTC",
        "",
        "| # | Check | Result | Time | Detail |",
        "|---|---|---|---|---|",
    ]
    for i, check in enumerate(report.checks, 1):
        detail = check.detail.replace("|", "/").replace("\n", " ")
        lines.append(f"| {i} | {check.name} | {check.status} | {check.seconds:.2f}s | {detail} |")
    lines += ["", f"Overall: {verdict}"]
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------

ROOT_HINT = """\
Run this as the `app` user, not root: git refuses a clone owned by another
user, and anything root writes into the repo or store.db breaks the server.
Inside the container:

    su app -c 'train-with-gpt-selftest --user-id <id>'
"""


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="train-with-gpt-selftest",
        description=(
            "Run the self_test checks (data source, repo read/write, build info, tools) "
            "and exit non-zero if any check fails."
        ),
    )
    parser.add_argument(
        "--user-id",
        help="OAuth user (Strava athlete id) to test; omit to test the personal/stdio configuration",
    )
    args = parser.parse_args(argv)
    if args.user_id is not None and not _SAFE_MARKER_NAME.match(args.user_id):
        parser.error("--user-id may only contain letters, digits, '.', '_' and '-'")

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print(ROOT_HINT, file=sys.stderr)
        return 2

    report = asyncio.run(run_self_test(args.user_id, in_server=False))
    print(format_report(report))
    return 1 if report.failed else 0


def cli() -> None:
    sys.exit(main())
