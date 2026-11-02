import logging

import httpx
import pytest

from messages_mcp.store import Store, StoreError


def _store(handler):
    return Store("https://ingest.test/", "read-tok", transport=httpx.MockTransport(handler))


def test_sends_the_read_token_and_drops_unset_params():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"rows": [{"sent_at": 1_760_000_000_000, "body": "hi"}]})

    rows = _store(handler).query("recent", hours=24, source=None, incoming_only=True)
    assert seen["auth"] == "Bearer read-tok"
    assert seen["url"] == "https://ingest.test/read/recent?hours=24&incoming_only=1"
    assert rows == [{"sent_at": 1_760_000_000_000, "sent_at_utc": "2025-10-09T08:53:20Z",
                     "sent_at_uk": "2025-10-09 09:53 BST", "body": "hi"}]


def test_adds_utc_and_uk_times_next_to_every_ms_field():
    def handler(request):
        return httpx.Response(200, json={"rows": [{"last_message": 1_760_000_000_000, "edited_at": None}]})

    [row] = _store(handler).query("needs-reply")
    assert row["last_message_utc"] == "2025-10-09T08:53:20Z"
    assert row["last_message_uk"] == "2025-10-09 09:53 BST"
    assert "edited_at_utc" not in row


def test_health_returns_sources_with_freshness():
    def handler(request):
        assert request.url.path == "/read/health"
        return httpx.Response(200, json={"sources": {"signal": {"last_heartbeat": 1_760_000_000_000, "last_message": None, "messages": 3}}})

    health = _store(handler).health(now_ms=1_760_000_000_000 + 10 * 60_000)
    assert health["signal"]["minutes_since_heartbeat"] == 10
    assert health["signal"]["stale"] is True
    assert health["signal"]["last_heartbeat_utc"] == "2025-10-09T08:53:20Z"


@pytest.mark.parametrize("status", [400, 401, 500])
def test_worker_errors_become_store_errors_without_the_token(status):
    def handler(request):
        return httpx.Response(status, json={"error": "nope"})

    with pytest.raises(StoreError) as e:
        _store(handler).query("recent")
    assert str(status) in str(e.value) and "read-tok" not in str(e.value)


def test_deleted_messages_never_carry_their_body():
    def handler(request):
        return httpx.Response(200, json={"rows": [
            {"body": "gone", "raw_json": "{}", "deleted": 1},
            {"body": "kept", "deleted": 0},
        ]})

    gone, kept = _store(handler).query("recent")
    assert gone["body"] is None and gone["raw_json"] is None and gone["deleted"] is True
    assert kept["body"] == "kept" and kept["deleted"] == 0


def test_only_outgoing_messages_are_labelled_max():
    def handler(request):
        return httpx.Response(200, json={"rows": [
            {"sender": "Bob", "outgoing": 1},  # old Worker: a stored name on Max's own message
            {"sender": "Max", "outgoing": 0},  # a contact who calls themselves Max
            {"sender": " max ", "sender_name": "max", "sender_id": "u1", "outgoing": 0},
            {"sender": None, "sender_id": "u2", "outgoing": 0},  # new Worker: no name, stable id
            {"conversation": "Bob", "messages": 3},  # not a message row
        ]})

    mine, impostor, impostor2, unnamed, conv = _store(handler).query("recent")
    assert mine["sender"] == "Max"
    assert impostor["sender"] == "Max (a contact, not Max)"
    assert impostor2["sender"] == "max (a contact, not Max)" and impostor2["sender_name"] == "max (a contact, not Max)"
    assert impostor2["sender_id"] == "u1"
    assert unnamed["sender"] == "u2"
    assert conv == {"conversation": "Bob", "messages": 3}


def test_request_urls_with_search_terms_are_not_logged(caplog):
    caplog.set_level(logging.INFO)  # what owner-mcp's basicConfig sets for the service

    def handler(request):
        return httpx.Response(200, json={"rows": []})

    _store(handler).query("search", q="secret-term")
    assert "secret-term" not in caplog.text
