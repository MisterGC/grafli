"""The small edits a tab sends: move, rename, add a box, connect, delete,
and grafli lines typed on the tab's ``:`` command line.

Each operation is a JSON object with an ``op`` name and its fields, applied
in place to a parsed ``Board``. ``apply_op`` raises ``OpError`` with a
message a person can read when the operation does not fit the board. No Qt:
the server applies these to the version a tab saw, then merges the result
into the file (see ``grafli.serve.room``).
"""

from __future__ import annotations

import dataclasses
import math
import re

from grafli.format import Arrow, Board, Box, parse, supported_version

# The app's new-box size (grafli.constants.DEFAULT_BOX_W / _H), repeated here
# because constants imports Qt; a test keeps the two equal.
NEW_BOX_W = 160
NEW_BOX_H = 80

MAX_LABEL_CHARS = 500
MAX_LINES_CHARS = 4000

# The gap the app leaves between a box and one made beside it (o / O,
# Ctrl+arrow: grafli.view.structure._create_adjacent_box).
BESIDE_GAP = 40
SIDES = ("below", "above", "right", "left")

# An element id as the format reads it: one token, no whitespace.
_ID_RE = re.compile(r"\S+")


class OpError(ValueError):
    """An operation that does not fit the board it is applied to."""


def _number(op: dict, name: str) -> float:
    value = op.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpError(f"'{name}' must be a number")
    if not math.isfinite(value):
        # The file holds whole numbers; NaN and infinity have none.
        raise OpError(f"'{name}' must be a finite number")
    return float(value)


def _text(op: dict, name: str, *, required: bool = True) -> str:
    value = op.get(name, None if required else "")
    if not isinstance(value, str):
        raise OpError(f"'{name}' must be a string")
    if len(value) > MAX_LABEL_CHARS:
        raise OpError(f"'{name}' is longer than {MAX_LABEL_CHARS} characters")
    return value


def _placed(board: Board, elem_id: str):
    """The box, note or image *elem_id*, or None."""
    return (board.box_by_id(elem_id) or board.note_by_id(elem_id)
            or board.image_by_id(elem_id))


def _arrow(board: Board, ref: str) -> Arrow | None:
    """The arrow with id *ref*, or the plain arrow named ``from->to``."""
    arrow = board.arrow_by_id(ref)
    if arrow is not None:
        return arrow
    if "->" in ref:
        a, b = ref.split("->", 1)
        for arrow in board.arrows:
            if not arrow.id and arrow.from_id == a and arrow.to_id == b:
                return arrow
    return None


def _descendants(board: Board, box_id: str) -> list:
    out = []
    for el in [*board.boxes, *board.notes, *board.images]:
        if el.parent == box_id:
            out.append(el)
            if isinstance(el, Box):
                out.extend(_descendants(board, el.id))
    return out


def _move(board: Board, op: dict) -> dict:
    elem_id = _text(op, "id")
    el = _placed(board, elem_id)
    if el is None:
        raise OpError(f"no box, note or image '{elem_id}'")
    x, y = _number(op, "x"), _number(op, "y")
    dx, dy = x - el.x, y - el.y
    el.x, el.y = x, y
    # A container carries what it holds, as a drag in the app does.
    if isinstance(el, Box):
        for child in _descendants(board, el.id):
            child.x += dx
            child.y += dy
    return {"id": elem_id}


def _rename(board: Board, op: dict) -> dict:
    elem_id = _text(op, "id")
    label = _text(op, "label")
    box = board.box_by_id(elem_id)
    if box is not None:
        box.label = label
        return {"id": elem_id}
    note = board.note_by_id(elem_id)
    if note is not None:
        if note.attach_kind == "doc":
            raise OpError(f"'{elem_id}' keeps its text in a doc; "
                          "edit the doc instead")
        note.text = label
        return {"id": elem_id}
    arrow = _arrow(board, elem_id)
    if arrow is not None:
        arrow.label = label
        return {"id": elem_id}
    raise OpError(f"no box, note or arrow '{elem_id}'")


