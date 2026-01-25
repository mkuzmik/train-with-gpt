"""Strava API client with authentication."""

import asyncio
import os
import sys
import webbrowser
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
from urllib.parse import urlparse, parse_qs
import httpx

from .config import config


# OAuth settings
PORT = 8111
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = "activity:read_all,activity:read,profile:read_all"

# Global for OAuth callback
auth_code = None
auth_error = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles OAuth callback from Strava."""
    
    def do_GET(self):
        global auth_code, auth_error
        
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == '/callback':
            if 'error' in params:
                auth_error = params['error'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: red;">Authorization Failed</h1>
                    <p>You can close this window.</p>
                    </body></html>
                ''')
            elif 'code' in params:
                auth_code = params['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'''
                    <html><body style="font-family: sans-serif; text-align: center; padding: 50px;">
                    <h1 style="color: green;">Success!</h1>
                    <p>Authentication successful. You can close this window.</p>
                    </body></html>
                ''')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        pass


class StravaClient:
    """Client for interacting with Strava API."""
    
    BASE_URL = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"
    
    def __init__(self):
        self.access_token = config.access_token
        self.refresh_token = config.refresh_token
        self.client_id = config.client_id
        self.client_secret = config.client_secret
        self.zones_cache = None  # Cache for athlete zones
        
        print(f"[DEBUG] Loaded credentials:", file=sys.stderr)
        print(f"  ACCESS_TOKEN: {self.access_token[:10] if self.access_token else 'NOT SET'}...", file=sys.stderr)
        print(f"  REFRESH_TOKEN: {self.refresh_token[:10] if self.refresh_token else 'NOT SET'}...", file=sys.stderr)
        print(f"  CLIENT_ID: {self.client_id if self.client_id else 'NOT SET'}", file=sys.stderr)
        print(f"  CLIENT_SECRET: {'SET' if self.client_secret else 'NOT SET'}", file=sys.stderr)
        
        if not self.access_token:
            print("Warning: STRAVA_ACCESS_TOKEN not set", file=sys.stderr)
    
    async def connect(self) -> dict:
        """
        Run OAuth flow to connect Strava account.
        Opens browser, waits for callback, exchanges code for tokens.
        
        Returns:
            dict with access_token, refresh_token, expires_at, athlete info
        """
        global auth_code, auth_error
        auth_code = None
        auth_error = None
        
        if not self.client_id or not self.client_secret:
            raise ValueError("Client credentials not configured")
        
        auth_url = (
            f"https://www.strava.com/oauth/authorize?"
            f"client_id={self.client_id}&"
            f"response_type=code&"
            f"redirect_uri={REDIRECT_URI}&"
            f"approval_prompt=force&"
            f"scope={SCOPES}"
        )
        
        print(f"[AUTH] Starting local server on port {PORT}...", file=sys.stderr)
        server = HTTPServer(('localhost', PORT), OAuthCallbackHandler)
        
        print(f"[AUTH] Opening browser for authorization...", file=sys.stderr)
        webbrowser.open(auth_url)
        
        # Wait for callback
        timeout_count = 0
        max_timeout = 300  # 5 minutes
        
        while auth_code is None and auth_error is None and timeout_count < max_timeout:
            server.handle_request()
            await asyncio.sleep(0.1)
            timeout_count += 1
        
        server.server_close()
        
        if timeout_count >= max_timeout:
            raise TimeoutError("Authentication timed out after 5 minutes")
        
        if auth_error:
            raise ValueError(f"Authorization failed: {auth_error}")
        
        if not auth_code:
            raise ValueError("No authorization code received")
        
        print("[AUTH] Authorization code received, exchanging for tokens...", file=sys.stderr)
        
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": auth_code,
                    "grant_type": "authorization_code",
                }
            )
            response.raise_for_status()
            data = response.json()
        
        # Update and save tokens
        self.access_token = data['access_token']
        self.refresh_token = data['refresh_token']
        expires_at = data.get('expires_at')
        
        config.save(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at=expires_at
        )
        
        return data
    
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
            config.save(
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
    
    async def get_athlete_zones(self, force_refresh: bool = False):
        """
        Get athlete's heart rate and power zones from Strava.
        Caches the result unless force_refresh is True.
        
        Returns dict with 'heart_rate' and 'power' zone configurations.
        """
        if self.zones_cache and not force_refresh:
            return self.zones_cache
        
        url = f"{self.BASE_URL}/athlete/zones"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        print(f"[DEBUG] Fetching athlete zones from: {url}", file=sys.stderr)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
            
            print(f"[DEBUG] Zones response status: {response.status_code}", file=sys.stderr)
            
            if response.status_code == 401:
                print("[DEBUG] 401 error, attempting token refresh", file=sys.stderr)
                await self.refresh_access_token()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                response = await client.get(url, headers=headers, timeout=30.0)
            
            if response.status_code == 200:
                self.zones_cache = response.json()
                return self.zones_cache
            else:
                error_msg = f"Failed to fetch zones: {response.status_code}"
                print(f"[DEBUG] {error_msg}", file=sys.stderr)
                raise Exception(error_msg)
    
    async def get_activity_streams(self, activity_id: int, stream_types: list[str] = None):
        """
        Get detailed stream data for an activity.
        
        Args:
            activity_id: Strava activity ID
            stream_types: List of stream types to fetch. Options:
                - time, latlng, distance, altitude, velocity_smooth,
                - heartrate, cadence, watts, temp, moving, grade_smooth
                Default: ['time', 'heartrate', 'velocity_smooth', 'cadence', 'watts', 'altitude']
        
        Returns dict with stream data arrays.
        """
        if stream_types is None:
            stream_types = ['time', 'heartrate', 'velocity_smooth', 'cadence', 'watts', 'altitude']
        
        stream_keys = ','.join(stream_types)
        url = f"{self.BASE_URL}/activities/{activity_id}/streams"
        params = {
            'keys': stream_keys,
            'key_by_type': 'true'
        }
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        print(f"[DEBUG] Fetching streams for activity {activity_id}", file=sys.stderr)
        print(f"[DEBUG] Stream types: {stream_keys}", file=sys.stderr)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            
            print(f"[DEBUG] Streams response status: {response.status_code}", file=sys.stderr)
            
            if response.status_code == 401:
                print("[DEBUG] 401 error, attempting token refresh", file=sys.stderr)
                await self.refresh_access_token()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                response = await client.get(url, headers=headers, params=params, timeout=30.0)
            
            if response.status_code == 200:
                return response.json()
            else:
                error_msg = f"Failed to fetch streams: {response.status_code}"
                print(f"[DEBUG] {error_msg}", file=sys.stderr)
                if response.status_code == 404:
                    raise Exception("Activity not found or no stream data available")
                raise Exception(error_msg)
    
    async def get_activity_laps(self, activity_id: int):
        """
        Get lap data for an activity.
        
        Args:
            activity_id: Strava activity ID
        
        Returns:
            List of lap objects with metrics for each lap.
        """
        url = f"{self.BASE_URL}/activities/{activity_id}/laps"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        print(f"[DEBUG] Fetching laps for activity {activity_id}", file=sys.stderr)
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
            
            print(f"[DEBUG] Laps response status: {response.status_code}", file=sys.stderr)
            
            if response.status_code == 401:
                print("[DEBUG] 401 error, attempting token refresh", file=sys.stderr)
                await self.refresh_access_token()
                headers = {"Authorization": f"Bearer {self.access_token}"}
                response = await client.get(url, headers=headers, timeout=30.0)
            
            if response.status_code == 200:
                laps = response.json()
                print(f"[DEBUG] Found {len(laps)} laps", file=sys.stderr)
                return laps
            elif response.status_code == 404:
                print(f"[DEBUG] Activity {activity_id} not found or no laps available", file=sys.stderr)
                return []  # Return empty list instead of raising exception
            else:
                error_msg = f"Failed to fetch laps: {response.status_code}"
                print(f"[DEBUG] {error_msg}", file=sys.stderr)
                raise Exception(error_msg)
