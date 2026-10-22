"""Client for the message-ingest Worker's read routes (`GET /read/<query>`).

The Worker runs fixed, read-only queries; this side only picks one and its parameters.
Times arrive as ms since the epoch; every one gets `_utc` and `_uk` siblings, because
Max is in the UK and the agent should not have to convert.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx

UK = ZoneInfo("Europe/London")
TIME_FIELDS = ("sent_at", "edited_at", "last_message", "last_heartbeat")
STALE_AFTER_MS = 5 * 60_000


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
        return [_times(row) for row in self._get(name, params)["rows"]]

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
