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
  @ arrow <from_id> -> <to_id> "label" [&url]      (resource reference)
  @ note <id> <x>,<y> "<text>" [%color] [~size] [!mono] [&url] [>parent]
  @ note <id> <x>,<y> <triple-quoted text block> [%color] [~size] [!mono] [&url] [>parent]
  @ image <id> "<relative_path>" <x>,<y> <w>x<h> [>parent] [&url]
  @ bookmark <id> "<label>" @<focus_id>[,<focus_id>...] [~pad=<n>] ["<description>"]
  @ flow <id> "<label>" <bookmark_ref>[:<dwell>] ... ["<description>"]
  @ footer "<markdown>"                            (board-global PDF footer)
  @ title-bg <style>                               (title-slide background: thumbnail-art)

Bookmarks/flows (v2) save a guided tour through the graph. A bookmark stores
a semantic anchor (the item ids to frame), not raw pan/zoom, so it survives
layout edits. A flow is an ordered list of bookmark refs with optional
auto-play dwell times. ``footer`` is a single board-global markdown branding
line rendered at the bottom of every exported PDF slide. The v2 header is
emitted only when such directives are present; pure-diagram files stay on v1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from grafli.glyphs import ensure_text_presentation

HEADER = "#!grafli v1"
HEADER_V2 = "#!grafli v2"
DEFAULT_BOOKMARK_PAD = 60   # scene px of breathing room around the anchor


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
    textsize: str = ""    # px number (e.g. "16"), legacy name, or "" (= default)
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
    textsize: str = ""    # px number (e.g. "16"), legacy name, or "" (= default)
    head_from: bool = False  # arrowhead at from_id end
    head_to: bool = True     # arrowhead at to_id end
    url: str = ""
    annotation: str = ""     # deprecated — kept for migration parsing


DEFAULT_NOTE_WRAP_CHARS = 80


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
    block_text: bool = False
    wrap_chars: int = DEFAULT_NOTE_WRAP_CHARS  # soft-wrap width in characters
    # True iff the author chose a width (via ~width=N or by dragging the
    # resize handle). When False, the wrap_chars value is the implicit
    # default and the box collapses to content-fit; when True, the box
    # always reserves the chosen budget.
    wrap_chars_explicit: bool = False


@dataclass
class Image:
    id: str
    image_path: str   # relative path to image file
    x: float
    y: float
    w: float
    h: float
    parent: str = ""
    url: str = ""
    annotation: str = ""     # deprecated — kept for migration parsing


@dataclass
class Bookmark:
    """A named, self-describing viewpoint of the graph.

    The viewport is stored *semantically*: ``focus`` lists the item ids the
    view should frame, and the actual pan/zoom is computed at display time by
    fitting their combined bounds. This stays correct when the layout changes
    and is the form an agent can author directly (it knows ids, not matrices).
    """
    id: str
    label: str
    focus: list[str] = field(default_factory=list)  # item ids to frame
    pad: int = 0                                     # 0 = use default padding
    description: str = ""
    # Exact scene rect (x, y, w, h) to frame when ``focus`` resolves to
    # nothing — set for viewport bookmarks and the empty-space fallback so
    # a hand-tuned or node-less view is still reproducible.
    view: tuple[float, float, float, float] | None = None
    # When True the focus items are an explicit, narrowed selection: thumbnails
    # and the exported PDF render only those items (and the arrows between
    # them), not everything inside the framed region.
    isolate: bool = False


@dataclass
class FlowStep:
    ref: str                  # bookmark id
    dwell: float | None = None  # auto-play seconds on this stop (None = default)


@dataclass
class Flow:
    """An ordered narrative path through a set of bookmarks."""
    id: str
    label: str
    steps: list[FlowStep] = field(default_factory=list)
    description: str = ""


