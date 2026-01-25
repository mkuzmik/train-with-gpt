"""Authentication tools for connecting Strava account."""

import asyncio
import sys
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import httpx


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


async def start_auth_flow(client_id: str, client_secret: str) -> dict:
    """Start the OAuth flow and wait for completion."""
    global auth_code, auth_error
    auth_code = None
    auth_error = None
    
    auth_url = (
        f"https://www.strava.com/oauth/authorize?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={REDIRECT_URI}&"
        f"approval_prompt=force&"
        f"scope={SCOPES}"
    )
    
    print(f"[AUTH] Starting local server on port {PORT}...", file=sys.stderr)
    server = HTTPServer(('localhost', PORT), CallbackHandler)
    
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
    data = await exchange_code(auth_code, client_id, client_secret)
    
    return data
