"""Unit tests for the train-with-gpt-purge-user operator CLI, over a real temp store.

Strava's deauthorize endpoint is stubbed with respx. Ids are synthetic.
"""

import os
from urllib.parse import parse_qs

import pytest
from httpx import Response

from train_with_gpt import store
from train_with_gpt.purge_user import main

DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"


@pytest.fixture(autouse=True)
def not_root(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000, raising=False)


def _seed(user_id):
    store.upsert_user(user_id, "strava", "Some Name", f"access-{user_id}", f"refresh-{user_id}", 9999999999)
    store.save_access_token(f"token-{user_id}", f'{{"subject": "{user_id}"}}')


def test_purges_the_user_and_revokes_the_strava_grant(db, http_mock, capsys):
    _seed("101")
    _seed("202")
    deauthorize = http_mock.post(DEAUTHORIZE_URL).mock(return_value=Response(200, json={}))

    assert main(["101"]) == 0

    assert parse_qs(deauthorize.calls.last.request.content.decode()) == {"access_token": ["access-101"]}
    assert store.get_user("101") is None
    assert store.get_access_token_row("token-101") is None
    assert store.get_user("202") is not None
    out = capsys.readouterr().out
    assert "Strava access revoked: yes" in out
    assert "users: 1 row(s) deleted" in out
    assert "notes/101/" in out and "goals/101.md" in out


def test_purges_even_when_deauthorize_fails(db, http_mock, capsys):
    _seed("101")
    http_mock.post(DEAUTHORIZE_URL).mock(return_value=Response(401, json={}))

    assert main(["101"]) == 0

    assert store.get_user("101") is None
    assert "Strava access revoked: no" in capsys.readouterr().out


def test_no_deauthorize_flag_skips_strava(db, http_mock):
    _seed("101")
    deauthorize = http_mock.post(DEAUTHORIZE_URL)

    assert main(["101", "--no-deauthorize"]) == 0

    assert not deauthorize.called
    assert store.get_user("101") is None


def test_unknown_user_is_a_no_op(db, http_mock, capsys):
    deauthorize = http_mock.post(DEAUTHORIZE_URL)

    assert main(["999"]) == 0

    assert not deauthorize.called
    assert "users: 0 row(s) deleted" in capsys.readouterr().out


@pytest.mark.parametrize("user_id", ["abc", "1 OR 1=1", "../x", "-1"])
def test_rejects_non_numeric_ids(db, user_id):
    with pytest.raises(SystemExit) as excinfo:
        main(["--", user_id])

    assert excinfo.value.code == 2


def test_refuses_to_run_as_root(db, monkeypatch, capsys):
    _seed("101")
    monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)

    assert main(["101"]) == 2

    assert store.get_user("101") is not None
    assert "app" in capsys.readouterr().err