def _overlaps(board: Board, parent: str, rect, skip: str = "") -> bool:
    """Whether *rect* overlaps a box or image that sits beside it (one with
    the same parent)."""
    x, y, w, h = rect
    for el in [*board.boxes, *board.images]:
        if el.id == skip or el.parent != parent or el.id == parent:
            continue
        if x < el.x + el.w and el.x < x + w and y < el.y + el.h and el.y < y + h:
            return True
    return False


def _beside(board: Board, anchor, side: str, w: float, h: float):
    """Where a *w* x *h* box goes on *side* of *anchor*: the app's spot, or
    further along that side until it overlaps nothing beside it."""
    ax, ay = anchor.x, anchor.y
    aw = getattr(anchor, "w", NEW_BOX_W)
    ah = getattr(anchor, "h", NEW_BOX_H)
    step = {"below": (0, ah + BESIDE_GAP), "above": (0, -(h + BESIDE_GAP)),
            "right": (aw + BESIDE_GAP, 0), "left": (-(w + BESIDE_GAP), 0)}[side]
    stride = {"below": (0, h + BESIDE_GAP), "above": (0, -(h + BESIDE_GAP)),
              "right": (w + BESIDE_GAP, 0), "left": (-(w + BESIDE_GAP), 0)}[side]
    x, y = ax + step[0], ay + step[1]
    for _ in range(64):
        if not _overlaps(board, anchor.parent, (x, y, w, h)):
            break
        x, y = x + stride[0], y + stride[1]
    return x, y


def _add_box(board: Board, op: dict) -> dict:
    """A new box at x, y — or *beside* an element, on *side* (below by
    default), the way the app's o / O / Ctrl+arrow place it: the anchor's
    size and parent, and with *connect* an arrow from the anchor to it."""
    label = _text(op, "label")
    elem_id = _text(op, "id", required=False) or board.next_box_id()
    if not _ID_RE.fullmatch(elem_id):
        raise OpError(f"{elem_id!r} is not an id: one word, no spaces")
    if _placed(board, elem_id) is not None:
        raise OpError(f"'{elem_id}' already exists")
    beside = _text(op, "beside", required=False)
    anchor = _placed(board, beside) if beside else None
    if beside and anchor is None:
        raise OpError(f"no box, note or image '{beside}' to put it beside")
    default_w = anchor.w if isinstance(anchor, Box) else NEW_BOX_W
    default_h = anchor.h if isinstance(anchor, Box) else NEW_BOX_H
    w = _number(op, "w") if "w" in op else default_w
    h = _number(op, "h") if "h" in op else default_h
    if w <= 0 or h <= 0:
        raise OpError("a box needs a positive size")
    parent = _text(op, "parent", required=False)
    if anchor is not None:
        side = _text(op, "side", required=False) or "below"
        if side not in SIDES:
            raise OpError(f"'side' is one of {', '.join(SIDES)}")
        x, y = _beside(board, anchor, side, w, h)
        parent = parent or anchor.parent
    else:
        x, y = _number(op, "x"), _number(op, "y")
    if parent and board.box_by_id(parent) is None:
        raise OpError(f"no box '{parent}' to put it in")
    board.add_box(Box(elem_id, label, x, y, w, h, parent=parent))
    if anchor is not None and op.get("connect") is True:
        board.add_arrow(Arrow(anchor.id, elem_id))
    return {"id": elem_id}


def _connect(board: Board, op: dict) -> dict:
    a, b = _text(op, "from"), _text(op, "to")
    for end in (a, b):
        if _placed(board, end) is None:
            raise OpError(f"no box, note or image '{end}'")
    if a == b:
        raise OpError("an arrow needs two different ends")
    if any(not x.id and x.from_id == a and x.to_id == b
           for x in board.arrows):
        raise OpError(f"'{a}' is already connected to '{b}'")
    board.add_arrow(Arrow(a, b, label=_text(op, "label", required=False)))
    return {"id": f"{a}->{b}"}