@dataclass
class Board:
    comments: list[str] = field(default_factory=list)
    boxes: list[Box] = field(default_factory=list)
    arrows: list[Arrow] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    bookmarks: list[Bookmark] = field(default_factory=list)
    flows: list[Flow] = field(default_factory=list)
    footer: str = ""   # board-global markdown branding footer for PDF exports
    title_bg: str = ""   # title-slide background: "" (none) or "thumbnail-art"
    _lines: list[tuple[str, object | None]] = field(
        default_factory=list, repr=False
    )
    """Ordered list of (kind, element) preserving original line order.
    kind is one of: 'comment', 'blank', 'box', 'arrow', 'note', 'image',
    'bookmark', 'flow'."""

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

    def image_by_id(self, image_id: str) -> Image | None:
        for img in self.images:
            if img.id == image_id:
                return img
        return None

    def next_image_id(self) -> str:
        max_n = 0
        for img in self.images:
            if img.id.startswith("img"):
                try:
                    max_n = max(max_n, int(img.id[3:]))
                except ValueError:
                    pass
        return f"img{max_n + 1}"

    def add_image(self, image: Image) -> None:
        if not image.id:
            image.id = self.next_image_id()
        self.images.append(image)
        self._lines.append(("image", image))

    def remove_image(self, image: Image) -> None:
        self.images.remove(image)
        self._lines = [(k, v) for k, v in self._lines if v is not image]

    def bookmark_by_id(self, bookmark_id: str) -> Bookmark | None:
        for bm in self.bookmarks:
            if bm.id == bookmark_id:
                return bm
        return None

    def flow_by_id(self, flow_id: str) -> Flow | None:
        for fl in self.flows:
            if fl.id == flow_id:
                return fl
        return None

    def next_bookmark_id(self) -> str:
        max_n = 0
        for bm in self.bookmarks:
            if bm.id.startswith("bm"):
                try:
                    max_n = max(max_n, int(bm.id[2:]))
                except ValueError:
                    pass
        return f"bm{max_n + 1}"

    def next_flow_id(self) -> str:
        max_n = 0
        for fl in self.flows:
            if fl.id.startswith("flow"):
                try:
                    max_n = max(max_n, int(fl.id[4:]))
                except ValueError:
                    pass
        return f"flow{max_n + 1}"

    def add_bookmark(self, bookmark: Bookmark) -> None:
        if not bookmark.id:
            bookmark.id = self.next_bookmark_id()
        self.bookmarks.append(bookmark)
        self._lines.append(("bookmark", bookmark))

    def add_flow(self, flow: Flow) -> None:
        if not flow.id:
            flow.id = self.next_flow_id()
        self.flows.append(flow)
        self._lines.append(("flow", flow))

    def remove_bookmark(self, bookmark: Bookmark) -> None:
        self.bookmarks.remove(bookmark)
        self._lines = [(k, v) for k, v in self._lines if v is not bookmark]

    def remove_flow(self, flow: Flow) -> None:
        self.flows.remove(flow)
        self._lines = [(k, v) for k, v in self._lines if v is not flow]


# ── Regex patterns ──────────────────────────────────────────────

_RE_BOX = re.compile(
    r'^@\s+box\s+(\S+)\s+"([^"]*)"\s+'
    r'(-?[\d.]+),\s*(-?[\d.]+)\s+([\d.]+)x([\d.]+)'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+\^(topleft|topcenter))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge|\d+))?'
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
    r'(?:\s+&(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_NOTE = re.compile(
    r'^@\s+note\s+(?:([a-zA-Z_]\S*)\s+)?(-?[\d.]+),\s*(-?[\d.]+)\s+"([^"]*)"'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge|\d+))?'
    r'(?:\s+~width=(\d+))?'
    r'(?:\s+!(mono))?'
    r'(?:\s+&(\S+))?'
    r'(?:\s+>(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_NOTE_BLOCK_START = re.compile(
    r'^@\s+note\s+(?:([a-zA-Z_]\S*)\s+)?(-?[\d.]+),\s*(-?[\d.]+)\s+"""'
    r'\s*$'
)

_RE_NOTE_BLOCK_SUFFIX = re.compile(
    r'^\s*"""'
    r'(?:\s+(#[0-9A-Fa-f]{6}|%[a-z]+))?'
    r'(?:\s+~(small|large|xlarge|xxlarge|xxxlarge|\d+))?'
    r'(?:\s+~width=(\d+))?'
    r'(?:\s+!(mono))?'
    r'(?:\s+&(\S+))?'
    r'(?:\s+>(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_IMAGE = re.compile(
    r'^@\s+image\s+(\S+)\s+"([^"]*)"\s+'
    r'(-?[\d.]+),\s*(-?[\d.]+)\s+([\d.]+)x([\d.]+)'
    r'(?:\s+>(\S+))?'
    r'(?:\s+&(\S+))?'
    r'(?:\s+#\s*(.+?))?'
    r'\s*$'
)

