"""One gate for every outbound request: offline mode and a transparent log of what left the machine.

Every function that talks to the internet calls :func:`network` first. In offline mode
(``PORTFOLIO_OFFLINE=1``) the call raises :class:`OfflineError` and the caller falls back to its
local cache; otherwise the request is recorded, so the dashboard can show exactly which hosts were
contacted and which identifiers (tickers, ISINs, search terms) were sent – never amounts, share
counts, names or account data, because those are not available at the call sites in the first place.
"""

from __future__ import annotations

import os
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime


class OfflineError(RuntimeError):
    """Raised instead of a network request while offline mode is on."""


@dataclass
class Request:
    host: str
    purpose: str
    sent: tuple[str, ...] = ()       # identifiers in the request: tickers, ISINs, a search term
    at: datetime = field(default_factory=datetime.now)


_LOG: list[Request] = []
_LOCK = threading.Lock()


def offline() -> bool:
    return os.environ.get("PORTFOLIO_OFFLINE") == "1"


def network(host: str, purpose: str, *sent: str) -> None:
    """Gate an outbound request: raise in offline mode, otherwise record it with the identifiers it carries."""
    if offline():
        raise OfflineError(f"offline mode: {purpose} ({host}) skipped")
    with _LOCK:
        _LOG.append(Request(host, purpose, tuple(str(x) for x in sent)))


def requests_log() -> list[Request]:
    with _LOCK:
        return list(_LOG)


def summary() -> list[dict]:
    """Requests since start, grouped by host and purpose, with the identifiers that were sent."""
    groups: dict[tuple[str, str], list[Request]] = {}
    for r in requests_log():
        groups.setdefault((r.host, r.purpose), []).append(r)
    out = []
    for (host, purpose), reqs in groups.items():
        sent = [x for x, _ in Counter(x for r in reqs for x in r.sent).most_common()]
        out.append({"host": host, "purpose": purpose, "requests": len(reqs), "sent": sent})
    return sorted(out, key=lambda g: -g["requests"])


YAHOO = "Yahoo Finance"
