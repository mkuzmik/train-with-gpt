#!/usr/bin/env python3
"""Exchange Strava authorization code for access tokens."""

import os
import sys
import httpx
import asyncio
from dotenv import load_dotenv

load_dotenv()

async def exchange_code(code: str):
    """Exchange authorization code for access tokens."""
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("Error: STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET must be set in .env")
        sys.exit(1)
    
    print(f"Exchanging code for tokens...")
    print(f"Client ID: {client_id}")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.strava.com/oauth/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            }
        )
        
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(response.text)
            sys.exit(1)
        
        data = response.json()
        
        print("\n✅ Success! Add these to your .env file:")
        print(f"\nSTRAVA_ACCESS_TOKEN={data['access_token']}")
        print(f"STRAVA_REFRESH_TOKEN={data['refresh_token']}")
        
        if 'athlete' in data:
            athlete = data['athlete']
            print(f"\nAthlete: {athlete.get('firstname')} {athlete.get('lastname')}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python exchange_token.py <code>")
        sys.exit(1)
    
    code = sys.argv[1]
    asyncio.run(exchange_code(code))
