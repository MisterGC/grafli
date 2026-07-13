"""Static layout diagnostics for `.grafli` files.

Pure functions that take a parsed `Board` (and optionally the source
file's directory for resource resolution) and return a list of
`Diagnostic` records. Used by `grafli diagnose` and exposed for tests.

The checks here are intentionally heuristic. They surface likely
layout problems but cannot be perfectly precise without running Qt's
layout engine — agents should treat findings as guidance, not gates.
"""

from __future__ import annotations

import difflib
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from grafli.constants import (
    ARROWHEAD_SIZE, BOX_FONT_SIZES, COLOR_TOKENS, LAYOUT_PADDING,
)
from grafli.format import Arrow, Board, Box, Image, Note
from grafli.iconset import has_icon


# Optional callable that returns a note's rendered scene rect
# (x1, y1, x2, y2). When supplied (typically from the CLI, which has
# Qt available), notes participate in geometric checks. When None,
# notes are skipped — keeps the pure-function tests fast.
NoteRectFn = Callable[[Note], Optional[tuple]]

# Optional callable returning an arrow label's rendered size (w, h) in
# scene units, using real font metrics. Needed for arrow-label checks.
ArrowLabelSizeFn = Callable[[Arrow], tuple]


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


def check_parse_errors(board: Board) -> list[Diagnostic]:
    """Surface lines the parser dropped (demoted to comments) as errors.

    This is the scariest failure class for hand/AI edits: a misordered
    modifier or unterminated triple-quote makes the whole element vanish
    from the render with no visible trace. The parser records these as
    ``board.parse_warnings``; here they become machine-checkable.
    """
    diags: list[Diagnostic] = []
    for w in getattr(board, "parse_warnings", []) or []:
        excerpt = w.text if len(w.text) <= 60 else w.text[:57] + "..."
        diags.append(Diagnostic(
            code="parse-error",
            severity=ERROR,
            message=(
                f"line {w.line}: {w.reason} — the element does not render "
                f"({excerpt!r})"
            ),
            item_ids=[],
            fixable=True,
        ))
    return diags


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


def _id_rect_map(board: Board, note_rect: NoteRectFn | None = None) -> dict:
    """Return id -> rect for everything an arrow could connect to."""
    out: dict = {}
    for _item, iid, rect in _items_with_rects(board, note_rect):
        out[iid] = rect
    return out


def _ray_exits_rect(rect: tuple, target: tuple) -> tuple:
    """Where does a ray from rect's center toward ``target`` leave the rect?

    Mirrors what the renderer's ``_rect_edge_point`` does for arrow
    endpoints — start of the visible arrow segment.
    """
    x1, y1, x2, y2 = rect
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    tx, ty = target
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return (cx, cy)
    hw, hh = (x2 - x1) / 2.0, (y2 - y1) / 2.0
    tx_factor = math.inf if dx == 0 else hw / abs(dx)
    ty_factor = math.inf if dy == 0 else hh / abs(dy)
    t = min(tx_factor, ty_factor)
    return (cx + dx * t, cy + dy * t)


