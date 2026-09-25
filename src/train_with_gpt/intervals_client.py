"""intervals.icu API client."""

import sys
from typing import Optional
import httpx

from .config import config


class IntervalsClient:
    """Client for interacting with the intervals.icu API."""

    BASE_URL = "https://intervals.icu/api/v1"

    def __init__(self):
        print(f"[DEBUG] intervals.icu credentials:", file=sys.stderr)
        print(f"  API_KEY: {'SET' if self.api_key else 'NOT SET'}", file=sys.stderr)

    @property
    def api_key(self) -> Optional[str]:
        """The personal API key, read from config on each use (single source of truth)."""
        return config.intervals_api_key

    def _auth(self) -> tuple[str, str]:
        """HTTP Basic auth tuple for intervals.icu (literal username 'API_KEY')."""
        if not self.api_key:
            raise ValueError("INTERVALS_API_KEY not configured")
        return ("API_KEY", self.api_key)

    async def get_activities(self, oldest: str, newest: str) -> list[dict]:
        """
        Fetch athlete activities within a date range.

        Args:
            oldest: ISO date (YYYY-MM-DD), inclusive
            newest: ISO date (YYYY-MM-DD), inclusive

        Returns:
            List of activity dictionaries
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/athlete/0/activities",
                auth=self._auth(),
                params={"oldest": oldest, "newest": newest},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def get_activity(self, activity_id: str, intervals: bool = True) -> dict:
        """
        Fetch detailed information about a specific activity, including
        precomputed HR/power zone times and per-lap interval stats.

        Args:
            activity_id: The intervals.icu activity ID (e.g. "i180171555")
            intervals: Whether to include icu_intervals / zone-time data

        Returns:
            Detailed activity dictionary
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/activity/{activity_id}",
                auth=self._auth(),
                params={"intervals": str(intervals).lower()},
                timeout=30.0,
            )
            if response.status_code == 404:
                raise Exception("Activity not found")
            response.raise_for_status()
            return response.json()

    async def get_activity_streams(
        self, activity_id: str, stream_types: Optional[list[str]] = None
    ) -> dict[str, dict]:
        """
        Fetch stream data for an activity.

        Args:
            activity_id: The intervals.icu activity ID
            stream_types: List of stream types to fetch (e.g. time, heartrate,
                distance, cadence, watts, velocity_smooth)

        Returns:
            Dict shaped {type: {"data": [...]}} to match the shape tools expect
        """
        if stream_types is None:
            stream_types = ["time", "heartrate", "distance", "cadence", "watts", "velocity_smooth"]

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/activity/{activity_id}/streams",
                auth=self._auth(),
                params={"types": ",".join(stream_types)},
                timeout=30.0,
            )
            if response.status_code == 404:
                raise Exception("Activity not found or no stream data available")
            response.raise_for_status()
            raw = response.json()
            return {item["type"]: {"data": item.get("data", [])} for item in raw}

    async def get_wellness(self, oldest: str, newest: str) -> list[dict]:
        """
        Fetch daily wellness records (sleep, HRV, resting HR, weight, etc.)
        within a date range.

        Args:
            oldest: ISO date (YYYY-MM-DD), inclusive
            newest: ISO date (YYYY-MM-DD), inclusive

        Returns:
            List of daily wellness dictionaries, each keyed by date via "id"
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/athlete/0/wellness",
                auth=self._auth(),
                params={"oldest": oldest, "newest": newest},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
