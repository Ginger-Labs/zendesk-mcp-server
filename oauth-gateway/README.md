# OAuth gateway spike

Proof-of-concept: put an MCP-aware OAuth 2.1 gateway in front of this Zendesk
MCP server so a remote MCP client (Claude Desktop, MCP Inspector, `mcp-remote`,
etc.) authenticates with a browser "Sign in" flow instead of any terminal setup.
The end user pastes one URL into their MCP client; the gateway runs the OAuth
dance and proxies authenticated traffic to the loopback-bound MCP server.

```
MCP client --(OAuth 2.1 browser flow + Bearer token)--> gateway :9090
                                                            |
                                              (plain MCP, loopback)
                                                            v
                          ZENDESK_MCP_TRANSPORT=streamable-http server :8000
                                                            |
                                                            v
                                  single shared Zendesk API token (.env)
```

The user authenticates to **our gateway**. The gateway holds the Zendesk
credentials (the shared API token in `.env`); the authenticated identity maps
server-side to that one token. Zendesk never sees per-user identities.

## Gateway choice: `sigbit/mcp-auth-proxy`

Chosen over the alternatives because it is the lowest-effort path that genuinely
implements the MCP auth handshake, not just a bearer check:

- **Drop-in, no code changes** to the MCP server. Pass the upstream MCP URL as a
  positional arg; the proxy fronts it.
- **Real OAuth 2.1 authorization server** (Ory Fosite under the hood): serves
  RFC 9728 protected-resource metadata, RFC 8414 authorization-server metadata,
  RFC 7591 dynamic client registration, and enforces PKCE (S256) — exactly the
  discovery + DCR + PKCE flow MCP clients expect.
- **Built-in password IdP** (`--password`) lets you prove the entire OAuth dance
  with zero external provider — ideal for a spike — and swaps cleanly to Google
  / GitHub / generic OIDC for production via flags.
- **Plain-HTTP loopback mode** (`--no-auto-tls` + `http://` external URL), so no
  certificates needed locally.
- Vendor-portable (a standalone Go binary), unlike Cloudflare
  `workers-oauth-provider` (ties you to Workers) or a from-scratch
  `oauth2-proxy` wiring (a forward-auth proxy that does not speak the MCP
  metadata/DCR handshake out of the box).

## Run it locally (mock IdP = built-in password)

1. Start the MCP server over streamable HTTP on loopback:

   ```sh
   ZENDESK_MCP_TRANSPORT=streamable-http ZENDESK_MCP_HOST=127.0.0.1 \
     ZENDESK_MCP_PORT=8000 uv run zendesk
   ```

2. Get an `mcp-auth-proxy` binary (build from source or download a release), then
   start the gateway. The password is the built-in IdP login secret — generate a
   throwaway one; it is never committed:

   ```sh
   export GATEWAY_PASSWORD=$(openssl rand -hex 12)
   export MCP_AUTH_PROXY_BIN=/path/to/mcp-auth-proxy   # or put it on PATH
   ./oauth-gateway/run-local-gateway.sh
   ```

   The protected MCP endpoint is now `http://localhost:9090/mcp`.

## Verifying the handshake

`oauth-gateway/verify_oauth_e2e.py` drives the full browser dance headlessly
(dynamic client registration -> authorize -> password login -> consent -> PKCE
token exchange -> authenticated `initialize` + `tools/list`) and asserts that an
unauthenticated request is rejected first.

```sh
GATEWAY_PASSWORD=<the password you exported> \
  uv run python oauth-gateway/verify_oauth_e2e.py
```

Expected: the no-token call fails, the OAuth flow yields a bearer + refresh
token, and the authenticated session lists all upstream tools.

A human can equivalently verify with **MCP Inspector** (`npx
@modelcontextprotocol/inspector`, connect to `http://localhost:9090/mcp`, click
through the browser login) or **`mcp-remote`**.

## Google as the production IdP (console-only, no infra)

Google (gingerlabs Workspace) replaces the password flag. This needs an OAuth
**client credential** created in Google Cloud Console — that is console-only
credentials, not provisioned infrastructure.

1. Google Cloud Console -> APIs & Services -> Credentials -> **Create OAuth
   client ID** -> application type **Web application**.
2. **Authorized redirect URI**: `{EXTERNAL_URL}/.auth/google/callback`
   (e.g. `https://zendesk-mcp.gingerlabs.example/.auth/google/callback`).
3. Configure the OAuth consent screen as **Internal** (restricts to the
   gingerlabs Workspace).
4. Scopes: the defaults `openid profile email` are sufficient (the gateway uses
   the email to authorize).
5. Run the gateway with Google flags instead of `--password`:

   ```sh
   mcp-auth-proxy \
     --external-url https://zendesk-mcp.gingerlabs.example \
     --tls-accept-tos \
     --google-client-id      "$GOOGLE_CLIENT_ID" \
     --google-client-secret  "$GOOGLE_CLIENT_SECRET" \
     --google-allowed-workspaces "gingerlabs.com" \
     http://127.0.0.1:8000/mcp
   ```

   `--google-allowed-workspaces` restricts logins to the gingerlabs Workspace;
   `--google-allowed-users` can pin an explicit allowlist instead. The client
   secret is read from the environment and must never be committed.

## Notes / caveats

- The upstream server runs `stateless=True`, so the gateway needs no sticky
  routing for the spike. If you flip to resumable/SSE sessions, the gateway and
  upstream would need session affinity.
- The gateway stores OAuth state in `--data-path` (embedded BoltDB by default;
  SQL backends available). It also holds signing keys; set `AUTH_HMAC_SECRET` /
  `JWT_PRIVATE_KEY` in production so restarts don't invalidate tokens.
- The shared Zendesk token lives in the upstream server's environment (`.env`
  locally; a secret manager in hosting). The gateway never sees it.
