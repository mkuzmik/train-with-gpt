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
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expires_at: Optional[int] = None
        self.training_repo_path: Optional[str] = None
        
    def load(self):
        """Load config from file and environment variables."""
        # Load from config file
        file_config = self._load_file()
        
        # Priority: env vars > config file
        self.client_id = os.getenv("STRAVA_CLIENT_ID") or file_config.get("clientId")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET") or file_config.get("clientSecret")
        self.access_token = os.getenv("STRAVA_ACCESS_TOKEN") or file_config.get("accessToken")
        self.refresh_token = os.getenv("STRAVA_REFRESH_TOKEN") or file_config.get("refreshToken")
        self.expires_at = file_config.get("expiresAt")
        self.training_repo_path = file_config.get("trainingRepoPath")
        
        print(f"[CONFIG] Loaded from: {CONFIG_FILE}", file=sys.stderr)
        print(f"[CONFIG] Client ID: {self.client_id or 'NOT SET'}", file=sys.stderr)
        print(f"[CONFIG] Access Token: {'SET' if self.access_token else 'NOT SET'}", file=sys.stderr)
        
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
        if "client_id" in kwargs:
            existing["clientId"] = kwargs["client_id"]
            self.client_id = kwargs["client_id"]
        
        if "client_secret" in kwargs:
            existing["clientSecret"] = kwargs["client_secret"]
            self.client_secret = kwargs["client_secret"]
        
        if "access_token" in kwargs:
            existing["accessToken"] = kwargs["access_token"]
            self.access_token = kwargs["access_token"]
        
        if "refresh_token" in kwargs:
            existing["refreshToken"] = kwargs["refresh_token"]
            self.refresh_token = kwargs["refresh_token"]
        
        if "expires_at" in kwargs:
            existing["expiresAt"] = kwargs["expires_at"]
            self.expires_at = kwargs["expires_at"]
        
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
