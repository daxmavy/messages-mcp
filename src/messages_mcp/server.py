"""MCP server over Max's message store (Signal, WhatsApp). Read-only: it cannot send anything.

The store is the message-ingest Worker's fixed read queries; see messages_mcp.store. The
front doors (stdio, exe.dev VM-to-VM, public OAuth), the audit log and the deploy scripts
come from owner-mcp; this module only defines the tools.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer
from owner_mcp.server import Service
from owner_mcp.server import main as serve
from messages_mcp.store import Store

INSTRUCTIONS = """Read-only access to Max's personal messages (Signal, WhatsApp, Slack). Nothing here can send.
- Call message_health first: if a source is `stale`, its ingester is down and recent messages are missing; say so.
- `outgoing = 1` (sender "Max") is Max. needs_reply is the test for "have I replied".
- Times: `*_uk` is UK local time; use it when talking about "today". Raw fields are ms since the epoch.
- Coverage: Signal live since 2026-09-21 plus a sparse backfill to 2023-05; WhatsApp from its pairing date
  plus about a year of history; Slack (bold-lab, multimodalaiworkspace) back to each workspace's retention limit. Slack conversations are named "<workspace> #channel". Absence of a message before that proves nothing.
- `deleted = 1`: the sender deleted it. Do not quote its body.
- These are private conversations with people who have not agreed to anything. Read the least that answers
  the question (needs_reply and list_conversations carry no text), and never copy message text into files,
  repositories, issues, other tools or external services."""

Source = Annotated[Literal["signal", "whatsapp", "slack"] | None, Field(description="only this source; default all")]


def build_server(store: Store | None) -> MCPServer:
    mcp = MCPServer("messages", instructions=INSTRUCTIONS)

    def s() -> Store:
        if store is None:
            raise RuntimeError("message store not configured")
        return store

    @mcp.tool()
    def message_health() -> dict:
        """Per source: last heartbeat, last message, message count, and whether the ingester looks down."""
        return s().health()

    @mcp.tool()
    def list_conversations(source: Source = None,
                           limit: Annotated[int, Field(ge=1, le=1000)] = 500) -> list[dict]:
        """Every chat, most recently active first, with all-time message counts. No message text."""
        return s().query("conversations", source=source, limit=limit)

    @mcp.tool()
    def recent_messages(
        hours: Annotated[float, Field(gt=0, le=24 * 3660, description="window ending now")] = 24,
        source: Source = None,
        conversation: Annotated[str | None, Field(description="part of a chat's name, or its exact id")] = None,
        incoming_only: Annotated[bool, Field(description="leave out what Max sent")] = False,
        limit: Annotated[int, Field(ge=1, le=1000, description="keeps the newest N")] = 200,
    ) -> list[dict]:
        """Messages from the last N hours, oldest first."""
        return s().query("recent", hours=hours, source=source, conversation=conversation,
                         incoming_only=incoming_only, limit=limit)

    @mcp.tool()
    def search_messages(text: Annotated[str, Field(min_length=1, description="substring, case-insensitive for ASCII")],
                        source: Source = None,
                        limit: Annotated[int, Field(ge=1, le=1000, description="keeps the newest N")] = 100) -> list[dict]:
        """Messages whose text contains `text`, oldest first."""
        return s().query("search", q=text, source=source, limit=limit)

    @mcp.tool()
    def read_conversation(
        conversation_id: Annotated[str, Field(description="from list_conversations or a message's conversation_id")],
        source: Source = None,
        before: Annotated[int | None, Field(description="ms since epoch; page back by passing the oldest sent_at")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
    ) -> list[dict]:
        """One chat's messages, the newest `limit` before `before` (default now), oldest first."""
        return s().query("thread", conversation_id=conversation_id, source=source, before=before, limit=limit)

    @mcp.tool()
    def needs_reply(days: Annotated[float, Field(gt=0, le=3660, description="ignore chats quiet for longer")] = 14,
                    source: Source = None) -> list[dict]:
        """Chats whose newest message is not Max's, newest first, with how many are unanswered. No message text."""
        return s().query("needs-reply", days=days, source=source)

    return mcp


def store_from_env() -> Store:
    token_file = Path(os.environ.get("MESSAGES_READ_TOKEN_FILE", "~/.config/messages-mcp/read-token")).expanduser()
    return Store(os.environ.get("MESSAGES_STORE_URL", "https://message-ingest.message-ingest-worker.workers.dev"),
                 token_file.read_text().strip())


SERVICE = Service(
    name="messages",
    title="Approve access to your messages",
    grant="read your Signal, WhatsApp and Slack messages (it cannot send)",
    build=lambda: build_server(store_from_env()),
)


def main() -> None:
    serve(SERVICE)