def check_arrow_label_crowded(
    board: Board,
    arrow_label_size: ArrowLabelSizeFn | None = None,
    note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    """Flag arrow labels that bleed into an endpoint shape.

    The renderer centers the label on the arrow's visible midpoint, so
    when the gap between endpoints is shorter than the label, the label
    sits on top of one of the boxes. Detection is grounded in real Qt
    font metrics via ``arrow_label_size``; without it, the check is
    skipped (heuristic would create false positives).
    """
    diags: list[Diagnostic] = []
    if arrow_label_size is None:
        return diags

    rects = _id_rect_map(board, note_rect)

    for a in board.arrows:
        if not a.label or a.from_id == a.to_id:
            continue
        src = rects.get(a.from_id)
        dst = rects.get(a.to_id)
        if src is None or dst is None:
            continue

        s_cx, s_cy = (src[0] + src[2]) / 2.0, (src[1] + src[3]) / 2.0
        d_cx, d_cy = (dst[0] + dst[2]) / 2.0, (dst[1] + dst[3]) / 2.0
        start = _ray_exits_rect(src, (d_cx, d_cy))
        end = _ray_exits_rect(dst, (s_cx, s_cy))

        seg_len = math.hypot(end[0] - start[0], end[1] - start[1])
        if seg_len < 1:
            # Endpoints overlap — sibling-overlap will flag this.
            continue

        label_w, label_h = arrow_label_size(a)
        mid_x = (start[0] + end[0]) / 2.0 + a.label_dx
        mid_y = (start[1] + end[1]) / 2.0 + a.label_dy
        # Inflate by 4px to match the renderer's line-clip "gap" rect —
        # captures visual crowding, not just strict glyph overlap.
        inflate = 4.0
        label_rect = (
            mid_x - label_w / 2.0 - inflate,
            mid_y - label_h / 2.0 - inflate,
            mid_x + label_w / 2.0 + inflate,
            mid_y + label_h / 2.0 + inflate,
        )

        for endpoint_id, endpoint_rect in (
            (a.from_id, src), (a.to_id, dst),
        ):
            if _rects_overlap(label_rect, endpoint_rect):
                diags.append(Diagnostic(
                    code="arrow-label-crowded",
                    severity=WARNING,
                    message=(
                        f"arrow {a.from_id!r} -> {a.to_id!r} label "
                        f"({a.label!r}) overlaps {endpoint_id!r} — "
                        f"shorten the label, widen the gap, or offset "
                        f"the label via @dx,dy"
                    ),
                    item_ids=[a.from_id, a.to_id],
                    fixable=True,
                ))
                break  # one finding per arrow
    return diags


def check_arrow_label_covers_head(
    board: Board,
    arrow_label_size: ArrowLabelSizeFn | None = None,
    note_rect: NoteRectFn | None = None,
) -> list[Diagnostic]:
    """Info: label wider than the visible arrow segment — direction lost.

    When the label fills (or exceeds) the arrow length, the renderer
    splits the line around the label rect and the arrowhead disappears
    behind the label. The endpoint-overlap check is the primary signal;
    this one catches the remaining cases (offset labels, longer gaps
    that still aren't long enough for the label).
    """
    diags: list[Diagnostic] = []
    if arrow_label_size is None:
        return diags

    rects = _id_rect_map(board, note_rect)

    for a in board.arrows:
        if not a.label or a.from_id == a.to_id:
            continue
        if not (a.head_to or a.head_from):
            continue  # no head → nothing to obscure
        src = rects.get(a.from_id)
        dst = rects.get(a.to_id)
        if src is None or dst is None:
            continue

        s_cx, s_cy = (src[0] + src[2]) / 2.0, (src[1] + src[3]) / 2.0
        d_cx, d_cy = (dst[0] + dst[2]) / 2.0, (dst[1] + dst[3]) / 2.0
        start = _ray_exits_rect(src, (d_cx, d_cy))
        end = _ray_exits_rect(dst, (s_cx, s_cy))
        seg_len = math.hypot(end[0] - start[0], end[1] - start[1])
        if seg_len < 1:
            continue

        label_w, _label_h = arrow_label_size(a)
        # Reserve one arrowhead worth of clearance on each head end.
        head_clearance = ARROWHEAD_SIZE * (
            int(bool(a.head_to)) + int(bool(a.head_from))
        )
        if label_w >= seg_len - head_clearance:
            diags.append(Diagnostic(
                code="arrow-label-covers-head",
                severity=INFO,
                message=(
                    f"arrow {a.from_id!r} -> {a.to_id!r} label is wider "
                    f"than the visible segment ({seg_len:.0f}px) — the "
                    f"arrowhead may be hidden behind it"
                ),
                item_ids=[a.from_id, a.to_id],
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


def check_unknown_icon(board: Board) -> list[Diagnostic]:
    """A ``*name`` symbol the iconset doesn't know fails silently at paint
    time — surface the typo here instead."""
    diags: list[Diagnostic] = []
    for el in list(board.boxes) + list(board.notes):
        if el.icon and not has_icon(el.icon):
            diags.append(Diagnostic(
                code="unknown-icon",
                severity=WARNING,
                message=(f"{el.id!r} uses unknown symbol *{el.icon} — "
                         "it will not render"),
                item_ids=[el.id],
                fixable=True,
            ))
    return diags


# Literal color names map to the nearest semantic token by hue — difflib
# can't bridge "green" → "forest" lexically, so pin the common ones. This
# only feeds the suggestion text; unknown tokens still fall back to default.
_COLOR_NAME_HINTS = {
    "green": "forest", "blue": "primary", "lightblue": "secondary",
    "red": "clay", "orange": "accent", "yellow": "highlight",
    "gold": "highlight", "purple": "plum", "violet": "plum",
    "pink": "rose", "magenta": "rose", "gray": "muted", "grey": "muted",
    "lavender": "soft", "white": "base", "black": "subtle",
    "dark": "subtle", "cyan": "teal",
}


def check_unknown_color(board: Board) -> list[Diagnostic]:
    """A ``%token`` color the palette doesn't define resolves to the
    default fill with no other trace — the miscolor is invisible until you
    look at the render. Surface the typo, and the nearest real token, here."""
    diags: list[Diagnostic] = []
    valid = list(COLOR_TOKENS.keys())

    def _check(color: str, iid: str) -> None:
        if not color.startswith("%"):
            return  # empty or #hex — nothing to validate
        token = color[1:]
        if token in COLOR_TOKENS:
            return
        suggestion = _COLOR_NAME_HINTS.get(token)
        if suggestion is None:
            near = difflib.get_close_matches(token, valid, n=1)
            suggestion = near[0] if near else None
        hint = f" — did you mean %{suggestion}?" if suggestion else ""
        diags.append(Diagnostic(
            code="unknown-color",
            severity=WARNING,
            message=(f"{iid!r} uses unknown color %{token}{hint} — "
                     "it falls back to the default fill"),
            item_ids=[iid],
            fixable=True,
        ))

    for el in list(board.boxes) + list(board.notes):
        _check(el.color, el.id)
    for a in board.arrows:
        _check(a.color, f"{a.from_id}->{a.to_id}")
    return diags


def run_all(
    board: Board,
    base_dir: Path | None = None,
    note_rect: NoteRectFn | None = None,
    arrow_label_size: ArrowLabelSizeFn | None = None,
) -> list[Diagnostic]:
    diags: list[Diagnostic] = []
    diags.extend(check_parse_errors(board))
    diags.extend(check_unknown_icon(board))
    diags.extend(check_unknown_color(board))
    diags.extend(check_child_outside_parent(board, note_rect=note_rect))
    diags.extend(check_sibling_overlap(board, note_rect=note_rect))
    diags.extend(check_cramped_container(board, note_rect=note_rect))
    diags.extend(check_label_truncated(board))
    diags.extend(check_arrow_label_crowded(
        board, arrow_label_size=arrow_label_size, note_rect=note_rect,
    ))
    diags.extend(check_arrow_label_covers_head(
        board, arrow_label_size=arrow_label_size, note_rect=note_rect,
    ))
    diags.extend(check_missing_resource(board, base_dir))
    diags.sort(key=lambda d: (_SEVERITY_ORDER.get(d.severity, 99), d.code, d.item_ids))
    return diags
