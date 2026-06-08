#!/usr/bin/env bash
#
# Local OAuth-gateway spike runner.
#
# Stands up sigbit/mcp-auth-proxy (a drop-in OAuth 2.1 / OIDC gateway) in front
# of the streamable-HTTP Zendesk MCP server on loopback. The gateway terminates
# the MCP OAuth 2.1 handshake (RFC 9728 protected-resource metadata, RFC 8414
# authorization-server metadata, RFC 7591 dynamic client registration, PKCE) and
# proxies authenticated traffic to the upstream MCP server. The upstream server
# stays auth-agnostic and bound to loopback; only the gateway is reachable by a
# client.
#
#   client --(OAuth 2.1 + Bearer)--> gateway :9090 --(plain MCP)--> server :8000
#
# Auth mode here is PASSWORD (the gateway is its own IdP) so the OAuth mechanics
# can be proven without any external provider. For production, swap the password
# flag for Google flags (see README.md, "Google as the production IdP").
#
# Secrets (the gateway password, and in production the Google client secret) are
# read from the environment at runtime and are never written to disk or git.
#
# Prereqs:
#   - The MCP server running with ZENDESK_MCP_TRANSPORT=streamable-http on
#     127.0.0.1:8000 (see repo README "Streamable HTTP" section).
#   - An mcp-auth-proxy binary. Build from source (go build) or grab a release:
#       https://github.com/sigbit/mcp-auth-proxy/releases
#     Point MCP_AUTH_PROXY_BIN at it, or put `mcp-auth-proxy` on PATH.
#
# Env knobs:
#   MCP_AUTH_PROXY_BIN   path to the proxy binary (default: mcp-auth-proxy on PATH)
#   GATEWAY_PORT         port the gateway listens on (default: 9090)
#   UPSTREAM_MCP_URL     upstream MCP endpoint (default: http://127.0.0.1:8000/mcp)
#   GATEWAY_PASSWORD     login password for the built-in IdP (required in this mode)

set -euo pipefail

BIN="${MCP_AUTH_PROXY_BIN:-mcp-auth-proxy}"
PORT="${GATEWAY_PORT:-9090}"
UPSTREAM="${UPSTREAM_MCP_URL:-http://127.0.0.1:8000/mcp}"

if [[ -z "${GATEWAY_PASSWORD:-}" ]]; then
  echo "ERROR: set GATEWAY_PASSWORD (the built-in-IdP login password)." >&2
  echo "       e.g. GATEWAY_PASSWORD=\$(openssl rand -hex 12) $0" >&2
  exit 1
fi

# --no-auto-tls + an http:// external URL keep this on plain loopback HTTP. The
# gateway is its own authorization server at this external URL, so the value must
# match how clients reach it.
EXTERNAL_URL="http://localhost:${PORT}" \
LISTEN=":${PORT}" \
NO_AUTO_TLS=1 \
PASSWORD="${GATEWAY_PASSWORD}" \
DATA_PATH="$(dirname "$0")/.gateway-data" \
exec "${BIN}" "${UPSTREAM}"