_RE_BOOKMARK = re.compile(
    r'^@\s+bookmark\s+(\S+)\s+"([^"]*)"'
    r'(?:\s+@(\S+))?'                  # focus: comma-separated item ids
    r'(?:\s+~pad=(\d+))?'
    r'(?:\s+~view=(-?\d+),(-?\d+),(\d+),(\d+))?'   # exact scene rect fallback
    r'(\s+~iso)?'                      # focus items are a narrowed selection
    r'(?:\s+"([^"]*)")?'               # optional description
    r'\s*$'
)

_RE_FLOW = re.compile(
    r'^@\s+flow\s+(\S+)\s+"([^"]*)"\s*(.*)$'
)

_RE_FOOTER = re.compile(
    r'^@\s+footer\s+"([^"]*)"\s*$'      # board-global markdown branding footer
)

_RE_TITLE_BG = re.compile(
    r'^@\s+title-bg\s+(\S+)\s*$'        # title-slide background style
)


# ── Parser ──────────────────────────────────────────────────────

def _parse_flow_rest(rest: str) -> tuple[list[FlowStep], str]:
    """Split a flow line's tail into (steps, description).

    The tail is bare bookmark refs (``ref`` or ``ref:dwell``) optionally
    followed by a quoted description. Bookmark ids never contain quotes, so
    the first ``"`` unambiguously starts the description.
    """
    rest = rest.strip()
    description = ""
    if '"' in rest:
        head, _, tail = rest.partition('"')
        rest = head.strip()
        description = tail.split('"', 1)[0]
    steps: list[FlowStep] = []
    for token in rest.split():
        ref, sep, dwell = token.partition(":")
        if not ref:
            continue
        parsed_dwell: float | None = None
        if sep and dwell:
            try:
                parsed_dwell = float(dwell.rstrip("s"))
            except ValueError:
                parsed_dwell = None
        steps.append(FlowStep(ref=ref, dwell=parsed_dwell))
    return steps, description


