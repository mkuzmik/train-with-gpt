"""Garmin Connect client with authentication."""

import sys
from pathlib import Path
from datetime import datetime
from garminconnect import Garmin, GarminConnectAuthenticationError, GarminConnectConnectionError
from typing import Optional

from .config import config


class GarminClient:
    """Client for interacting with Garmin Connect API."""
    
    def __init__(self):
        self.client: Optional[Garmin] = None
        self.garmin_email = config.garmin_email
        self.garmin_password = config.garmin_password
        self.token_store = Path.home() / ".garminconnect"
        
        print(f"[DEBUG] Garmin credentials:", file=sys.stderr)
        print(f"  EMAIL: {'SET' if self.garmin_email else 'NOT SET'}", file=sys.stderr)
        print(f"  PASSWORD: {'SET' if self.garmin_password else 'NOT SET'}", file=sys.stderr)
    
    async def login(self) -> dict:
        """
        Login to Garmin Connect.
        
        First tries to use existing tokens, then falls back to email/password.
        Tokens are automatically saved to ~/.garminconnect and are valid for 1 year.
        
        Returns:
            dict with login status and message
        """
        # Try to use existing tokens first
        try:
            print(f"[DEBUG] Attempting to use existing tokens from {self.token_store}", file=sys.stderr)
            self.client = Garmin()
            self.client.login(str(self.token_store))
            print(f"✅ Garmin Connect authenticated using existing tokens", file=sys.stderr)
            
            profile = self.client.get_full_name()
            return {
                "status": "success",
                "message": f"Connected to Garmin Connect as {profile}",
                "token_location": str(self.token_store),
            }
        except (FileNotFoundError, GarminConnectAuthenticationError, GarminConnectConnectionError) as e:
            print(f"[DEBUG] Token auth failed ({type(e).__name__}), trying password auth...", file=sys.stderr)
        
        # Fall back to email/password login
        if not self.garmin_email or not self.garmin_password:
            raise ValueError("GARMIN_EMAIL and GARMIN_PASSWORD must be configured in config file")
        
        try:
            print(f"[DEBUG] Attempting Garmin Connect password login...", file=sys.stderr)
            
            # Initialize Garmin client with credentials
            self.client = Garmin(email=self.garmin_email, password=self.garmin_password)
            
            # Login with credentials (this will create OAuth tokens)
            self.client.login()
            
            # Save tokens for future use
            self.token_store.mkdir(parents=True, exist_ok=True)
            self.client.garth.dump(str(self.token_store))
            
            print(f"✅ Garmin Connect login successful, tokens saved", file=sys.stderr)
            
            # Get user profile to verify connection
            profile = self.client.get_full_name()
            
            return {
                "status": "success",
                "message": f"Connected to Garmin Connect as {profile}",
                "token_location": str(self.token_store),
            }
        
        except Exception as e:
            print(f"[DEBUG] Garmin Connect login failed: {e}", file=sys.stderr)
            raise ValueError(f"Failed to connect to Garmin Connect: {str(e)}")
    
    def _ensure_logged_in(self):
        """Ensure client is logged in."""
        if not self.client:
            raise ValueError("Not connected to Garmin Connect. Please login first.")
    
    async def get_sleep_data(self, date: str) -> dict:
        """
        Get sleep data for a specific date.
        
        Automatically connects if not already logged in.
        
        Args:
            date: Date in YYYY-MM-DD format
        
        Returns:
            dict with sleep metrics
        """
        # Auto-login if not connected
        if not self.client:
            await self.login()
        
        try:
            print(f"[DEBUG] Fetching sleep data for {date}", file=sys.stderr)
            
            # Get sleep data from Garmin
            sleep_data = self.client.get_sleep_data(date)
            
            print(f"[DEBUG] Sleep data retrieved successfully", file=sys.stderr)
            
            return sleep_data
        
        except Exception as e:
            print(f"[DEBUG] Error fetching sleep data: {e}", file=sys.stderr)
            raise ValueError(f"Failed to get sleep data: {str(e)}")
    
    async def get_hrv_data(self, date: str) -> dict:
        """
        Get HRV (Heart Rate Variability) data for a specific date.
        
        Automatically connects if not already logged in.
        
        Args:
            date: Date in YYYY-MM-DD format
        
        Returns:
            dict with HRV metrics
        """
        # Auto-login if not connected
        if not self.client:
            await self.login()
        
        try:
            print(f"[DEBUG] Fetching HRV data for {date}", file=sys.stderr)
            
            # Get HRV data from Garmin
            hrv_data = self.client.get_hrv_data(date)
            
            print(f"[DEBUG] HRV data retrieved successfully", file=sys.stderr)
            
            return hrv_data
        
        except Exception as e:
            print(f"[DEBUG] Error fetching HRV data: {e}", file=sys.stderr)
            raise ValueError(f"Failed to get HRV data: {str(e)}")
    
    async def get_heart_rates(self, date: str) -> dict:
        """
        Get heart rate data including resting heart rate for a specific date.
        
        Automatically connects if not already logged in.
        
        Args:
            date: Date in YYYY-MM-DD format
        
        Returns:
            dict with heart rate metrics including resting HR
        """
        # Auto-login if not connected
        if not self.client:
            await self.login()
        
        try:
            print(f"[DEBUG] Fetching heart rate data for {date}", file=sys.stderr)
            
            # Get heart rate data from Garmin
            hr_data = self.client.get_heart_rates(date)
            
            print(f"[DEBUG] Heart rate data retrieved successfully", file=sys.stderr)
            
            return hr_data
        
        except Exception as e:
            print(f"[DEBUG] Error fetching heart rate data: {e}", file=sys.stderr)
            raise ValueError(f"Failed to get heart rate data: {str(e)}")


