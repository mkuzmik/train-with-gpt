"""Optional "connect intervals.icu" step inside the OAuth login flow.

After Strava's callback identifies the user, and before redirecting back to
Claude, we show one page asking for the user's personal intervals.icu API key
(Strava has no sleep/HRV/resting-HR data; intervals.icu has it from Garmin).
The key goes straight from the browser to this server - never through Claude
or the chat - is validated against intervals.icu, and is stored encrypted
(secret_box.py). Skipping finishes the login exactly as before.

Only shown when TOKEN_ENCRYPTION_KEY is configured.
"""

import html
import secrets
import sys

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

from . import secret_box, store
from .authorization import complete_authorization
from .intervals_client import IntervalsClient

CONNECT_PATH = "/oauth/intervals/connect"
STEP_TTL_SECONDS = 15 * 60

_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
}


def start_connect_step(pending: dict, user_id: str) -> HTMLResponse:
    """Park the Claude authorization request and show the connect page."""
    token = secrets.token_urlsafe(32)
    store.save_pending_connect_step(token, user_id, pending)
    return _render(token, store.get_intervals_connection(user_id))


def _render(token: str, connection: dict | None, error: str | None = None, status_code: int = 200) -> HTMLResponse:
    esc = html.escape
    if connection:
        who = esc(connection["athlete_name"] or connection["athlete_id"])
        status = f'<p class="ok">Connected as <b>{who}</b>. Paste a new key to replace it.</p>'
        skip_label = "Keep current and continue"
        disconnect = '<button class="link" name="action" value="disconnect">Disconnect intervals.icu</button>'
    else:
        status = ""
        skip_label = "Skip"
        disconnect = ""
    error_html = f'<p class="err">{esc(error)}</p>' if error else ""

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect intervals.icu</title>
<style>
  body {{ font: 16px/1.5 system-ui, sans-serif; max-width: 30rem; margin: 2rem auto; padding: 0 1rem; color: #222; background: #fff; }}
  h1 {{ font-size: 1.3rem; }}
  input {{ width: 100%; box-sizing: border-box; padding: .6rem; font: inherit; margin: .3rem 0 1rem; }}
  button {{ font: inherit; padding: .6rem 1rem; margin: 0 .5rem .5rem 0; cursor: pointer; }}
  .primary {{ background: #1f6feb; color: #fff; border: 0; border-radius: 6px; }}
  .link {{ background: none; border: 0; color: #b42318; padding: 0; text-decoration: underline; }}
  .ok {{ color: #1a7f37; }} .err {{ color: #b42318; }} .muted {{ color: #666; font-size: .9rem; }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #111; color: #eee; }} .muted {{ color: #aaa; }} }}
</style></head><body>
<h1>Add sleep, HRV and resting HR (optional)</h1>
<p>Strava has no wellness data. If your Garmin syncs to intervals.icu, paste your
intervals.icu API key to use it.</p>
<p class="muted">Find it on intervals.icu under Settings &rarr; Developer Settings &rarr; API key.
It is stored encrypted and only used to read your data. You can cut access
at any time by regenerating the key there.</p>
{status}{error_html}
<form method="post" action="{CONNECT_PATH}" autocomplete="off">
  <input type="hidden" name="token" value="{esc(token)}">
  <label for="api_key">intervals.icu API key</label>
  <input id="api_key" name="api_key" type="password" autocomplete="off" spellcheck="false">
  <button class="primary" name="action" value="connect">Connect</button>
  <button name="action" value="skip">{skip_label}</button>
  <p>{disconnect}</p>
</form>
</body></html>"""
    return HTMLResponse(page, status_code=status_code, headers=_HEADERS)


async def handle_connect(request: Request):
    form = await request.form()
    token = str(form.get("token") or "")
    action = str(form.get("action") or "skip")

    # Claimed (deleted) up front so two concurrent submits can't both finish
    # the same Claude authorization; put back only when the user should retry.
    step = store.claim_pending_connect_step(token, STEP_TTL_SECONDS) if token else None
    if not step:
        return PlainTextResponse(
            "This sign-in link has expired. Start connecting again from Claude.", status_code=400
        )
    user_id = step["user_id"]

    def retry(message: str, status_code: int) -> HTMLResponse:
        store.save_pending_connect_step(token, user_id, step["pending"])
        return _render(token, store.get_intervals_connection(user_id), message, status_code)

    if action == "disconnect":
        store.delete_intervals_connection(user_id)
        print(f"[intervals.icu] Disconnected user {user_id}", file=sys.stderr)
    elif action == "connect":
        api_key = str(form.get("api_key") or "").strip()
        if not api_key:
            return retry("Paste your API key first.", 400)
        try:
            athlete = await IntervalsClient(api_key=api_key).get_athlete()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                message = "intervals.icu rejected that key. Check you copied the whole key."
            else:
                message = "intervals.icu returned an error. Try again in a moment."
            return retry(message, 400)
        except httpx.HTTPError:
            return retry("Couldn't reach intervals.icu. Try again.", 502)

        store.save_intervals_connection(
            user_id=user_id,
            athlete_id=str(athlete.get("id", "")),
            athlete_name=athlete.get("name"),
            encrypted_api_key=secret_box.encrypt(api_key),
        )
        print(f"[intervals.icu] Connected user {user_id} to athlete {athlete.get('id')}", file=sys.stderr)

    return complete_authorization(step["pending"], user_id)


intervals_connect_route = Route(CONNECT_PATH, handle_connect, methods=["POST"])