def parse(text: str) -> Board:
    """Parse a .grafli file string into a Board object."""
    board = Board()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()

        if not stripped:
            board._lines.append(("blank", None))
            continue

        if stripped in (HEADER, HEADER_V2):
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
                annotation=(m.group(13) or "").replace("\\n", "\n"),
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
                url=m.group(9) or "",
                annotation=(m.group(10) or "").replace("\\n", "\n"),
            )
            board.arrows.append(arrow)
            board._lines.append(("arrow", arrow))
            continue

        m = _RE_NOTE_BLOCK_START.match(stripped)
        if m:
            note_id = m.group(1) or ""
            x = float(m.group(2))
            y = float(m.group(3))
            body_lines: list[str] = []
            suffix = ""
            while i < len(lines):
                body_line = lines[i]
                i += 1
                if body_line.strip().startswith('"""'):
                    suffix = body_line
                    break
                body_lines.append(body_line)

            sm = _RE_NOTE_BLOCK_SUFFIX.match(suffix.strip())
            if sm:
                note = Note(
                    id=note_id,
                    x=x,
                    y=y,
                    text=ensure_text_presentation("\n".join(body_lines)),
                    color=sm.group(1) or "",
                    textsize=sm.group(2) or "",
                    wrap_chars=int(sm.group(3)) if sm.group(3)
                                                else DEFAULT_NOTE_WRAP_CHARS,
                    wrap_chars_explicit=bool(sm.group(3)),
                    style=sm.group(4) or "",
                    url=sm.group(5) or "",
                    parent=sm.group(6) or "",
                    annotation=(sm.group(7) or "").replace("\\n", "\n"),
                    block_text=True,
                )
                board.notes.append(note)
                board._lines.append(("note", note))
                continue

            # Malformed block — preserve its contents as comments.
            board.comments.append(stripped)
            board._lines.append(("comment", stripped))
            for body_line in body_lines:
                board.comments.append(body_line)
                board._lines.append(("comment", body_line))
            if suffix:
                board.comments.append(suffix)
                board._lines.append(("comment", suffix))
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
                wrap_chars=int(m.group(7)) if m.group(7)
                                            else DEFAULT_NOTE_WRAP_CHARS,
                wrap_chars_explicit=bool(m.group(7)),
                style=m.group(8) or "",
                url=m.group(9) or "",
                parent=m.group(10) or "",
                annotation=(m.group(11) or "").replace("\\n", "\n"),
            )
            board.notes.append(note)
            board._lines.append(("note", note))
            continue

        m = _RE_BOOKMARK.match(stripped)
        if m:
            focus = [fid for fid in (m.group(3) or "").split(",") if fid]
            view = None
            if m.group(5) is not None:
                view = (
                    float(m.group(5)), float(m.group(6)),
                    float(m.group(7)), float(m.group(8)),
                )
            bookmark = Bookmark(
                id=m.group(1),
                label=ensure_text_presentation(m.group(2).replace("\\n", "\n")),
                focus=focus,
                pad=int(m.group(4)) if m.group(4) else 0,
                description=ensure_text_presentation(
                    (m.group(10) or "").replace("\\n", "\n")
                ),
                view=view,
                isolate=m.group(9) is not None,
            )
            board.bookmarks.append(bookmark)
            board._lines.append(("bookmark", bookmark))
            continue

        m = _RE_FOOTER.match(stripped)
        if m:
            board.footer = ensure_text_presentation(
                m.group(1).replace("\\n", "\n")
            )
            continue

        m = _RE_TITLE_BG.match(stripped)
        if m:
            board.title_bg = m.group(1)
            continue

        m = _RE_FLOW.match(stripped)
        if m:
            steps, description = _parse_flow_rest(m.group(3))
            flow = Flow(
                id=m.group(1),
                label=ensure_text_presentation(m.group(2).replace("\\n", "\n")),
                steps=steps,
                description=ensure_text_presentation(
                    description.replace("\\n", "\n")
                ),
            )
            board.flows.append(flow)
            board._lines.append(("flow", flow))
            continue

        m = _RE_IMAGE.match(stripped)
        if m:
            image = Image(
                id=m.group(1),
                image_path=m.group(2),
                x=float(m.group(3)),
                y=float(m.group(4)),
                w=float(m.group(5)),
                h=float(m.group(6)),
                parent=m.group(7) or "",
                url=m.group(8) or "",
                annotation=(m.group(9) or "").replace("\\n", "\n"),
            )
            board.images.append(image)
            board._lines.append(("image", image))
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

def _q(value: float) -> int:
    """Quantize a coordinate / size to integer pixels.

    Why: full float precision in saved files produces noisy diffs (~14
    digits per moved element) that obscure real edits. Integer pixels
    are visually indistinguishable in the UI but keep diffs readable
    and round-trips byte-stable.
    """
    return round(value)


def _serialize_box(box: Box) -> str:
    x = _q(box.x)
    y = _q(box.y)
    w = _q(box.w)
    h = _q(box.h)
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
    dx = _q(arrow.label_dx)
    dy = _q(arrow.label_dy)
    if dx or dy:
        base += f" @{dx},{dy}"
    if arrow.style:
        base += f" !{arrow.style}"
    if arrow.textsize:
        base += f" ~{arrow.textsize}"
    if arrow.url:
        base += f" &{arrow.url}"
    return base


def _serialize_note(note: Note) -> str:
    x = _q(note.x)
    y = _q(note.y)
    use_block = note.block_text or '"' in note.text
    if use_block:
        parts = [f'@ note {note.id} {x},{y} """']
        parts.append(note.text)
        suffix = '"""'
        if note.color:
            suffix += f" {note.color}"
        if note.textsize:
            suffix += f" ~{note.textsize}"
        if note.wrap_chars_explicit:
            suffix += f" ~width={note.wrap_chars}"
        if note.style:
            suffix += f" !{note.style}"
        if note.url:
            suffix += f" &{note.url}"
        if note.parent:
            suffix += f" >{note.parent}"
        parts.append(suffix)
        return "\n".join(parts)

    escaped_text = note.text.replace("\n", "\\n")
    s = f'@ note {note.id} {x},{y} "{escaped_text}"'
    if note.color:
        s += f" {note.color}"
    if note.textsize:
        s += f" ~{note.textsize}"
    if note.wrap_chars_explicit:
        s += f" ~width={note.wrap_chars}"
    if note.style:
        s += f" !{note.style}"
    if note.url:
        s += f" &{note.url}"
    if note.parent:
        s += f" >{note.parent}"
    return s


