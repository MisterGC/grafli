"""Resolved-geometry inspection for `.grafli` files (`grafli inspect`).

Pure query layer: given a parsed ``Board``, report element bounds,
container inner rects after the margin model, sibling gaps, and the
next free slot per container. It answers the geometry questions an
agent would otherwise re-derive by arithmetic from the source — and it
never moves anything: placement stays a deliberate, written-out choice.
"""

from __future__ import annotations

from statistics import median
from typing import Callable, Optional

from grafli.constants import LAYOUT_PADDING
from grafli.format import Board, Note

NoteRectFn = Callable[[Note], Optional[tuple]]

# Container headline clearance per the documented margin model: children
# start 60 px below the top edge for large headings, 40 px otherwise.
_TOP_MARGIN_LARGE = 60.0
_TOP_MARGIN_DEFAULT = 40.0
_LARGE_SIZES = frozenset(
    {"large", "xlarge", "xxlarge", "xxxlarge", "xxxxlarge"}
)

# Children whose coordinate differs by no more than this share a row/column.
_ALIGN_EPS = 2.0


def _top_margin(textsize: str) -> float:
    return _TOP_MARGIN_LARGE if textsize in _LARGE_SIZES else _TOP_MARGIN_DEFAULT


def _rect(x: float, y: float, w: float, h: float) -> list[float]:
    return [x, y, w, h]


def _element_entries(board: Board, note_rect: NoteRectFn | None) -> list[dict]:
    entries: list[dict] = []
    for b in board.boxes:
        entries.append({
            "id": b.id, "type": "box", "label": b.label,
            "rect": _rect(b.x, b.y, b.w, b.h),
            "parent": b.parent or None,
            "color": b.color or None, "textsize": b.textsize or None,
            "flat": b.style == "flat",
        })
    for n in board.notes:
        entry = {
            "id": n.id, "type": "note",
            "text_head": (n.text or "").split("\n", 1)[0][:60],
            "rect": None,
            "position": [n.x, n.y],
            "parent": n.parent or None,
            "textsize": n.textsize or None,
        }
        if note_rect is not None:
            r = note_rect(n)
            if r:
                x1, y1, x2, y2 = r
                entry["rect"] = _rect(x1, y1, x2 - x1, y2 - y1)
        entries.append(entry)
    for im in board.images:
        entries.append({
            "id": im.id, "type": "image",
            "rect": _rect(im.x, im.y, im.w, im.h),
            "parent": im.parent or None,
        })
    return entries


def _axis_groups(values: list[float]) -> list[list[int]]:
    """Group indices whose value matches within the alignment epsilon."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    groups: list[list[int]] = []
    for i in order:
        if groups and abs(values[i] - values[groups[-1][-1]]) <= _ALIGN_EPS:
            groups[-1].append(i)
        else:
            groups.append([i])
    return groups


def _gaps_along(rects: list[list[float]], axis: int) -> list[float]:
    """Edge-to-edge gaps between consecutive rects along axis (0=x, 1=y)."""
    ordered = sorted(rects, key=lambda r: r[axis])
    return [
        round(b[axis] - (a[axis] + a[axis + 2]), 2)
        for a, b in zip(ordered, ordered[1:])
    ]


def _container_entry(parent, child_boxes: list) -> dict:
    top = _top_margin(parent.textsize or "")
    inner = _rect(
        parent.x + LAYOUT_PADDING,
        parent.y + top,
        parent.w - 2 * LAYOUT_PADDING,
        parent.h - top - LAYOUT_PADDING,
    )
    rects = [[c.x, c.y, c.w, c.h] for c in child_boxes]
    ids = [c.id for c in child_boxes]

    ys = [r[1] for r in rects]
    xs = [r[0] for r in rects]
    row_groups = _axis_groups(ys) if rects else []
    col_groups = _axis_groups(xs) if rects else []
    if len(rects) >= 2 and len(row_groups) == 1:
        orientation = "row"
    elif len(rects) >= 2 and len(col_groups) == 1:
        orientation = "column"
    elif len(rects) >= 2:
        orientation = "grid"
    else:
        orientation = "single"

    gaps: list[float] = []
    next_slot = None
    if orientation == "row":
        gaps = _gaps_along(rects, 0)
        last = max(rects, key=lambda r: r[0])
        gap = median(gaps) if gaps else LAYOUT_PADDING * 2
        next_slot = _rect(last[0] + last[2] + gap, last[1], last[2], last[3])
    elif orientation == "column":
        gaps = _gaps_along(rects, 1)
        last = max(rects, key=lambda r: r[1])
        gap = median(gaps) if gaps else LAYOUT_PADDING * 2
        next_slot = _rect(last[0], last[1] + last[3] + gap, last[2], last[3])

    entry = {
        "id": parent.id,
        "rect": _rect(parent.x, parent.y, parent.w, parent.h),
        "inner": inner,
        "top_margin": top,
        "children": ids,
        "orientation": orientation,
        "gaps": gaps,
    }
    if next_slot is not None:
        fits = (
            next_slot[0] >= inner[0] - _ALIGN_EPS
            and next_slot[1] >= inner[1] - _ALIGN_EPS
            and next_slot[0] + next_slot[2] <= inner[0] + inner[2] + _ALIGN_EPS
            and next_slot[1] + next_slot[3] <= inner[1] + inner[3] + _ALIGN_EPS
        )
        entry["next_slot"] = next_slot
        entry["next_slot_fits"] = fits
    return entry


def board_info(board: Board, note_rect: NoteRectFn | None = None) -> dict:
    """Return the resolved-geometry report as a JSON-ready dict."""
    boxes_by_id = {b.id: b for b in board.boxes}
    children_by_parent: dict[str, list] = {}
    for b in board.boxes:
        if b.parent and b.parent in boxes_by_id:
            children_by_parent.setdefault(b.parent, []).append(b)

    containers = [
        _container_entry(boxes_by_id[pid], kids)
        for pid, kids in sorted(children_by_parent.items())
    ]
    arrows = [
        {
            "from": a.from_id, "to": a.to_id,
            "label": a.label or None,
            "heads": [bool(a.head_from), bool(a.head_to)],
            "style": a.style or None,
        }
        for a in board.arrows
    ]

    xs1: list[float] = []
    ys1: list[float] = []
    xs2: list[float] = []
    ys2: list[float] = []
    for b in board.boxes:
        xs1.append(b.x); ys1.append(b.y)
        xs2.append(b.x + b.w); ys2.append(b.y + b.h)
    bounds = (
        _rect(min(xs1), min(ys1), max(xs2) - min(xs1), max(ys2) - min(ys1))
        if xs1 else None
    )

    return {
        "bounds": bounds,
        "elements": _element_entries(board, note_rect),
        "containers": containers,
        "arrows": arrows,
    }
