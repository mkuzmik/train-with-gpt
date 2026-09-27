"""Tools module for train-with-gpt MCP server."""

from .setup_training_repo import setup_training_repo_tool, setup_training_repo_handler
from .start_consultation import start_consultation_tool, start_consultation_handler
from .get_activities import get_activities_tool, get_activities_handler
from .get_current_date import get_current_date_tool, get_current_date_handler
from .get_sleep_data import get_sleep_data_tool, get_sleep_data_handler
from .get_hrv_data import get_hrv_data_tool, get_hrv_data_handler
from .get_resting_heart_rate import get_resting_heart_rate_tool, get_resting_heart_rate_handler
from .analyze_activity import analyze_activity_tool, analyze_activity_handler
from .analyze_lap import analyze_lap_tool, analyze_lap_handler
from .save_goals import save_goals_tool, save_goals_handler
from .read_goals import read_goals_tool, read_goals_handler
from .save_consultation_notes import save_consultation_notes_tool, save_consultation_notes_handler
from .read_consultation_notes import read_consultation_notes_tool, read_consultation_notes_handler
from .list_consultation_notes import list_consultation_notes_tool, list_consultation_notes_handler
from .search_consultation_notes import search_consultation_notes_tool, search_consultation_notes_handler
from .self_test import self_test_tool, self_test_handler

__all__ = [
    "setup_training_repo_tool",
    "setup_training_repo_handler",
    "start_consultation_tool",
    "start_consultation_handler",
    "get_activities_tool",
    "get_activities_handler",
    "get_current_date_tool",
    "get_current_date_handler",
    "get_sleep_data_tool",
    "get_sleep_data_handler",
    "get_hrv_data_tool",
    "get_hrv_data_handler",
    "get_resting_heart_rate_tool",
    "get_resting_heart_rate_handler",
    "analyze_activity_tool",
    "analyze_activity_handler",
    "analyze_lap_tool",
    "analyze_lap_handler",
    "save_goals_tool",
    "save_goals_handler",
    "read_goals_tool",
    "read_goals_handler",
    "save_consultation_notes_tool",
    "save_consultation_notes_handler",
    "read_consultation_notes_tool",
    "read_consultation_notes_handler",
    "list_consultation_notes_tool",
    "list_consultation_notes_handler",
    "search_consultation_notes_tool",
    "search_consultation_notes_handler",
    "self_test_tool",
    "self_test_handler",
]
