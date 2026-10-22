# messages-mcp

A read-only MCP server over Max's message store: Signal and WhatsApp, as ingested by
[message-ingest](https://github.com/daxmavy/message-ingest). It cannot send anything.

```
agent ──MCP──▶ messages-mcp ──GET /read/<query>, READ_TOKEN──▶ message-ingest Worker ──▶ D1 `messages`
```

The Worker runs a fixed set of read-only queries (`worker/src/read.ts` there); this server
only picks one and its parameters, and adds UK-local times. It never sees SQL, `raw_json`
or attachment bytes. The read token opens only the read routes; it cannot write.

## Tools

`message_health`, `list_conversations`, `recent_messages`, `search_messages`,
`read_conversation`, `needs_reply`. `needs_reply` and `list_conversations` return no message text.

## Where it runs

| Machine | MCP server | Who can call it |
|---|---|---|
| `messages-mcp` VM | HTTP on :8080 (+ public OAuth on :8090 behind a tunnel to `messages-mcp.maxdavy.com`) | VMs granted with `owner-mcp-deploy access`; Claude connectors via OAuth |
| Mac (optional) | stdio, registered with `claude mcp add -s user` | agents on the Mac |

## Setup

```
# put the Worker's READ_TOKEN in ~/.config/messages-mcp/read-token (mode 600), then
deploy/install.sh
```

From the Mac: `uv run owner-mcp-deploy public` (tunnel, DNS, owner passphrase) and
`uv run owner-mcp-deploy access grant <vm>`.

## Settings

`MESSAGES_STORE_URL` (default the message-ingest Worker), `MESSAGES_READ_TOKEN_FILE`
(default `~/.config/messages-mcp/read-token`), plus owner-mcp's `MESSAGES_MCP_*`.

## Audit log and security model

See [owner-mcp](https://github.com/daxmavy/owner-mcp). Every tool call is logged in
`~/.config/messages-mcp/audit.log` with its arguments and the number of rows returned,
never the message text. `messages-mcp revoke-all` drops every OAuth token.

## Tests

`uv run pytest`
