#!/usr/bin/env python3
"""One-time OAuth setup for Clay's MCP endpoint.

Run this locally to get the OAuth credentials needed for Railway:

    python scripts/clay_oauth_setup.py

It will:
1. Register as an OAuth client with Clay
2. Open your browser to Clay's login page
3. Catch the redirect after you authorize
4. Exchange the code for tokens
5. Print the env vars to set in Railway
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CLAY_AUTH_SERVER = "https://api.clay.com"
CLAY_AUTHORIZE_URL = "https://app.clay.com/oauth/authorize"
CLAY_TOKEN_URL = "https://api.clay.com/oauth/token"
CLAY_REGISTER_URL = "https://api.clay.com/oauth/register"
REDIRECT_PORT = 9876
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPES = "mcp mcp:run-enrichment"


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(96)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _register_client() -> tuple[str, str]:
    """Dynamically register as an OAuth client with Clay."""
    print("\n[1/4] Registering OAuth client with Clay...")

    response = httpx.post(
        CLAY_REGISTER_URL,
        json={
            "client_name": "tender-intelligence-agent",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": SCOPES,
            "token_endpoint_auth_method": "client_secret_post",
        },
        timeout=15.0,
    )

    if response.status_code not in (200, 201):
        print(f"Registration failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

    data = response.json()
    client_id = data["client_id"]
    client_secret = data.get("client_secret", "")

    print(f"  Client registered: {client_id}")
    return client_id, client_secret


def _authorize(client_id: str, code_challenge: str) -> str:
    """Open browser for authorization, capture the callback code."""
    state = secrets.token_urlsafe(32)
    auth_code: list[str] = []
    error_msg: list[str] = []

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return

            params = parse_qs(parsed.query)

            if "error" in params:
                error_msg.append(params["error"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Authorization failed</h1><p>You can close this tab.</p>")
                return

            received_state = params.get("state", [""])[0]
            if received_state != state:
                error_msg.append("State mismatch")
                self.send_response(400)
                self.end_headers()
                return

            code = params.get("code", [""])[0]
            if code:
                auth_code.append(code)

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h1>Authorization successful!</h1>"
                b"<p>You can close this tab and return to the terminal.</p>"
            )

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress request logs

    server = HTTPServer(("localhost", REDIRECT_PORT), CallbackHandler)

    auth_params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "scope": SCOPES,
    })
    auth_url = f"{CLAY_AUTHORIZE_URL}?{auth_params}"

    print(f"\n[2/4] Opening browser for Clay authorization...")
    print(f"  If the browser doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("  Waiting for authorization callback...")

    # Wait up to 5 minutes
    server.timeout = 300
    while not auth_code and not error_msg:
        server.handle_request()

    server.server_close()

    if error_msg:
        print(f"  Authorization failed: {error_msg[0]}")
        sys.exit(1)

    if not auth_code:
        print("  No authorization code received")
        sys.exit(1)

    print("  Authorization code received!")
    return auth_code[0]


def _exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    code_verifier: str,
) -> dict:
    """Exchange authorization code for tokens."""
    print("\n[3/4] Exchanging code for tokens...")

    response = httpx.post(
        CLAY_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
        timeout=15.0,
    )

    if response.status_code != 200:
        print(f"  Token exchange failed: {response.status_code}")
        print(f"  {response.text}")
        sys.exit(1)

    data = response.json()
    print("  Tokens received!")
    return data


def main() -> None:
    print("=" * 60)
    print("  Clay MCP OAuth Setup")
    print("=" * 60)

    # Step 1: Register client
    client_id, client_secret = _register_client()

    # Step 2: Generate PKCE and authorize
    code_verifier, code_challenge = _generate_pkce()
    auth_code = _authorize(client_id, code_challenge)

    # Step 3: Exchange code for tokens
    tokens = _exchange_code(client_id, client_secret, auth_code, code_verifier)

    # Step 4: Print results
    refresh_token = tokens.get("refresh_token", "")
    access_token = tokens.get("access_token", "")
    expires_in = tokens.get("expires_in", "unknown")

    print(f"\n[4/4] Setup complete!")
    print()
    print("=" * 60)
    print("  Add these env vars to Railway:")
    print("=" * 60)
    print()
    print(f"CLAY_OAUTH_CLIENT_ID={client_id}")
    print(f"CLAY_OAUTH_CLIENT_SECRET={client_secret}")
    print(f"CLAY_OAUTH_REFRESH_TOKEN={refresh_token}")
    print()
    print(f"  Access token expires in: {expires_in}s")
    print(f"  The refresh token will be used to auto-renew access tokens.")
    print(f"  If the refresh token ever expires, re-run this script.")
    print()


if __name__ == "__main__":
    main()
