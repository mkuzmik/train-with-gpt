"""Unit tests for parsing ALLOWED_STRAVA_ATHLETE_IDS (allowlist.py). Ids are synthetic."""

import pytest

from train_with_gpt.allowlist import ENV_VAR, AllowlistError, load_allowlist, parse_allowlist


@pytest.mark.parametrize("raw, expected", [
    ("101", {"101"}),
    ("101,202", {"101", "202"}),
    (" 101 ,\t202 ,  303 ", {"101", "202", "303"}),
    ("101,202,", {"101", "202"}),  # trailing comma
    ("101,,202", {"101", "202"}),
    ("101,101", {"101"}),
    ("0101", {"101"}),  # canonical form, as str(athlete["id"]) would give
])
def test_parses_comma_separated_ids(raw, expected):
    assert parse_allowlist(raw) == frozenset(expected)


@pytest.mark.parametrize("raw", [None, "", "   ", ",", " , ,"])
def test_unset_or_empty_allows_nobody(raw):
    assert parse_allowlist(raw) == frozenset()


@pytest.mark.parametrize("raw", [
    "101,abc", "101;202", "101 202", "-5", "0", "1.5", "+7", "１２", "²", "101,0x1f",
])
def test_invalid_entries_are_rejected(raw):
    with pytest.raises(AllowlistError, match=ENV_VAR):
        parse_allowlist(raw)


def test_error_names_the_position_but_not_the_value():
    with pytest.raises(AllowlistError) as excinfo:
        parse_allowlist("101, 20x2")

    assert "entry #2" in str(excinfo.value)
    assert "20x2" not in str(excinfo.value)


def test_there_is_no_wildcard():
    with pytest.raises(AllowlistError, match="no wildcard"):
        parse_allowlist("*")


def test_load_logs_only_the_count(capsys):
    allowed = load_allowlist({ENV_VAR: "101,202"})

    assert allowed == frozenset({"101", "202"})
    err = capsys.readouterr().err
    assert "2 Strava athlete(s) allowed" in err
    assert "101" not in err and "202" not in err


def test_load_warns_loudly_when_unset(capsys):
    assert load_allowlist({}) == frozenset()
    assert "WARNING" in capsys.readouterr().err


def test_load_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "303")

    assert load_allowlist() == frozenset({"303"})
