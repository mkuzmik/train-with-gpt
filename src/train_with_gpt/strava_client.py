"""Strava API client for OAuth'd multi-user sessions.

Unlike `intervals_client.py` (one shared personal API key), this client is
constructed per-request with one user's tokens. It refreshes its own access
token on expiry/401 and calls back into `on_refresh` so the caller can
persist the rotated token (see `store.py`).
"""

import sys
import time
from typing import Awaitable, Callable, Optional

import httpx

from .config import config

TOKEN_URL = "https://www.strava.com/oauth/token"
AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
SCOPES = "activity:read_all,activity:read,profile:read_all"


class StravaClient:
    """Client for interacting with the Strava API on behalf of one user."""

    BASE_URL = "https://www.strava.com/api/v3"

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_at: Optional[int] = None,
        on_refresh: Optional[Callable[[str, Optional[str], Optional[int]], Awaitable[None]]] = None,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.on_refresh = on_refresh
        self.zones_cache = None

    async def _ensure_fresh_token(self) -> None:
        """Proactively refresh if the token is expired or about to expire."""
        if not self.refresh_token or not self.expires_at:
            return
        if self.expires_at > time.time() + 60:
            return
        await self._refresh()

    async def _refresh(self) -> None:
        if not self.refresh_token or not config.client_id or not config.client_secret:
            raise ValueError("Missing credentials for Strava token refresh")

        print("[Strava] Refreshing access token...", file=sys.stderr)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = data.get("expires_at")

        if self.on_refresh:
            await self.on_refresh(self.access_token, self.refresh_token, self.expires_at)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _get(self, url: str, params: Optional[dict] = None, timeout: float = 30.0) -> httpx.Response:
        await self._ensure_fresh_token()

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self._headers(), params=params, timeout=timeout)

            if response.status_code == 401 and self.refresh_token:
                await self._refresh()
                response = await client.get(url, headers=self._headers(), params=params, timeout=timeout)

            return response

    async def get_athlete(self) -> dict:
        """Fetch the authenticated athlete's profile (used to learn their stable id)."""
        response = await self._get(f"{self.BASE_URL}/athlete")
        response.raise_for_status()
        return response.json()

    async def get_activities(
        self,
        before: Optional[int] = None,
        after: Optional[int] = None,
        page: int = 1,
        per_page: int = 30,
    ) -> list[dict]:
        params = {"page": page, "per_page": min(per_page, 200)}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        response = await self._get(f"{self.BASE_URL}/athlete/activities", params=params)
        response.raise_for_status()
        return response.json()

    async def get_activity_details(self, activity_id: int) -> dict:
        response = await self._get(f"{self.BASE_URL}/activities/{activity_id}")
        response.raise_for_status()
        return response.json()

    async def get_athlete_zones(self, force_refresh: bool = False) -> dict:
        if self.zones_cache and not force_refresh:
            return self.zones_cache

        response = await self._get(f"{self.BASE_URL}/athlete/zones")
        if response.status_code != 200:
            raise Exception(f"Failed to fetch zones: {response.status_code}")
        self.zones_cache = response.json()
        return self.zones_cache

    async def get_activity_streams(self, activity_id: int, stream_types: Optional[list[str]] = None) -> dict:
        if stream_types is None:
            stream_types = ["time", "heartrate", "velocity_smooth", "cadence", "watts", "altitude"]

        response = await self._get(
            f"{self.BASE_URL}/activities/{activity_id}/streams",
            params={"keys": ",".join(stream_types), "key_by_type": "true"},
        )

        if response.status_code == 404:
            raise Exception("Activity not found or no stream data available")
        if response.status_code != 200:
            raise Exception(f"Failed to fetch streams: {response.status_code}")
        return response.json()

    async def get_activity_laps(self, activity_id: int) -> list[dict]:
        response = await self._get(f"{self.BASE_URL}/activities/{activity_id}/laps")

        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise Exception(f"Failed to fetch laps: {response.status_code}")
        return response.json()
