"""Hosted (OAuth) callers of the save tools never see raw git output.

On the hosted server the training repo is shared: git errors can carry the
private remote URL, server paths or other users' file names. The personal
(stdio) path keeps the full detail. All content here is made up.
"""

import pytest

from tests.support import as_oauth_user, git, text_of
from train_with_gpt.helpers import GitSyncError
from train_with_gpt.tools import (
    save_athlete_profile_handler,
    save_consultation_notes_handler,
    save_goals_handler,
)
from train_with_gpt.tools import save_athlete_profile, save_consultation_notes, save_goals

SAVES = [
    pytest.param(save_athlete_profile_handler, save_athlete_profile, {"content": "## Background\n- Synthetic\n"}, id="profile"),
    pytest.param(save_goals_handler, save_goals, {"goals_text": "Synthetic 10k goal"}, id="goals"),
    pytest.param(save_consultation_notes_handler, save_consultation_notes, {"notes": "Synthetic note"}, id="notes"),
]


@pytest.mark.parametrize("handler, module, arguments", SAVES)
async def test_a_failed_push_shows_hosted_users_no_git_output(training_repo, tmp_path, handler, module, arguments):
    # The remote is unreachable: fetch and push both fail with its path in the error.
    git(training_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))

    personal = text_of(await handler(arguments))
    with as_oauth_user("1001"):
        hosted = text_of(await handler(arguments))

    assert "Could not push to remote" in personal and "gone.git" in personal
    assert hosted.startswith("✅")
    assert "couldn't be pushed" in hosted
    assert str(tmp_path) not in hosted
    assert "git pull had issues" not in hosted


@pytest.mark.parametrize("handler, module, arguments", SAVES)
async def test_a_successful_hosted_save_shows_no_server_path(training_repo, handler, module, arguments):
    with as_oauth_user("1001"):
        hosted = text_of(await handler(arguments))

    assert "pushed to remote" in hosted
    assert str(training_repo) not in hosted
    assert "1001" in hosted  # the caller's own relative path


@pytest.mark.parametrize("handler, module, arguments", SAVES)
@pytest.mark.parametrize("error", [GitSyncError("Could not sync with the remote: /srv/secret/repo athlete/2002.md"),
                                   RuntimeError("/srv/secret/repo athlete/2002.md")])
async def test_save_errors_show_hosted_users_a_generic_message(training_repo, monkeypatch, handler, module, arguments, error):
    def fail(*args):
        raise error

    monkeypatch.setattr(module, "git_save_file", fail)

    personal = text_of(await handler(arguments))
    with as_oauth_user("1001"):
        hosted = text_of(await handler(arguments))

    assert "/srv/secret/repo" in personal
    assert hosted.startswith("❌ Error:")
    assert "/srv/secret/repo" not in hosted and "2002" not in hosted
