"""Helpers for semantic arrow-label prefixes.

Arrow labels can stay human-editable text while carrying a lightweight
relationship kind:

    data: user_id
    call: validate(input)
    step: 1

Only known prefixes are interpreted, so ordinary labels with colons keep
rendering as plain text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtGui import QColor


EDGE_KINDS = (
    "call",
    "data",
    "event",
    "state",
    "step",
    "verify",
    "owns",
    "depends",
    "risk",
    "note",
)

EDGE_KIND_COLORS: dict[str, QColor] = {
    "call": QColor("#2F5D5C"),
    "data": QColor("#2B6CB0"),
    "event": QColor("#C05621"),
    "state": QColor("#805AD5"),
    "step": QColor("#805AD5"),
    "verify": QColor("#2F855A"),
    "owns": QColor("#2C7A7B"),
    "depends": QColor("#6A9FB5"),
    "risk": QColor("#C53030"),
    "note": QColor("#8A8580"),
}

_RE_EDGE_LABEL = re.compile(
    r"^(?P<kind>" + "|".join(EDGE_KINDS) + r"):\s*(?P<body>.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedEdgeLabel:
    kind: str
    body: str


def parse_edge_label(label: str) -> ParsedEdgeLabel:
    """Split a semantic arrow label into ``kind`` and ``body``.

    Unknown ``word:`` prefixes are intentionally left as plain label text.
    """
    m = _RE_EDGE_LABEL.match(label.strip())
    if not m:
        return ParsedEdgeLabel("", label)
    return ParsedEdgeLabel(m.group("kind").lower(), m.group("body"))
