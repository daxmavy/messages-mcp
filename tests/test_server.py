import asyncio
import json

from mcp import Client
from owner_mcp import audit
from owner_mcp.server import prepare
from messages_mcp.server import SERVICE, build_server


class FakeStore:
    def __init__(self):
        self.calls = []

    def query(self, name, **params):
        self.calls.append((name, params))
        return [{"source": "whatsapp", "conversation": "Bob", "body": "dinner?"}]

    def health(self):
        return {"whatsapp": {"stale": False}}


def _call(server, tool, args):
    async def go():
        async with Client(server) as c:
            return await c.call_tool(tool, args)

    return asyncio.run(go())


def test_server_is_read_only():
    names = {t.name for t in asyncio.run(build_server(store=None).list_tools())}
    assert names == {"message_health", "list_conversations", "recent_messages", "search_messages",
                     "read_conversation", "needs_reply"}
    assert not any(w in n for n in names for w in ("send", "delete", "write", "sql"))


def test_tools_map_to_the_workers_fixed_queries():
    store = FakeStore()
    server = build_server(store)
    _call(server, "recent_messages", {"hours": 6, "source": "whatsapp", "incoming_only": True})
    _call(server, "search_messages", {"text": "dinner"})
    _call(server, "read_conversation", {"conversation_id": "447700900001@s.whatsapp.net", "before": 5})
    _call(server, "needs_reply", {})
    _call(server, "list_conversations", {"source": "signal"})
    assert store.calls == [
        ("recent", {"hours": 6, "source": "whatsapp", "conversation": None, "incoming_only": True, "limit": 200}),
        ("search", {"q": "dinner", "source": None, "limit": 100}),
        ("thread", {"conversation_id": "447700900001@s.whatsapp.net", "source": None, "before": 5, "limit": 100}),
        ("needs-reply", {"days": 14, "source": None}),
        ("conversations", {"source": "signal", "limit": 500}),
    ]


def test_service_identity():
    assert SERVICE.prefix == "MESSAGES_MCP_" and SERVICE.config_dir.name == "messages-mcp"
    assert "cannot send" in SERVICE.grant


def test_tool_calls_are_audited_without_message_text(tmp_path, monkeypatch):
    audit.configure(tmp_path / "audit.log")
    monkeypatch.setattr(SERVICE, "build", lambda: build_server(FakeStore()))
    server = prepare(SERVICE)

    async def go():
        async with Client(server) as c:
            await c.call_tool("search_messages", {"text": "dinner"})

    with audit.caller("local"):
        asyncio.run(go())
    log = (tmp_path / "audit.log").read_text()
    rec = json.loads(log.splitlines()[-1])
    assert rec["tool"] == "search_messages" and rec["ok"] is True and rec["result"] == {"items": 1}
    assert "dinner?" not in log  # the result's text is never logged
