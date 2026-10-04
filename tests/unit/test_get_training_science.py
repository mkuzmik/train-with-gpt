"""Unit tests for the get_training_science guidance tool."""

import re

from tests.support import text_of
from train_with_gpt.intervals_client import IntervalsClient
from train_with_gpt.tools import (
    get_training_science_handler, get_training_science_tool, start_consultation_handler,
)


async def test_guidance_asks_the_model_to_research_and_check_sources_itself():
    output = text_of(await get_training_science_handler({}))

    assert "Search the web" in output and "PubMed" in output
    assert "Never cite a paper you haven't found in this conversation" in output
    assert "starting point, not a limit" in output
    assert "how sure (consensus / moderate / low / emerging / contested)" in output
    assert "suggest how\n  the athlete could go deeper" in output


async def test_guidance_carries_the_safety_referrals():
    output = text_of(await get_training_science_handler({}))
    safety = output.split("## Safety", 1)[1].split("## Starting points", 1)[0]

    assert "call emergency services" in safety
    assert "no training until it has resolved" in safety
    assert "no hard training" not in safety
    assert "low energy availability" in safety
    assert "under-18s" in safety


async def test_starting_points_are_doi_links():
    output = text_of(await get_training_science_handler({}))
    starting_points = output.split("## Starting points", 1)[1].strip().splitlines()[1:]

    assert len(starting_points) >= 10
    assert all(re.search(r"https://doi\.org/10\.\d{4,9}/\S+$", line) for line in starting_points)


def test_takes_no_arguments():
    assert get_training_science_tool().inputSchema["properties"] == {}


async def test_start_consultation_makes_the_coach_science_based_and_points_at_the_tool():
    output = text_of(await start_consultation_handler(
        {}, IntervalsClient(api_key="synthetic-key"), IntervalsClient(api_key="synthetic-key"),
    ))
    coaching = output.split("## Step 2", 1)[1].split("## Available Data Sources", 1)[0]

    assert "**get_training_science**" in coaching
    assert "bases\neverything on sport science and stays up to date with it" in coaching
    assert "research it on the web rather than\n  relying on memory" in coaching
    assert "suggests deeper research or a\n  professional" in coaching
