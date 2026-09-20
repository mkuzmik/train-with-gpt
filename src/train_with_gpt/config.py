"""Configuration management for train-with-gpt."""

import json
import os
import sys
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path.home() / ".config" / "train-with-gpt"
CONFIG_FILE = CONFIG_DIR / "config.json"


class Config:
    """Manages train-with-gpt configuration."""

    def __init__(self):
        self.intervals_api_key: Optional[str] = None
        self.training_repo_path: Optional[str] = None
        # Strava app credentials, used only by the multi-user OAuth path
        # (strava_client.py / strava_oauth.py) to talk to Strava on our
        # server's behalf - not a per-user secret.
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None

    def load(self):
        """Load config from file and environment variables."""
        # Load from config file
        file_config = self._load_file()

        # Priority: env vars > config file
        self.intervals_api_key = os.getenv("INTERVALS_API_KEY") or file_config.get("intervalsApiKey")
        self.training_repo_path = file_config.get("trainingRepoPath")
        self.client_id = os.getenv("STRAVA_CLIENT_ID") or file_config.get("clientId")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET") or file_config.get("clientSecret")

        print(f"[CONFIG] Loaded from: {CONFIG_FILE}", file=sys.stderr)
        print(f"[CONFIG] Intervals API Key: {'SET' if self.intervals_api_key else 'NOT SET'}", file=sys.stderr)
        print(f"[CONFIG] Strava Client ID: {self.client_id or 'NOT SET'}", file=sys.stderr)

    def _load_file(self) -> dict:
        """Load configuration from JSON file."""
        if not CONFIG_FILE.exists():
            return {}

        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[CONFIG] Error loading config file: {e}", file=sys.stderr)
            return {}

    def save(self, **kwargs):
        """Save configuration to file."""
        # Ensure directory exists
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # Load existing config
        existing = self._load_file()

        # Update with new values
        if "intervals_api_key" in kwargs:
            existing["intervalsApiKey"] = kwargs["intervals_api_key"]
            self.intervals_api_key = kwargs["intervals_api_key"]

        if "training_repo_path" in kwargs:
            existing["trainingRepoPath"] = kwargs["training_repo_path"]
            self.training_repo_path = kwargs["training_repo_path"]

        # Write to file
        with open(CONFIG_FILE, 'w') as f:
            json.dump(existing, f, indent=2)

        print(f"[CONFIG] Saved to: {CONFIG_FILE}", file=sys.stderr)

    def get_config_path(self) -> str:
        """Get the configuration file path."""
        return str(CONFIG_FILE)


# Global config instance
config = Config()
config.load()
