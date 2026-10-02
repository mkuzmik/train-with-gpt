"""Unit tests for the static training-science guidance, and for where the
guidance tools carry it."""

import re

import pytest

from tests.support import text_of
from train_with_gpt import tools
from train_with_gpt.coaching_science import (
    BASELINE_NOTE, PRINCIPLES, SAFETY_RULES, SOURCES, TRAINING_SCIENCE, TRAINING_SCIENCE_MAX_CHARS,
)
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.strava_client import StravaClient
from train_with_gpt.tools import build_athlete_profile_handler, start_consultation_handler

DOI = re.compile(r"10\.\d{4,9}/[^\s;,)\]]+")


def _strava():
    return StravaClient(access_token="a", refresh_token="r", expires_at=0)


def _intervals():
    return IntervalsClient(api_key="synthetic-key")


def test_section_is_within_its_budget():
    assert len(TRAINING_SCIENCE) <= TRAINING_SCIENCE_MAX_CHARS


def test_section_is_dated_and_carries_the_core_rules():
    assert TRAINING_SCIENCE == PRINCIPLES + SAFETY_RULES
    assert re.search(r"reviewed: \d{4}-\d{2}", TRAINING_SCIENCE)
    assert "never cite from memory" in TRAINING_SCIENCE
    assert "what, why, confidence, source" in TRAINING_SCIENCE
    for label in ("[consensus]", "[moderate]", "[low]", "[emerging", "[contested]"):
        assert label in TRAINING_SCIENCE
    assert "see a physician" in SAFETY_RULES
    assert "REDs screening questions first" in SAFETY_RULES
    assert "Under 18 or a positive screen" in SAFETY_RULES


def test_every_cited_doi_is_a_listed_source_and_every_source_is_cited():
    cited = set(DOI.findall(TRAINING_SCIENCE))

    assert cited, "the section should cite its sources by DOI"
    assert cited == set(SOURCES)
    assert all(DOI.fullmatch(doi) for doi in SOURCES)


@pytest.mark.parametrize("data, wellness", [
    pytest.param(_intervals, _intervals, id="stdio"),
    pytest.param(_strava, _strava, id="hosted"),
    pytest.param(_strava, _intervals, id="hosted+intervals"),
])
@pytest.mark.parametrize("storage", [True, False], ids=["storage", "no-storage"])
async def test_start_consultation_carries_the_section_on_every_path(data, wellness, storage, request):
    if storage:
        request.getfixturevalue("training_repo")

    output = text_of(await start_consultation_handler({}, data(), wellness()))

    assert TRAINING_SCIENCE in output
    # Guidance for both paths, before the closing reminders.
    assert output.index(TRAINING_SCIENCE) > output.index("## Path B")
    assert output.index(TRAINING_SCIENCE) < output.index("## Important Reminders")
    assert output.endswith("Ready to begin? 🎯")


async def test_start_consultation_reads_hrv_and_rhr_against_the_athletes_baseline():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))
    data_sources = output.split("## Available Data Sources", 1)[1].split("## Path A", 1)[0]

    assert "Higher HRV = better" not in output
    assert "Lower RHR = better" not in output
    assert data_sources.count("own baseline") == 2


def test_wellness_descriptions_are_baseline_relative():
    for tool in (tools.get_hrv_data_tool(), tools.get_resting_heart_rate_tool()):
        assert "own baseline" in tool.description
        assert "indicate better" not in tool.description
    assert "own baseline" in BASELINE_NOTE


async def test_profile_interview_defers_to_the_shared_safety_list():
    output = text_of(await build_athlete_profile_handler({}))

    assert "start_consultation's Safety list" in output
    assert SAFETY_RULES.startswith("Safety - ")


def test_the_shared_safety_list_assumes_no_notes_storage():
    assert "notes" not in SAFETY_RULES


async def test_red_flags_go_into_the_notes_only_when_notes_can_be_saved(training_repo):
    with_storage = text_of(await start_consultation_handler({}, _intervals(), _intervals()))
    reminders = with_storage.split("## Important Reminders", 1)[1]

    assert "safety rule" in reminders and "save_consultation_notes" in reminders


async def test_without_storage_nothing_asks_to_record_red_flags_in_notes():
    output = text_of(await start_consultation_handler({}, _intervals(), _intervals()))
    reminders = output.split("## Important Reminders", 1)[1]

    assert "safety rule" not in reminders
    assert "Nothing is saved this chat" in reminders
