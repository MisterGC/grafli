"""Presence in a live tab: who is on a board, their pointers, the laser and
the presenter's view.

All of it travels over the WebSocket only; nothing here reads or writes the
board file, and a presence message never makes a frame. A tab sends:

* ``{"t": "cursor", "x", "y"}`` where its pointer is on the board (board
  units), ``{"t": "cursor", "off": true}`` when it leaves the board;
* ``{"t": "laser", "x", "y"}`` for each point of the laser while it is on,
  ``{"t": "laser", "off": true}`` when it goes off;
* ``{"t": "view", "x", "y", "w", "h"}`` — the camera; only the presenter's
  is passed on;
* ``{"t": "follow", "on"}`` whether it follows the presenter;
* ``{"t": "name", "name"}`` the name the others see;
* ``{"t": "select", "id"}`` what the presenter selected (``None`` for
  nothing); kept for the agent to read, never passed on.

The server passes cursors and the laser on to the board's other tabs with
the sender's public ``id`` (never its author token), sends every tab a
``peers`` list when someone comes, goes, renames or (un)follows, and keeps
the presenter's last view for a tab that comes later. No Qt.
"""

from __future__ import annotations

import math
import secrets
import time
import unicodedata

# The presenter's colour; guests take the first free one of the others.
# Purple is the agent's (``grafli.serve.agent.AGENT_COLOR``).
PRESENTER_COLOR = "#e8590c"
GUEST_COLORS = ("#0c8599", "#1971c2", "#2f9e44", "#c2255c", "#66a80f",
                "#495057")

MAX_NAME_CHARS = 32
# Board coordinates beyond this are not on any board.
MAX_COORD = 1e7

# Presence messages a tab may send: a steady rate with a burst on top. A
# pointer sends about 30 a second; what comes faster is dropped.
RATE_PER_S = 60.0
BURST = 120.0

KINDS = ("cursor", "laser", "view", "follow", "name", "select")


def new_id() -> str:
    """A tab's public id in presence messages."""
    return secrets.token_urlsafe(6)


def clean_name(value) -> str:
    """*value* as a name others can see: one line of printable text, at most
    ``MAX_NAME_CHARS`` long; "" when nothing of it is left."""
    if not isinstance(value, str):
        return ""
    kept = "".join(ch if unicodedata.category(ch)[0] not in "CZ" else " "
                   for ch in value)
    return " ".join(kept.split())[:MAX_NAME_CHARS].strip()


def _coord(msg: dict, name: str, low: float = -MAX_COORD) -> float | None:
    value = msg.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value) or not low <= value <= MAX_COORD:
        return None
    return value


def point(msg: dict) -> dict | None:
    """The ``{"x", "y"}`` or ``{"off": True}`` a cursor or laser message
    carries, or None when it carries neither."""
    if msg.get("off") is True:
        return {"off": True}
    x, y = _coord(msg, "x"), _coord(msg, "y")
    if x is None or y is None:
        return None
    return {"x": round(x, 2), "y": round(y, 2)}


def view(msg: dict) -> dict | None:
    """The camera ``{"x", "y", "w", "h"}`` a view message carries, or None."""
    out = {k: _coord(msg, k) for k in ("x", "y")}
    out.update({k: _coord(msg, k, low=0) for k in ("w", "h")})
    if any(v is None for v in out.values()) or not out["w"] or not out["h"]:
        return None
    return {k: round(v, 2) for k, v in out.items()}


class Bucket:
    """How many presence messages a tab may still send now."""

    def __init__(self, rate: float = RATE_PER_S, burst: float = BURST,
                 clock=time.monotonic):
        self.rate, self.burst, self.clock = rate, burst, clock
        self.tokens = burst
        self.at = clock()

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True
