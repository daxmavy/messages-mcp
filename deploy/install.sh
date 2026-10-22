#!/usr/bin/env bash
# Install messages-mcp on this machine. Idempotent; re-run after pulling changes.
#
#   Needs ~/.config/messages-mcp/read-token (mode 600): the message-ingest Worker's READ_TOKEN.
#   macOS: registers the server with Claude Code (user scope) over stdio.
#   Linux: (the messages-mcp VM) owner-mcp writes the units: peer HTTP on 8080, and with a
#          tunnel the public OAuth server and cloudflared.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/messages-mcp"

mkdir -p "$CONF" && chmod 700 "$CONF"
[ -s "$CONF/read-token" ] || { echo "missing $CONF/read-token (the Worker's READ_TOKEN)" >&2; exit 1; }
chmod 600 "$CONF/read-token"

uv sync --quiet --project "$ROOT" --no-dev

case "$(uname)" in
Darwin)
  claude mcp remove -s user messages >/dev/null 2>&1 || true
  claude mcp add -s user messages -- "$ROOT/.venv/bin/messages-mcp"
  ;;
Linux)
  (cd "$ROOT" && .venv/bin/owner-mcp-deploy units)
  ;;
*) echo "unsupported OS: $(uname)" >&2; exit 1 ;;
esac
echo "Installed."