def _serialize_image(image: Image) -> str:
    x = _q(image.x)
    y = _q(image.y)
    w = _q(image.w)
    h = _q(image.h)
    s = f'@ image {image.id} "{image.image_path}" {x},{y} {w}x{h}'
    if image.parent:
        s += f" >{image.parent}"
    if image.url:
        s += f" &{image.url}"
    return s


def _serialize_bookmark(bm: Bookmark) -> str:
    label = bm.label.replace("\n", "\\n")
    s = f'@ bookmark {bm.id} "{label}"'
    if bm.focus:
        s += f' @{",".join(bm.focus)}'
    if bm.pad:
        s += f" ~pad={bm.pad}"
    if bm.view is not None:
        x, y, w, h = (_q(v) for v in bm.view)
        s += f" ~view={x},{y},{w},{h}"
    if bm.isolate:
        s += " ~iso"
    if bm.description:
        desc = bm.description.replace("\n", "\\n")
        s += f' "{desc}"'
    return s


def _serialize_flow(flow: Flow) -> str:
    label = flow.label.replace("\n", "\\n")
    s = f'@ flow {flow.id} "{label}"'
    for step in flow.steps:
        s += f" {step.ref}"
        if step.dwell is not None:
            dwell = int(step.dwell) if step.dwell == int(step.dwell) else step.dwell
            s += f":{dwell}"
    if flow.description:
        desc = flow.description.replace("\n", "\\n")
        s += f' "{desc}"'
    return s


def _serialize_footer(footer: str) -> str:
    escaped = footer.replace("\n", "\\n")
    return f'@ footer "{escaped}"'


def _serialize_title_bg(title_bg: str) -> str:
    return f'@ title-bg {title_bg}'


def serialize(board: Board) -> str:
    """Serialize a Board object back to .grafli format.

    Emits the v2 header only when the board carries bookmarks or flows;
    otherwise stays on v1 so existing files round-trip byte-stable.
    If the board was parsed (has _lines), preserves original ordering.
    Otherwise, outputs comments, then boxes, arrows, notes.
    """
    header = (HEADER_V2 if (board.bookmarks or board.flows or board.footer
                            or board.title_bg) else HEADER)
    meta_lines = []
    if board.footer:
        meta_lines.append(_serialize_footer(board.footer))
    if board.title_bg:
        meta_lines.append(_serialize_title_bg(board.title_bg))
    if board._lines:
        parts = [header, *meta_lines]
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
            elif kind == "image":
                parts.append(_serialize_image(obj))
            elif kind == "bookmark":
                parts.append(_serialize_bookmark(obj))
            elif kind == "flow":
                parts.append(_serialize_flow(obj))
        return "\n".join(parts) + "\n"

    parts = [header, *meta_lines]
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
    for image in board.images:
        parts.append(_serialize_image(image))
    for bm in board.bookmarks:
        parts.append(_serialize_bookmark(bm))
    for flow in board.flows:
        parts.append(_serialize_flow(flow))
    return "\n".join(parts) + "\n"


def serialize_to_file(board: Board, path: str) -> None:
    """Write a Board to a .grafli file on disk."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(serialize(board))


def merge_box_positions(
    new_board: Board, prev_disk: Board | None, in_memory: Board,
) -> Board:
    """3-way merge of box positions for live-reload after external edits.

    For each box in ``new_board``, keep the ``in_memory`` position only
    when the previous disk content had it at the same place as the new
    disk content (user dragged in-app, external edit didn't touch the
    position). When the disk position changed externally, accept it —
    otherwise external position edits are silently discarded.

    Mutates and returns ``new_board``. Notes / images / arrows are
    untouched (their positions already round-trip cleanly via the
    file watcher).
    """
    prev_pos = (
        {b.id: (b.x, b.y) for b in prev_disk.boxes} if prev_disk else {}
    )
    mem_pos = {b.id: (b.x, b.y) for b in in_memory.boxes}
    for box in new_board.boxes:
        was = prev_pos.get(box.id)
        now = (box.x, box.y)
        mem = mem_pos.get(box.id)
        if was is not None and was == now and mem is not None and mem != was:
            box.x, box.y = mem
    return new_board
