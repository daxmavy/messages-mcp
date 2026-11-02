"""Client for the message-ingest Worker's read routes (`GET /read/<query>`).

The Worker runs fixed, read-only queries; this side only picks one and its parameters.
Times arrive as ms since the epoch; every one gets `_utc` and `_uk` siblings, because
Max is in the UK and the agent should not have to convert. A deleted message comes back
without its body, whatever the Worker sends. Only `outgoing = 1` is labelled "Max": a contact
can set their own display name to "Max", so that name is never trusted on its own.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

UK = ZoneInfo("Europe/London")
TIME_FIELDS = ("sent_at", "edited_at", "last_message", "last_heartbeat")
STALE_AFTER_MS = 5 * 60_000

# httpx logs every request URL at INFO, query string included (search terms, conversation ids),
# and the service runs at INFO, so that would land in journald.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class StoreError(RuntimeError):
    """The Worker refused or failed a read."""


def _times(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        out[key] = value
        if key in TIME_FIELDS and isinstance(value, (int, float)):
            moment = datetime.fromtimestamp(value / 1000, timezone.utc)
            out[f"{key}_utc"] = moment.strftime("%Y-%m-%dT%H:%M:%SZ")
            out[f"{key}_uk"] = moment.astimezone(UK).strftime("%Y-%m-%d %H:%M %Z")
    return out


def _mask_deleted(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("deleted"):
        return row
    return row | {"body": None, "deleted": True} | ({"raw_json": None} if "raw_json" in row else {})


def _label_sender(row: dict[str, Any]) -> dict[str, Any]:
    if "outgoing" not in row:
        return row
    if row["outgoing"] == 1:
        return row | {"sender": "Max"}
    out = dict(row)
    if not out.get("sender") and out.get("sender_id"):
        out["sender"] = out["sender_id"]
    for key in ("sender", "sender_name"):
        if isinstance(out.get(key), str) and out[key].strip().casefold() == "max":
            out[key] = f"{out[key].strip()} (a contact, not Max)"
    return out


class Store:
    def __init__(self, url: str, token: str, *, transport: httpx.BaseTransport | None = None,
                 timeout: float = 30.0) -> None:
        self._http = httpx.Client(base_url=url.rstrip("/") + "/read/", transport=transport, timeout=timeout,
                                  headers={"Authorization": f"Bearer {token}"})

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {k: (1 if v is True else v) for k, v in params.items() if v is not None and v is not False}
        try:
            response = self._http.get(path, params=params)
        except httpx.HTTPError as error:
            raise StoreError(f"message store unreachable: {error}") from error
        if not response.is_success:
            raise StoreError(f"message store returned {response.status_code}: {response.text[:200]}")
        return response.json()

    def query(self, name: str, **params: Any) -> list[dict[str, Any]]:
        return [_times(_label_sender(_mask_deleted(row))) for row in self._get(name, params)["rows"]]

    def health(self, now_ms: int | None = None) -> dict[str, dict[str, Any]]:
        now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
        sources = {}
        for source, h in self._get("health", {})["sources"].items():
            beat = h.get("last_heartbeat")
            sources[source] = _times(h) | {
                "minutes_since_heartbeat": None if beat is None else round((now_ms - beat) / 60_000),
                "stale": beat is None or now_ms - beat > STALE_AFTER_MS,
            }
        return sources
