"""The small edits a tab sends: move, rename, add a box, connect, delete.

Each operation is a JSON object with an ``op`` name and its fields, applied
in place to a parsed ``Board``. ``apply_op`` raises ``OpError`` with a
message a person can read when the operation does not fit the board. No Qt:
the server applies these to the version a tab saw, then merges the result
into the file (see ``grafli.serve.room``).
"""

from __future__ import annotations

import math
import re

from grafli.format import Arrow, Board, Box

# The app's new-box size (grafli.constants.DEFAULT_BOX_W / _H), repeated here
# because constants imports Qt; a test keeps the two equal.
NEW_BOX_W = 160
NEW_BOX_H = 80

MAX_LABEL_CHARS = 500

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


def _add_box(board: Board, op: dict) -> dict:
    label = _text(op, "label")
    elem_id = _text(op, "id", required=False) or board.next_box_id()
    if not _ID_RE.fullmatch(elem_id):
        raise OpError(f"{elem_id!r} is not an id: one word, no spaces")
    if _placed(board, elem_id) is not None:
        raise OpError(f"'{elem_id}' already exists")
    w = _number(op, "w") if "w" in op else NEW_BOX_W
    h = _number(op, "h") if "h" in op else NEW_BOX_H
    if w <= 0 or h <= 0:
        raise OpError("a box needs a positive size")
    parent = _text(op, "parent", required=False)
    if parent and board.box_by_id(parent) is None:
        raise OpError(f"no box '{parent}' to put it in")
    board.add_box(Box(elem_id, label, _number(op, "x"), _number(op, "y"),
                      w, h, parent=parent))
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


OPS = {
    "move": _move,
    "rename": _rename,
    "add_box": _add_box,
    "connect": _connect,
    "delete": _delete,
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