def _delete(board: Board, op: dict) -> dict:
    elem_id = _text(op, "id")
    el = _placed(board, elem_id)
    if el is None:
        arrow = _arrow(board, elem_id)
        if arrow is None:
            raise OpError(f"no element '{elem_id}'")
        board.remove_arrow(arrow)
        return {"id": elem_id}
    # As the app deletes: what it held is let go, its arrows go with it.
    for other in [*board.boxes, *board.notes, *board.images]:
        if other.parent == elem_id:
            other.parent = ""
    for arrow in list(board.arrows):
        if elem_id in (arrow.from_id, arrow.to_id):
            board.remove_arrow(arrow)
    if isinstance(el, Box):
        board.remove_box(el)
    elif board.note_by_id(elem_id) is el:
        board.remove_note(el)
    else:
        board.remove_image(el)
    return {"id": elem_id}


# A box line on the command line may leave out where the box goes:
# ``@ box cache "Cache"`` (and anything after the label).
_BOX_HEAD_RE = re.compile(r'^@\s+box\s+(\S+)\s+"((?:[^"\\]|\\.)*)"(.*)$')
_PLACE_RE = re.compile(r'^\s+-?[\d.]+,\s*-?[\d.]+\s+[\d.]+x[\d.]+')
_PARENT_RE = re.compile(r'\s>\S+')
_KINDS = ("box", "arrow", "note", "image")


