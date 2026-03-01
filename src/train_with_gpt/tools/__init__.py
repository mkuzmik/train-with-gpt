"""Tools module for train-with-gpt MCP server."""

from .setup_training_repo import setup_training_repo_tool, setup_training_repo_handler
from .connect_strava import connect_strava_tool, connect_strava_handler
from .start_consultation import start_consultation_tool, start_consultation_handler
from .get_activities import get_activities_tool, get_activities_handler
from .get_current_date import get_current_date_tool, get_current_date_handler
from .get_sleep_data import get_sleep_data_tool, get_sleep_data_handler
from .analyze_activity import analyze_activity_tool, analyze_activity_handler
from .discuss_goals import discuss_goals_tool, discuss_goals_handler
from .save_goals import save_goals_tool, save_goals_handler
from .read_goals import read_goals_tool, read_goals_handler
from .save_consultation_notes import save_consultation_notes_tool, save_consultation_notes_handler
from .read_consultation_notes import read_consultation_notes_tool, read_consultation_notes_handler

__all__ = [
    "setup_training_repo_tool",
    "setup_training_repo_handler",
    "connect_strava_tool",
    "connect_strava_handler",
    "start_consultation_tool",
    "start_consultation_handler",
    "get_activities_tool",
    "get_activities_handler",
    "get_current_date_tool",
    "get_current_date_handler",
    "get_sleep_data_tool",
    "get_sleep_data_handler",
    "analyze_activity_tool",
    "analyze_activity_handler",
    "discuss_goals_tool",
    "discuss_goals_handler",
    "save_goals_tool",
    "save_goals_handler",
    "read_goals_tool",
    "read_goals_handler",
    "save_consultation_notes_tool",
    "save_consultation_notes_handler",
    "read_consultation_notes_tool",
    "read_consultation_notes_handler",
]
