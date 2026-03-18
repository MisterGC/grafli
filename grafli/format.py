"""Parser and serializer for the .grafli format.

Format spec:
  #!grafli v1                                      (file header, first line)
  # comment or title
  @ box <id> "<label>" <x>,<y> <w>x<h> [%color] [^anchor] [~size] [!flat] [&url] [>parent]
  @ arrow <from_id> -> <to_id> "<label>"           (forward)
  @ arrow <from_id> <- <to_id> "<label>"           (backward)
  @ arrow <from_id> <-> <to_id> "<label>"          (bidirectional)
  @ arrow <from_id> -- <to_id> "<label>"           (no heads)
  @ arrow <from_id> -> <to_id> "label" @<dx>,<dy>  (label offset)
  @ arrow <from_id> -> <to_id> "label" !dashed     (arrow styles: dashed/dotted/thick)
  @ note <id> <x>,<y> "<text>" [%color] [~size] [!mono] [&url] [>parent]   (color/style ignored by renderer)
  Any element line may end with  # annotation text
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from grafli.glyphs import ensure_text_presentation

HEADER = "#!grafli v1"


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
    style: str = ""       # "" (node) or "flat"
    url: str = ""
    parent: str = ""
    annotation: str = ""


@dataclass
class Arrow:
    from_id: str
    to_id: str
    label: str = ""
    label_dx: float = 0.0
    label_dy: float = 0.0
    style: str = ""       # "dashed", "dotted", "thick", or "" (solid)
    textsize: str = ""    # "small", "large", "xlarge", "xxlarge", "xxxlarge", or "" (default)
    head_from: bool = False  # arrowhead at from_id end
    head_to: bool = True     # arrowhead at to_id end
    annotation: str = ""


@dataclass
class Note:
    id: str
    x: float
    y: float
    text: str
    color: str = ""
    textsize: str = ""
    style: str = ""       # "" (handwritten) or "mono"
    url: str = ""
    parent: str = ""
    annotation: str = ""


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

    def note_by_id(self, note_id: str) -> Note | None:
        for n in self.notes:
            if n.id == note_id:
                return n
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

    def next_note_id(self) -> str:
        """Return the next available n<N> identifier."""
        max_n = 0
        for n in self.notes:
            if n.id.startswith("n"):
                try:
                    max_n = max(max_n, int(n.id[1:]))
                except ValueError:
                    pass
        return f"n{max_n + 1}"

    def add_box(self, box: Box) -> None:
        self.boxes.append(box)
        self._lines.append(("box", box))

    def add_arrow(self, arrow: Arrow) -> None:
        self.arrows.append(arrow)
        self._lines.append(("arrow", arrow))

    def add_note(self, note: Note) -> None:
        if not note.id:
            note.id = self.next_note_id()
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
    r'(-?[\d.]+),\s*(-?[\d.]+)\s+([\d.]+)x([\d.]+)'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+\^(topleft|topcenter))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge))?'
    r'(?:\s+!(flat))?'
    r'(?:\s+&(\S+))?'
    r'(?:\s+>(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_ARROW = re.compile(
    r'^@\s+arrow\s+(\S+)\s+(<->|->|<-|--)\s+(\S+)'
    r'(?:\s+"([^"]*)")?'
    r'(?:\s+@(-?[\d.]+),(-?[\d.]+))?'
    r'(?:\s+!(dashed|dotted|thick))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_NOTE = re.compile(
    r'^@\s+note\s+(?:([a-zA-Z_]\S*)\s+)?(-?[\d.]+),\s*(-?[\d.]+)\s+"([^"]*)"'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge))?'
    r'(?:\s+!(mono))?'
    r'(?:\s+&(\S+))?'
    r'(?:\s+>(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)


# ── Parser ──────────────────────────────────────────────────────

def parse(text: str) -> Board:
    """Parse a .grafli file string into a Board object."""
    board = Board()
    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            board._lines.append(("blank", None))
            continue

        if stripped == HEADER:
            board._lines.append(("header", stripped))
            continue

        if stripped.startswith("#"):
            board.comments.append(stripped)
            board._lines.append(("comment", stripped))
            continue

        m = _RE_BOX.match(stripped)
        if m:
            box = Box(
                id=m.group(1),
                label=ensure_text_presentation(m.group(2).replace("\\n", "\n")),
                x=float(m.group(3)),
                y=float(m.group(4)),
                w=float(m.group(5)),
                h=float(m.group(6)),
                color=m.group(7) or "",
                anchor=m.group(8) or "",
                textsize=m.group(9) or "",
                style=m.group(10) or "",
                url=m.group(11) or "",
                parent=m.group(12) or "",
                annotation=m.group(13) or "",
            )
            board.boxes.append(box)
            board._lines.append(("box", box))
            continue

        m = _RE_ARROW.match(stripped)
        if m:
            op = m.group(2)
            arrow = Arrow(
                from_id=m.group(1),
                to_id=m.group(3),
                label=m.group(4) or "",
                label_dx=float(m.group(5)) if m.group(5) else 0.0,
                label_dy=float(m.group(6)) if m.group(6) else 0.0,
                style=m.group(7) or "",
                textsize=m.group(8) or "",
                head_from=op in ("<->", "<-"),
                head_to=op in ("<->", "->"),
                annotation=m.group(9) or "",
            )
            board.arrows.append(arrow)
            board._lines.append(("arrow", arrow))
            continue

        m = _RE_NOTE.match(stripped)
        if m:
            note = Note(
                id=m.group(1) or "",
                x=float(m.group(2)),
                y=float(m.group(3)),
                text=ensure_text_presentation(m.group(4).replace("\\n", "\n")),
                color=m.group(5) or "",
                textsize=m.group(6) or "",
                style=m.group(7) or "",
                url=m.group(8) or "",
                parent=m.group(9) or "",
                annotation=m.group(10) or "",
            )
            board.notes.append(note)
            board._lines.append(("note", note))
            continue

        # Unknown line — preserve as comment
        board.comments.append(stripped)
        board._lines.append(("comment", stripped))

    # Backfill IDs for legacy notes that had no ID
    for note in board.notes:
        if not note.id:
            note.id = board.next_note_id()

    return board


def parse_file(path: str) -> Board:
    """Parse a .grafli file from disk."""
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


# ── Serializer ──────────────────────────────────────────────────

def _serialize_box(box: Box) -> str:
    x = int(box.x) if box.x == int(box.x) else box.x
    y = int(box.y) if box.y == int(box.y) else box.y
    w = int(box.w) if box.w == int(box.w) else box.w
    h = int(box.h) if box.h == int(box.h) else box.h
    escaped_label = box.label.replace("\n", "\\n")
    s = f'@ box {box.id} "{escaped_label}" {x},{y} {w}x{h}'
    if box.color:
        s += f" {box.color}"
    if box.anchor:
        s += f" ^{box.anchor}"
    if box.textsize:
        s += f" ~{box.textsize}"
    if box.style:
        s += f" !{box.style}"
    if box.url:
        s += f" &{box.url}"
    if box.parent:
        s += f" >{box.parent}"
    if box.annotation:
        s += f"  # {box.annotation}"
    return s


def _serialize_arrow(arrow: Arrow) -> str:
    if arrow.head_from and arrow.head_to:
        op = "<->"
    elif arrow.head_from:
        op = "<-"
    elif arrow.head_to:
        op = "->"
    else:
        op = "--"
    base = f"@ arrow {arrow.from_id} {op} {arrow.to_id}"
    if arrow.label:
        base += f' "{arrow.label}"'
    if arrow.label_dx or arrow.label_dy:
        dx = int(arrow.label_dx) if arrow.label_dx == int(arrow.label_dx) else arrow.label_dx
        dy = int(arrow.label_dy) if arrow.label_dy == int(arrow.label_dy) else arrow.label_dy
        base += f" @{dx},{dy}"
    if arrow.style:
        base += f" !{arrow.style}"
    if arrow.textsize:
        base += f" ~{arrow.textsize}"
    if arrow.annotation:
        base += f"  # {arrow.annotation}"
    return base


def _serialize_note(note: Note) -> str:
    x = int(note.x) if note.x == int(note.x) else note.x
    y = int(note.y) if note.y == int(note.y) else note.y
    escaped_text = note.text.replace("\n", "\\n")
    s = f'@ note {note.id} {x},{y} "{escaped_text}"'
    if note.color:
        s += f" {note.color}"
    if note.textsize:
        s += f" ~{note.textsize}"
    if note.style:
        s += f" !{note.style}"
    if note.url:
        s += f" &{note.url}"
    if note.parent:
        s += f" >{note.parent}"
    if note.annotation:
        s += f"  # {note.annotation}"
    return s


def serialize(board: Board) -> str:
    """Serialize a Board object back to .grafli format.

    Always emits the #!grafli v1 header as the first line.
    If the board was parsed (has _lines), preserves original ordering.
    Otherwise, outputs comments, then boxes, arrows, notes.
    """
    if board._lines:
        parts = [HEADER]
        for kind, obj in board._lines:
            if kind == "header":
                continue
            elif kind == "blank":
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

    parts = [HEADER]
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
    """Write a Board to a .grafli file on disk."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(serialize(board))
