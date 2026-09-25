"""Unit tests for the static training-science guidance and the tool references
in the guidance prompts."""

import re
from pathlib import Path

import pytest

from tests.support import text_of
from train_with_gpt import tools
from train_with_gpt.coaching_science import (
    BASELINE_NOTE, PRINCIPLES, SAFETY_RULES, TRAINING_SCIENCE, TRAINING_SCIENCE_MAX_CHARS,
)
from train_with_gpt.tools import discuss_goals_handler, start_consultation_handler

DESIGN_DOC = Path(__file__).parents[2] / "docs" / "ideas" / "science-based-coaching.md"
DOI = re.compile(r"10\.\d{4,9}/[^\s;,)\]]+")
# Anything that looks like a tool name: a known verb prefix plus snake_case.
TOOL_REFERENCE = re.compile(r"\b(?:get|read|save|list|search|analyze|discuss|setup|start)_[a-z_]+\b")


def _existing_tool_names() -> set[str]:
    return {getattr(tools, name)().name for name in tools.__all__ if name.endswith("_tool")}


def _referenced_dois() -> set[str]:
    references = DESIGN_DOC.read_text().split("\n## References\n", 1)[1]
    return {doi.lower() for doi in DOI.findall(references)}


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


def test_every_doi_is_in_the_design_docs_verified_references():
    cited = {doi.lower() for doi in DOI.findall(TRAINING_SCIENCE)}
    assert cited, "the section should cite its sources by DOI"
    assert cited <= _referenced_dois()


@pytest.mark.parametrize("handler", [discuss_goals_handler, start_consultation_handler])
async def test_guidance_only_references_tools_that_exist(handler):
    output = text_of(await handler({}))

    referenced = set(TOOL_REFERENCE.findall(output))
    assert referenced, "expected the guidance to name some tools"
    assert referenced <= _existing_tool_names()


async def test_discuss_goals_points_at_get_activities():
    output = text_of(await discuss_goals_handler({}))

    assert "get_activities" in output
    assert "get_last_week_activities" not in output


async def test_start_consultation_ends_with_the_training_science_section():
    output = text_of(await start_consultation_handler({}))

    assert output.endswith(TRAINING_SCIENCE)
    assert "Higher HRV = better" not in output
    assert "Lower RHR = better" not in output
    assert "own baseline" in output


def test_wellness_descriptions_are_baseline_relative():
    for tool in (tools.get_hrv_data_tool(), tools.get_resting_heart_rate_tool()):
        assert "own baseline" in tool.description
        assert "indicate better" not in tool.description
    assert "own baseline" in BASELINE_NOTE
