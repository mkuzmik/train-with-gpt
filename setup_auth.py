#!/usr/bin/env python3
"""Interactive Strava authentication setup."""

import asyncio
import os
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import httpx
from dotenv import load_dotenv, set_key

load_dotenv()

PORT = 8111
REDIRECT_URI = f"http://localhost:{PORT}/callback"
SCOPES = "activity:read_all,activity:read,profile:read_all"

# Global to store the auth code
auth_code = None
auth_error = None


class CallbackHandler(BaseHTTPRequestHandler):
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
        # Suppress server logs
        pass


async def exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange authorization code for tokens."""
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
        response.raise_for_status()
        return response.json()


def update_env_file(access_token: str, refresh_token: str):
    """Update .env file with new tokens."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    
    if not os.path.exists(env_path):
        # Create from example
        example_path = env_path + '.example'
        if os.path.exists(example_path):
            with open(example_path, 'r') as f:
                with open(env_path, 'w') as out:
                    out.write(f.read())
    
    set_key(env_path, "STRAVA_ACCESS_TOKEN", access_token)
    set_key(env_path, "STRAVA_REFRESH_TOKEN", refresh_token)


async def main():
    """Run the authentication flow."""
    print("=" * 60)
    print("Train With GPT - Strava Authentication Setup")
    print("=" * 60)
    print()
    
    # Check for client credentials
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("❌ Missing Strava API credentials!")
        print()
        print("Please set up your Strava API application:")
        print("1. Go to https://www.strava.com/settings/api")
        print("2. Create an application if you haven't")
        print("3. Add these to your .env file:")
        print("   STRAVA_CLIENT_ID=your_client_id")
        print("   STRAVA_CLIENT_SECRET=your_client_secret")
        print("4. Set Authorization Callback Domain to: localhost")
        return
    
    print(f"✓ Client ID: {client_id}")
    print()
    
    # Build auth URL
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={REDIRECT_URI}&"
        f"approval_prompt=force&"
        f"scope={SCOPES}"
    )
    
    print("Starting local server on port 8111...")
    server = HTTPServer(('localhost', PORT), CallbackHandler)
    
    print("Opening browser for Strava authorization...")
    print()
    webbrowser.open(auth_url)
    
    print("Waiting for authorization...")
    print("(If browser doesn't open, visit this URL manually:)")
    print(auth_url)
    print()
    
    # Wait for callback
    global auth_code, auth_error
    while auth_code is None and auth_error is None:
        server.handle_request()
        await asyncio.sleep(0.1)
    
    server.server_close()
    
    if auth_error:
        print(f"❌ Authorization failed: {auth_error}")
        return
    
    if not auth_code:
        print("❌ No authorization code received")
        return
    
    print("✓ Authorization code received")
    print("Exchanging code for tokens...")
    
    try:
        data = await exchange_code(auth_code, client_id, client_secret)
        
        access_token = data['access_token']
        refresh_token = data['refresh_token']
        athlete = data.get('athlete', {})
        
        print("✓ Tokens received")
        print("Saving to .env file...")
        
        update_env_file(access_token, refresh_token)
        
        print()
        print("=" * 60)
        print("✅ Authentication successful!")
        print("=" * 60)
        print(f"Athlete: {athlete.get('firstname')} {athlete.get('lastname')}")
        print()
        print("Your tokens have been saved to .env")
        print("You can now restart Claude Desktop to use the server!")
        
    except Exception as e:
        print(f"❌ Failed to exchange code: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        sys.exit(0)
