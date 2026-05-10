"""Static layout diagnostics for `.grafli` files.

Pure functions that take a parsed `Board` (and optionally the source
file's directory for resource resolution) and return a list of
`Diagnostic` records. Used by `grafli diagnose` and exposed for tests.

The checks here are intentionally heuristic. They surface likely
layout problems but cannot be perfectly precise without running Qt's
layout engine — agents should treat findings as guidance, not gates.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from grafli.constants import BOX_FONT_SIZES, LAYOUT_PADDING
from grafli.format import Board, Box, Image, Note


# Optional callable that returns a note's rendered scene rect
# (x1, y1, x2, y2). When supplied (typically from the CLI, which has
# Qt available), notes participate in geometric checks. When None,
# notes are skipped — keeps the pure-function tests fast.
NoteRectFn = Callable[[Note], Optional[tuple]]


ERROR = "error"
WARNING = "warning"
INFO = "info"

_SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Diagnostic:
    code: str
    severity: str
    message: str
    item_ids: list[str] = field(default_factory=list)
    fixable: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _box_rect(b: Box) -> tuple[float, float, float, float]:
    return (b.x, b.y, b.x + b.w, b.y + b.h)


def _image_rect(im: Image) -> tuple[float, float, float, float]:
    return (im.x, im.y, im.x + im.w, im.y + im.h)


def _rect_contains(outer: tuple, inner: tuple) -> bool:
    ox1, oy1, ox2, oy2 = outer
    ix1, iy1, ix2, iy2 = inner
    return ix1 >= ox1 and iy1 >= oy1 and ix2 <= ox2 and iy2 <= oy2


def _rects_overlap(a: tuple, b: tuple) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 < bx2 and ax2 > bx1 and ay1 < by2 and ay2 > by1


def _items_with_rects(board: Board, note_rect: NoteRectFn | None = None):
    """Yield (item, id, rect) for items with computable geometry.

    Notes are included only when ``note_rect`` is provided — typically
    from the CLI, which has Qt available to measure actual font
    metrics. Without it, notes are skipped (a heuristic rect would
    create false positives).
    """
    for b in board.boxes:
        yield b, b.id, _box_rect(b)
    for im in board.images:
        yield im, im.id, _image_rect(im)
    if note_rect is not None:
        for n in board.notes:
            r = note_rect(n)
            if r is not None:
                yield n, n.id, r


def check_child_outside_parent(
    board: Board, note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    boxes_by_id = {b.id: b for b in board.boxes}
    for item, iid, rect in _items_with_rects(board, note_rect):
        parent_id = getattr(item, "parent", "")
        if not parent_id:
            continue
        parent = boxes_by_id.get(parent_id)
        if parent is None:
            diags.append(Diagnostic(
                code="invalid-parent-ref",
                severity=ERROR,
                message=f"{iid!r} declares parent {parent_id!r} which does not exist",
                item_ids=[iid],
                fixable=True,
            ))
            continue
        if not _rect_contains(_box_rect(parent), rect):
            diags.append(Diagnostic(
                code="child-outside-parent",
                severity=WARNING,
                message=f"{iid!r} is positioned outside its parent {parent_id!r}",
                item_ids=[iid, parent_id],
                fixable=True,
            ))
    return diags


def check_sibling_overlap(
    board: Board, note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    items = list(_items_with_rects(board, note_rect))
    groups: dict[str, list] = {}
    for item, iid, rect in items:
        groups.setdefault(getattr(item, "parent", ""), []).append((iid, rect))
    for _parent_id, group in groups.items():
        for i in range(len(group)):
            ai, ar = group[i]
            for j in range(i + 1, len(group)):
                bi, br = group[j]
                if _rects_overlap(ar, br):
                    diags.append(Diagnostic(
                        code="sibling-overlap",
                        severity=WARNING,
                        message=f"{ai!r} overlaps {bi!r} (same containment level)",
                        item_ids=[ai, bi],
                        fixable=True,
                    ))
    return diags


def check_cramped_container(
    board: Board,
    min_padding: float = LAYOUT_PADDING,
    note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    """Flag parent boxes whose children sit tight against the inner edge."""
    diags: list[Diagnostic] = []
    children_by_parent: dict[str, list] = {}
    for _item, _iid, rect in _items_with_rects(board, note_rect):
        pid = getattr(_item, "parent", "")
        if pid:
            children_by_parent.setdefault(pid, []).append(rect)
    boxes_by_id = {b.id: b for b in board.boxes}
    for pid, child_rects in children_by_parent.items():
        parent = boxes_by_id.get(pid)
        if parent is None or not child_rects:
            continue
        cx1 = min(r[0] for r in child_rects)
        cy1 = min(r[1] for r in child_rects)
        cx2 = max(r[2] for r in child_rects)
        cy2 = max(r[3] for r in child_rects)
        px1, py1, px2, py2 = _box_rect(parent)
        worst = min(cx1 - px1, px2 - cx2, cy1 - py1, py2 - cy2)
        if 0 <= worst < min_padding:
            diags.append(Diagnostic(
                code="cramped-container",
                severity=INFO,
                message=(
                    f"{pid!r} children are tight against the edge "
                    f"(min padding ~{worst:.0f}px, recommended >= {min_padding:.0f}px)"
                ),
                item_ids=[pid],
                fixable=True,
            ))
    return diags


def check_label_truncated(board: Board) -> list[Diagnostic]:
    """Heuristic: estimate text width and warn when it likely won't fit."""
    diags: list[Diagnostic] = []
    AVG_CHAR_FACTOR = 0.6  # JetBrains Mono is ~0.6em per char
    H_PADDING = 16          # left+right padding inside box
    TOLERANCE = 1.05        # 5% slack — only complain when clearly over
    for b in board.boxes:
        if not b.label:
            continue
        font_px = BOX_FONT_SIZES.get(b.textsize, BOX_FONT_SIZES[""])
        longest = max((len(line) for line in b.label.split("\n")), default=0)
        if longest == 0:
            continue
        est_w = longest * font_px * AVG_CHAR_FACTOR
        avail_w = b.w - H_PADDING
        if avail_w > 0 and est_w > avail_w * TOLERANCE:
            diags.append(Diagnostic(
                code="label-truncated",
                severity=INFO,
                message=(
                    f"{b.id!r} label ({longest} chars at size "
                    f"{b.textsize or 'default'}) may not fit width "
                    f"{b.w:.0f}px (estimate ~{est_w:.0f}px)"
                ),
                item_ids=[b.id],
                fixable=True,
            ))
    return diags


