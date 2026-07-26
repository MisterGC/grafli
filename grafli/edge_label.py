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

from grafli import theme


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

def edge_kind_color(kind: str, fallback: QColor | None = None) -> QColor:
    """Colour for an edge kind under the active theme.

    The hues carry meaning across a theme switch (``risk`` stays red), so the
    palette re-tunes their lightness rather than remapping them.
    """
    color = theme.EDGE_KIND_COLORS.get(kind)
    if color is not None:
        return color
    return fallback if fallback is not None else theme.ARROW_COLOR

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
