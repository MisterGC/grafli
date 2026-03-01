"""Parser and serializer for the .board whiteboard format.

Format spec:
  # comment or title
  @ box <id> "<label>" <x>,<y> <w>x<h>
  @ arrow <from_id> -> <to_id> "<label>"   (label optional)
  @ note <x>,<y> "<text>"
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Box:
    id: str
    label: str
    x: float
    y: float
    w: float
    h: float
    color: str = ""
    anchor: str = ""      # "topleft", "topcenter", or "" (= center)
    textsize: str = ""    # "small", "large", or "" (= medium)
    parent: str = ""


@dataclass
class Arrow:
    from_id: str
    to_id: str
    label: str = ""


@dataclass
class Note:
    x: float
    y: float
    text: str
    color: str = ""
    textsize: str = ""


@dataclass
class Board:
    comments: list[str] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    arrows: list[Arrow] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    _lines: list[tuple[str, object | None]] = field(
        default_factory=list, repr=False
    )
    """Ordered list of (kind, element) preserving original line order.
    kind is one of: 'comment', 'blank', 'box', 'arrow', 'note'."""

    def box_by_id(self, box_id: str) -> Box | None:
        for b in self.boxes:
            if b.id == box_id:
                return b
        return None

    def next_box_id(self) -> str:
        """Return the next available box<N> identifier."""
        max_n = 0
        for b in self.boxes:
            if b.id.startswith("box"):
                try:
                    max_n = max(max_n, int(b.id[3:]))
                except ValueError:
                    pass
        return f"box{max_n + 1}"

    def add_box(self, box: Box) -> None:
        self.boxes.append(box)
        self._lines.append(("box", box))

    def add_arrow(self, arrow: Arrow) -> None:
        self.arrows.append(arrow)
        self._lines.append(("arrow", arrow))

    def add_note(self, note: Note) -> None:
        self.notes.append(note)
        self._lines.append(("note", note))

    def remove_box(self, box: Box) -> None:
        self.boxes.remove(box)
        self._lines = [(k, v) for k, v in self._lines if v is not box]

    def remove_arrow(self, arrow: Arrow) -> None:
        self.arrows.remove(arrow)
        self._lines = [(k, v) for k, v in self._lines if v is not arrow]

    def remove_note(self, note: Note) -> None:
        self.notes.remove(note)
        self._lines = [(k, v) for k, v in self._lines if v is not note]


# ── Regex patterns ──────────────────────────────────────────────

_RE_BOX = re.compile(
    r'^@\s+box\s+(\S+)\s+"([^"]*)"\s+'
    r'(-?[\d.]+),(-?[\d.]+)\s+([\d.]+)x([\d.]+)'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+\^(topleft|topcenter))?'
    r'(?:\s+~(small|large|xlarge|xxlarge))?'
    r'(?:\s+>(\S+))?\s*$'
)

_RE_ARROW_LABEL = re.compile(
    r'^@\s+arrow\s+(\S+)\s+->\s+(\S+)\s+"([^"]*)"\s*$'
)

_RE_ARROW_BARE = re.compile(
    r'^@\s+arrow\s+(\S+)\s+->\s+(\S+)\s*$'
)

_RE_NOTE = re.compile(
    r'^@\s+note\s+(-?[\d.]+),(-?[\d.]+)\s+"([^"]*)"'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+~(small|large|xlarge|xxlarge))?\s*$'
)


# ── Parser ──────────────────────────────────────────────────────

def parse(text: str) -> Board:
    """Parse a .board file string into a Board object."""
    board = Board()
    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            board._lines.append(("blank", None))
            continue

        if stripped.startswith("#"):
            board.comments.append(stripped)
            board._lines.append(("comment", stripped))
            continue

        m = _RE_BOX.match(stripped)
        if m:
            box = Box(
                id=m.group(1),
                label=m.group(2),
                x=float(m.group(3)),
                y=float(m.group(4)),
                w=float(m.group(5)),
                h=float(m.group(6)),
                color=m.group(7) or "",
                anchor=m.group(8) or "",
                textsize=m.group(9) or "",
                parent=m.group(10) or "",
            )
            board.boxes.append(box)
            board._lines.append(("box", box))
            continue

        m = _RE_ARROW_LABEL.match(stripped)
        if m:
            arrow = Arrow(
                from_id=m.group(1),
                to_id=m.group(2),
                label=m.group(3),
            )
            board.arrows.append(arrow)
            board._lines.append(("arrow", arrow))
            continue

        m = _RE_ARROW_BARE.match(stripped)
        if m:
            arrow = Arrow(from_id=m.group(1), to_id=m.group(2))
            board.arrows.append(arrow)
            board._lines.append(("arrow", arrow))
            continue

        m = _RE_NOTE.match(stripped)
        if m:
            note = Note(
                x=float(m.group(1)),
                y=float(m.group(2)),
                text=m.group(3),
                color=m.group(4) or "",
                textsize=m.group(5) or "",
            )
            board.notes.append(note)
            board._lines.append(("note", note))
            continue

        # Unknown line — preserve as comment
        board.comments.append(stripped)
        board._lines.append(("comment", stripped))

    return board


def parse_file(path: str) -> Board:
    """Parse a .board file from disk."""
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


# ── Serializer ──────────────────────────────────────────────────

def _serialize_box(box: Box) -> str:
    x = int(box.x) if box.x == int(box.x) else box.x
    y = int(box.y) if box.y == int(box.y) else box.y
    w = int(box.w) if box.w == int(box.w) else box.w
    h = int(box.h) if box.h == int(box.h) else box.h
    s = f'@ box {box.id} "{box.label}" {x},{y} {w}x{h}'
    if box.color:
        s += f" {box.color}"
    if box.anchor:
        s += f" ^{box.anchor}"
    if box.textsize:
        s += f" ~{box.textsize}"
    if box.parent:
        s += f" >{box.parent}"
    return s


def _serialize_arrow(arrow: Arrow) -> str:
    base = f"@ arrow {arrow.from_id} -> {arrow.to_id}"
    if arrow.label:
        return f'{base} "{arrow.label}"'
    return base


def _serialize_note(note: Note) -> str:
    x = int(note.x) if note.x == int(note.x) else note.x
    y = int(note.y) if note.y == int(note.y) else note.y
    s = f'@ note {x},{y} "{note.text}"'
    if note.color:
        s += f" {note.color}"
    if note.textsize:
        s += f" ~{note.textsize}"
    return s


def serialize(board: Board) -> str:
    """Serialize a Board object back to .board format.

    If the board was parsed (has _lines), preserves original ordering.
    Otherwise, outputs comments, then boxes, arrows, notes.
    """
    if board._lines:
        parts = []
        for kind, obj in board._lines:
            if kind == "blank":
                parts.append("")
            elif kind == "comment":
                parts.append(obj)
            elif kind == "box":
                parts.append(_serialize_box(obj))
            elif kind == "arrow":
                parts.append(_serialize_arrow(obj))
            elif kind == "note":
                parts.append(_serialize_note(obj))
        return "\n".join(parts) + "\n"

    parts = []
    for c in board.comments:
        parts.append(c)
    if board.comments and (board.boxes or board.arrows or board.notes):
        parts.append("")
    for box in board.boxes:
        parts.append(_serialize_box(box))
    for arrow in board.arrows:
        parts.append(_serialize_arrow(arrow))
    for note in board.notes:
        parts.append(_serialize_note(note))
    return "\n".join(parts) + "\n"


def serialize_to_file(board: Board, path: str) -> None:
    """Write a Board to a .board file on disk."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(serialize(board))
