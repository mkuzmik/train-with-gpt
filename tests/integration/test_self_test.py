"""The self_test tool and the post-deploy CLI, black box.

Over HTTP as an OAuth'd Strava user (only Strava's API and the git remote are
stubbed), and the installed `train-with-gpt-selftest` script as a subprocess.
"""

import os
import subprocess
import sys
from pathlib import Path

from httpx import Response

from tests.integration.conftest import STRAVA_API
from tests.support import assert_clean_and_in_sync, remote_file, remote_files

ALICE = 1001


def test_self_test_over_http_saves_only_the_marker(login, strava, http_mock, git_remote, server_env):
    def athlete(request):
        athlete_id = strava._athlete_for(request)
        return Response(200, json={"id": athlete_id}) if athlete_id else Response(401)

    http_mock.get(f"{STRAVA_API}/athlete").mock(side_effect=athlete)
    strava.activities[ALICE] = [{"id": 1, "sport_type": "Run", "start_date": "2024-01-15T07:00:00Z"}]
    alice = login(ALICE)

    first = alice.call_tool("self_test")
    second = alice.call_tool("self_test")

    for output in (first, second):
        assert "| Data source auth | PASS |" in output
        assert "activities: Strava, token valid" in output
        assert "| Data reads | PASS |" in output and "activities in the last 7 days: 1" in output
        assert "| Repo read | PASS |" in output
        assert "| Repo write | PASS |" in output and "verified on origin/main" in output
        assert f"user {ALICE}" in output
        assert "strava-access-" not in output and "strava-refresh-" not in output
    assert "Overall: FAIL" not in second
    assert [p for p in remote_files(git_remote) if p != "README.md"] == [f"selftest/{ALICE}.md"]
    run_id = second.split("\nRun ", 1)[1].split(" ", 1)[0]
    assert f"run_id: {run_id}" in remote_file(git_remote, f"selftest/{ALICE}.md")
    assert_clean_and_in_sync(server_env)


def test_self_test_is_listed_with_its_prompt(login):
    alice = login(ALICE)

    assert "self_test" in {tool["name"] for tool in alice.list_tools()}
    prompts = alice.request("prompts/list")["prompts"]
    assert [p["name"] for p in prompts] == ["self-test"]
    prompt = alice.request("prompts/get", {"name": "self-test"})
    text = prompt["messages"][0]["content"]["text"]
    assert "Call `self_test`" in text and "never call `save_goals`" in text


def _cli() -> str:
    return str(Path(sys.executable).parent / "train-with-gpt-selftest")


def _cli_env(home: Path, **extra) -> dict:
    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "PATH": os.environ["PATH"]}
    env.update({k: v for k, v in os.environ.items() if k.startswith("GIT_")})
    env.update(extra)
    return env


def test_cli_exit_code_is_non_zero_when_a_check_fails(hermetic, training_repo, git_remote):
    # No intervals.icu key: the data checks fail, the repo checks still run.
    result = subprocess.run(
        [_cli()], env=_cli_env(hermetic, TRAINING_REPO_PATH=str(training_repo), GIT_SHA="abc1234"),
        capture_output=True, text=True, timeout=120,
    )

    assert result.returncode == 1, result.stderr
    assert "| Data source auth | FAIL |" in result.stdout
    assert "| Repo write | PASS |" in result.stdout
    assert "Overall: FAIL" in result.stdout
    assert "selftest/local.md" in remote_files(git_remote)


def test_cli_help_exits_zero(hermetic):
    result = subprocess.run([_cli(), "--help"], env=_cli_env(hermetic), capture_output=True, text=True, timeout=60)

    assert result.returncode == 0
    assert "--user-id" in result.stdout
