"""Strava API client for fetching activities."""

import os
import sys
from datetime import datetime, timedelta
from typing import Optional
import httpx

from .config import config


class StravaClient:
    """Client for interacting with Strava API."""
    
    BASE_URL = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"
    
    def __init__(self):
        self.access_token = config.access_token
        self.refresh_token = config.refresh_token
        self.client_id = config.client_id
        self.client_secret = config.client_secret
        
        print(f"[DEBUG] Loaded credentials:", file=sys.stderr)
        print(f"  ACCESS_TOKEN: {self.access_token[:10] if self.access_token else 'NOT SET'}...", file=sys.stderr)
        print(f"  REFRESH_TOKEN: {self.refresh_token[:10] if self.refresh_token else 'NOT SET'}...", file=sys.stderr)
        print(f"  CLIENT_ID: {self.client_id if self.client_id else 'NOT SET'}", file=sys.stderr)
        print(f"  CLIENT_SECRET: {'SET' if self.client_secret else 'NOT SET'}", file=sys.stderr)
        
        if not self.access_token:
            print("Warning: STRAVA_ACCESS_TOKEN not set", file=sys.stderr)
    
    async def refresh_access_token(self) -> str:
        """Refresh the access token using the refresh token."""
        if not all([self.refresh_token, self.client_id, self.client_secret]):
            raise ValueError("Missing credentials for token refresh")
        
        print("🔄 Refreshing Strava access token...", file=sys.stderr)
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                }
            )
            response.raise_for_status()
            data = response.json()
            
            new_access_token = data["access_token"]
            new_refresh_token = data["refresh_token"]
            expires_at = data.get("expires_at")
            
            # Update tokens
            self.access_token = new_access_token
            self.refresh_token = new_refresh_token
            
            # Save to config
            from .config import config as global_config
            global_config.save(
                access_token=new_access_token,
                refresh_token=new_refresh_token,
                expires_at=expires_at
            )
            
            if expires_at:
                expiry_date = datetime.fromtimestamp(expires_at)
                print(f"✅ Token refreshed. Expires: {expiry_date}", file=sys.stderr)
            
            return new_access_token
    
    def _get_headers(self) -> dict:
        """Get headers with authorization token."""
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
    
    async def get_activities(
        self,
        before: Optional[int] = None,
        after: Optional[int] = None,
        page: int = 1,
        per_page: int = 30
    ) -> list[dict]:
        """
        Fetch athlete activities.
        
        Args:
            before: Epoch timestamp to use for filtering activities before this time
            after: Epoch timestamp to use for filtering activities after this time
            page: Page number
            per_page: Number of items per page (max 200)
        
        Returns:
            List of activity dictionaries
        """
        if not self.access_token:
            raise ValueError("STRAVA_ACCESS_TOKEN not configured")
        
        params = {
            "page": page,
            "per_page": min(per_page, 200),
        }
        
        if before:
            params["before"] = before
        if after:
            params["after"] = after
        
        url = f"{self.BASE_URL}/athlete/activities"
        headers = self._get_headers()
        
        print(f"[DEBUG] Making request to: {url}", file=sys.stderr)
        print(f"[DEBUG] Params: {params}", file=sys.stderr)
        print(f"[DEBUG] Authorization header: Bearer {self.access_token[:10]}...", file=sys.stderr)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers=headers,
                params=params,
            )
            
            print(f"[DEBUG] Response status: {response.status_code}", file=sys.stderr)
            
            # If 401, try to refresh token and retry
            if response.status_code == 401:
                print(f"[DEBUG] Got 401, attempting token refresh...", file=sys.stderr)
                try:
                    await self.refresh_access_token()
                    # Retry with new token
                    headers = self._get_headers()
                    response = await client.get(url, headers=headers, params=params)
                    print(f"[DEBUG] Retry response status: {response.status_code}", file=sys.stderr)
                except Exception as e:
                    print(f"[DEBUG] Token refresh failed: {e}", file=sys.stderr)
                    raise
            
            if response.status_code != 200:
                print(f"[DEBUG] Response body: {response.text}", file=sys.stderr)
            
            response.raise_for_status()
            return response.json()
    
    async def get_recent_activities(self, per_page: int = 30) -> list[dict]:
        """Fetch the most recent activities."""
        return await self.get_activities(per_page=per_page)
    
    async def get_activities_last_week(self) -> list[dict]:
        """Fetch activities from the last 7 days."""
        now = datetime.now()
        week_ago = now - timedelta(days=7)
        after_timestamp = int(week_ago.timestamp())
        
        return await self.get_activities(after=after_timestamp, per_page=200)
    
    async def get_activity_details(self, activity_id: int) -> dict:
        """
        Fetch detailed information about a specific activity.
        
        Args:
            activity_id: The Strava activity ID
        
        Returns:
            Detailed activity dictionary
        """
        if not self.access_token:
            raise ValueError("STRAVA_ACCESS_TOKEN not configured")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.BASE_URL}/activities/{activity_id}",
                headers=self._get_headers(),
            )
            response.raise_for_status()
            return response.json()
