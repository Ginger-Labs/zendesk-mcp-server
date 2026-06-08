"""End-to-end verification of the OAuth gateway in front of the MCP server.

Drives the full MCP OAuth 2.1 browser dance headlessly against a locally running
sigbit/mcp-auth-proxy (password / built-in-IdP mode):

  1. assert an unauthenticated MCP request is rejected,
  2. dynamic client registration (RFC 7591),
  3. authorize -> password login -> consent,
  4. PKCE token exchange,
  5. authenticated `initialize` + `tools/list` through the gateway.

Run the gateway first (see oauth-gateway/README.md), then:

    GATEWAY_PASSWORD=<pw> uv run python oauth-gateway/verify_oauth_e2e.py

Env knobs:
    GATEWAY_URL       gateway base URL (default: http://localhost:9090)
    GATEWAY_PASSWORD  built-in-IdP login password (required)
"""

import asyncio
import base64
import hashlib
import os
import secrets
import sys
import urllib.parse

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

BASE = os.environ.get("GATEWAY_URL", "http://localhost:9090").rstrip("/")
REDIRECT = "http://127.0.0.1:7777/callback"


def _pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


async def run_oauth_dance(password: str) -> str:
    """Complete the browser OAuth flow and return a bearer access token."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        registration = await client.post(
            f"{BASE}/.idp/register",
            json={
                "client_name": "oauth-gateway-verifier",
                "redirect_uris": [REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        registration.raise_for_status()
        client_id = registration.json()["client_id"]

        verifier, challenge = _pkce()
        authorize_params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(16),
        }

        # Authorize bounces to the login page; submitting the password redirects
        # back to the per-request auth-session URL.
        await client.get(f"{BASE}/.idp/auth", params=authorize_params)
        login = await client.post(
            f"{BASE}/.auth/login", data={"password": password}, follow_redirects=False
        )
        resume = login.headers.get("location")
        if not resume:
            raise SystemExit(f"login did not redirect (HTTP {login.status_code}); bad password?")
        resume = resume if resume.startswith("http") else BASE + resume

        # The authenticated session shows a consent screen; POSTing it (the human
        # clicking "Authorize") redirects with the auth code to REDIRECT.
        callback = await _follow_to_callback(client, resume)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(callback).query)
        if "error" in query:
            raise SystemExit(f"authorize error: {query}")
        code = query["code"][0]

        token_response = await client.post(
            f"{BASE}/.idp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        token_response.raise_for_status()
        token = token_response.json()
        print(
            f"  token_type={token.get('token_type')} "
            f"refresh_token={'yes' if token.get('refresh_token') else 'no'} "
            f"expires_in={token.get('expires_in')}"
        )
        return token["access_token"]


async def _follow_to_callback(client: httpx.AsyncClient, url: str) -> str:
    for _ in range(8):
        response = await client.get(url, follow_redirects=False)
        location = response.headers.get("location", "")
        if location.startswith(REDIRECT):
            return location
        if response.is_redirect and location:
            url = location if location.startswith("http") else BASE + location
            continue
        if "Authorize" in response.text and "<form" in response.text:
            consent = await client.post(url, follow_redirects=False)
            location = consent.headers.get("location", "")
            if location.startswith(REDIRECT):
                return location
            url = location if location.startswith("http") else BASE + location
            continue
        break
    raise SystemExit("never reached the OAuth callback with an authorization code")


async def assert_unauthenticated_rejected() -> None:
    try:
        async with streamablehttp_client(f"{BASE}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
    except Exception:
        print("  unauthenticated initialize rejected (expected)")
        return
    raise SystemExit("FAIL: unauthenticated MCP request was NOT rejected")


async def main() -> None:
    password = os.environ.get("GATEWAY_PASSWORD")
    if not password:
        sys.exit("set GATEWAY_PASSWORD to the gateway's built-in-IdP login password")

    print("1. negative check")
    await assert_unauthenticated_rejected()

    print("2. OAuth dance (register -> login -> consent -> token)")
    token = await run_oauth_dance(password)

    print("3. authenticated MCP through the gateway")
    async with streamablehttp_client(
        f"{BASE}/mcp", headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            print(f"  initialize -> {init.serverInfo.name} {init.serverInfo.version}")
            print(f"  tools/list -> {len(tools.tools)} tools")

    print("\nPASS: OAuth handshake verified end-to-end")


if __name__ == "__main__":
    asyncio.run(main())