# Captures `@<path>:<anything>` where path looks like a file (has an
# extension). Trailing `:line` / `:anchor` is consumed to keep matching
# tight, but the anchor itself is not validated.
_REF_RE = re.compile(r"@([^\s@]+\.[A-Za-z0-9]+)(?::[^\s]+)?")


def check_missing_resource(
    board: Board, base_dir: Path | None
) -> list[Diagnostic]:
    """Check `Image.image_path` and `@path[:anchor]` refs in text content."""
    diags: list[Diagnostic] = []
    if base_dir is None:
        return diags
    base = Path(base_dir)
    for im in board.images:
        if not im.image_path:
            continue
        if not (base / im.image_path).exists():
            diags.append(Diagnostic(
                code="missing-resource",
                severity=WARNING,
                message=f"image {im.id!r} -> {im.image_path!r} not found",
                item_ids=[im.id],
                fixable=False,
            ))
    sources: list[tuple[str, str]] = []
    for b in board.boxes:
        sources.append((b.id, b.label or ""))
    for n in board.notes:
        sources.append((n.id, n.text or ""))
    for a in board.arrows:
        sources.append((f"{a.from_id}->{a.to_id}", a.label or ""))
    for iid, text in sources:
        for m in _REF_RE.finditer(text):
            ref_path = m.group(1)
            if not (base / ref_path).exists():
                diags.append(Diagnostic(
                    code="missing-resource",
                    severity=INFO,
                    message=f"{iid!r} references {ref_path!r} which does not exist",
                    item_ids=[iid],
                    fixable=False,
                ))
    return diags


def run_all(
    board: Board,
    base_dir: Path | None = None,
    note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    diags.extend(check_child_outside_parent(board, note_rect=note_rect))
    diags.extend(check_sibling_overlap(board, note_rect=note_rect))
    diags.extend(check_cramped_container(board, note_rect=note_rect))
    diags.extend(check_label_truncated(board))
    diags.extend(check_missing_resource(board, base_dir))
    diags.sort(key=lambda d: (_SEVERITY_ORDER.get(d.severity, 99), d.code, d.item_ids))
    return diags