def _command_lines(text: str) -> list[str]:
    """The element lines of *text*: blank lines and comments dropped, and a
    line may leave out the ``@ `` (``box cache "Cache"``)."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("@"):
            line = "@ " + line
        kind = line[1:].split(None, 1)[0] if line[1:].strip() else ""
        if kind not in _KINDS:
            raise OpError(f"':' takes box, arrow, note and image lines, "
                          f"not {raw.strip()!r}")
        out.append(line)
    return out


def _inside(ref: str) -> bool:
    """Whether a file *ref* stays in the board's folder: relative, no
    ``..``, no ``~``. A URL is no file."""
    if "://" in ref:
        return True
    path = ref.split("#", 1)[0]
    if path.startswith(("/", "\\", "~")) or re.match(r"[A-Za-z]:", path):
        return False
    return ".." not in re.split(r"[\\/]", path)


def _check_files(el) -> None:
    """Refuse a line that points at a file outside the board's folder: the
    worker reads what an image or attachment names and sends it to every
    tab."""
    refs = [getattr(el, "image_path", ""), el.url]
    for ref in refs:
        if ref and not _inside(ref):
            raise OpError(f"'{ref}' lies outside the board's folder; "
                          "a tab may only name files inside it")


def _fields(dst, src) -> None:
    for f in dataclasses.fields(src):
        if not f.name.startswith("_"):
            setattr(dst, f.name, getattr(src, f.name))


def _lines(board: Board, op: dict) -> dict:
    """Lines of grafli syntax, as typed on the tab's ``:`` command line.

    Each line adds its element, or restates the element with that id (a
    plain arrow: with those ends) in full. A box line without a place
    keeps the place of the box it restates; a new one goes beside *beside*,
    below it, or at x, y.
    """
    text = op.get("text")
    if not isinstance(text, str):
        raise OpError("'text' must be a string")
    if len(text) > MAX_LINES_CHARS:
        raise OpError(f"'text' is longer than {MAX_LINES_CHARS} characters")
    lines = _command_lines(text)
    if not lines:
        raise OpError("nothing to add: type a line such as "
                      '@ box cache "Cache"')
    beside = _text(op, "beside", required=False)
    anchor = _placed(board, beside) if beside else None
    if beside and anchor is None:
        raise OpError(f"no box, note or image '{beside}' to put it beside")
    kept_parent: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = _BOX_HEAD_RE.match(line)
        if not m or _PLACE_RE.match(m.group(3)):
            continue
        box_id, rest = m.group(1), m.group(3)
        old = board.box_by_id(box_id)
        if old is not None:
            x, y, w, h = old.x, old.y, old.w, old.h
            if not _PARENT_RE.search(rest):
                kept_parent[box_id] = old.parent
        else:
            w, h = ((anchor.w, anchor.h) if isinstance(anchor, Box)
                    else (NEW_BOX_W, NEW_BOX_H))
            if anchor is not None:
                x, y = _beside(board, anchor, "below", w, h)
                if not _PARENT_RE.search(rest) and anchor.parent:
                    kept_parent[box_id] = anchor.parent
            elif "x" in op and "y" in op:
                x, y = _number(op, "x") - w / 2, _number(op, "y") - h / 2
            else:
                x, y = 0.0, 0.0
            # Several new boxes in one command go each below the last.
            anchor = Box(box_id, "", x, y, w, h,
                         parent=kept_parent.get(box_id, ""))
        lines[i] = (f'@ box {box_id} "{m.group(2)}" '
                    f'{round(x)},{round(y)} {round(w)}x{round(h)}{rest}')
    parsed = parse(f"#!grafli v{supported_version()}\n" + "\n".join(lines))
    if parsed.parse_warnings:
        w = parsed.parse_warnings[0]
        raise OpError(f"not a grafli line: {w.text!r} — {w.reason}")
    # Every check before the first change: a refused command leaves the
    # board as it was.
    kinds = {"box": (parsed.boxes, board.box_by_id, board.add_box),
             "note": (parsed.notes, board.note_by_id, board.add_note),
             "image": (parsed.images, board.image_by_id, board.add_image)}
    taken = Board(notes=list(board.notes))
    for note in parsed.notes:
        if not note.id:
            note.id = taken.next_note_id()
        taken.notes.append(note)
    for box in parsed.boxes:
        if box.id in kept_parent and not box.parent:
            box.parent = kept_parent[box.id]
    new_boxes = {box.id for box in parsed.boxes}
    new_ends = {el.id for els, _, _ in kinds.values() for el in els}
    for kind, (els, same, _add) in kinds.items():
        for el in els:
            if same(el.id) is None and _placed(board, el.id) is not None:
                raise OpError(f"'{el.id}' is already on the board, "
                              f"and not as a {kind}")
            if (el.parent and board.box_by_id(el.parent) is None
                    and el.parent not in new_boxes):
                raise OpError(f"no box '{el.parent}' to put '{el.id}' in")
    for arrow in parsed.arrows:
        for end in (arrow.from_id, arrow.to_id):
            if _placed(board, end) is None and end not in new_ends:
                raise OpError(f"no box, note or image '{end}'")
    for el in [*parsed.boxes, *parsed.notes, *parsed.images, *parsed.arrows]:
        _check_files(el)
    touched: list[str] = []
    for els, same, add in kinds.values():
        for el in els:
            old = same(el.id)
            if old is not None:
                _fields(old, el)
            else:
                add(el)
            touched.append(el.id)
    for arrow in parsed.arrows:
        ref = arrow.id or f"{arrow.from_id}->{arrow.to_id}"
        old = _arrow(board, ref)
        if old is not None:
            _fields(old, arrow)
        else:
            board.add_arrow(arrow)
        touched.append(ref)
    return {"id": touched[0], "ids": touched}


OPS = {
    "move": _move,
    "rename": _rename,
    "add_box": _add_box,
    "connect": _connect,
    "delete": _delete,
    "lines": _lines,
}


def apply_op(board: Board, op: dict) -> dict:
    """Apply *op* to *board* in place; returns what it touched (``id``)."""
    if not isinstance(op, dict):
        raise OpError("an edit is a JSON object")
    name = op.get("op")
    fn = OPS.get(name) if isinstance(name, str) else None
    if fn is None:
        raise OpError(f"unknown edit {name!r}; one of {', '.join(OPS)}")
    return fn(board, op)
