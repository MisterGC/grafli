"""Pure geometry helpers for arrow drawing between boxes."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

from grafli.constants import ARROWHEAD_SIZE
from grafli.format import Box


def _rect_edge_point(x: float, y: float, w: float, h: float, target: QPointF) -> QPointF:
    """Find the point on a rectangle's edge closest to target along the line
    from the rectangle's center to target."""
    cx = x + w / 2
    cy = y + h / 2
    dx = target.x() - cx
    dy = target.y() - cy

    if dx == 0 and dy == 0:
        return QPointF(cx, cy)

    hw, hh = w / 2, h / 2

    # Scale factor to reach the rectangle edge
    scales = []
    if dx != 0:
        scales.append(hw / abs(dx))
    if dy != 0:
        scales.append(hh / abs(dy))
    t = min(scales) if scales else 1.0

    return QPointF(cx + dx * t, cy + dy * t)


def _box_edge_point(box: Box, target: QPointF) -> QPointF:
    """Find the point on box's edge closest to target along the line
    from box center to target."""
    return _rect_edge_point(box.x, box.y, box.w, box.h, target)


def _line_rect_clip(p1: QPointF, p2: QPointF, rect: QRectF) -> tuple[QPointF, QPointF]:
    """Find where the line p1->p2 enters and exits *rect*.

    Returns (enter_point, exit_point) using parametric clipping.
    Falls back to (p1, p2) if the line doesn't cross the rect cleanly.
    """
    dx = p2.x() - p1.x()
    dy = p2.y() - p1.y()

    # Parametric t values for each rect edge
    edges = []
    if dx != 0:
        t_left = (rect.left() - p1.x()) / dx
        t_right = (rect.right() - p1.x()) / dx
        edges.append(t_left)
        edges.append(t_right)
    if dy != 0:
        t_top = (rect.top() - p1.y()) / dy
        t_bottom = (rect.bottom() - p1.y()) / dy
        edges.append(t_top)
        edges.append(t_bottom)

    # Keep only t values where the intersection actually lies on the rect boundary
    valid = []
    for t in edges:
        if t < 0 or t > 1:
            continue
        ix = p1.x() + dx * t
        iy = p1.y() + dy * t
        if (rect.left() - 0.5 <= ix <= rect.right() + 0.5
                and rect.top() - 0.5 <= iy <= rect.bottom() + 0.5):
            valid.append(t)

    if len(valid) < 2:
        return p1, p2

    valid.sort()
    t_enter = valid[0]
    t_exit = valid[-1]

    enter_pt = QPointF(p1.x() + dx * t_enter, p1.y() + dy * t_enter)
    exit_pt = QPointF(p1.x() + dx * t_exit, p1.y() + dy * t_exit)
    return enter_pt, exit_pt


def _aligned_edge_points(
    from_box: Box, to_box: Box,
) -> tuple[QPointF, QPointF] | None:
    """Return edge-to-edge points when boxes share horizontal or vertical range.

    Returns a (start, end) pair for a straight H or V segment, or None when
    the boxes are diagonal (caller falls back to center-to-center logic).
    """
    fcy = from_box.y + from_box.h / 2
    tcy = to_box.y + to_box.h / 2
    fcx = from_box.x + from_box.w / 2
    tcx = to_box.x + to_box.w / 2

    x_lo = max(from_box.x, to_box.x)
    x_hi = min(from_box.x + from_box.w, to_box.x + to_box.w)
    y_lo = max(from_box.y, to_box.y)
    y_hi = min(from_box.y + from_box.h, to_box.y + to_box.h)

    if x_lo < x_hi:
        # Horizontal overlap -> straight vertical line
        mx = (x_lo + x_hi) / 2
        sy = from_box.y + from_box.h if fcy < tcy else from_box.y
        ey = to_box.y if fcy < tcy else to_box.y + to_box.h
        return QPointF(mx, sy), QPointF(mx, ey)

    if y_lo < y_hi:
        # Vertical overlap -> straight horizontal line
        my = (y_lo + y_hi) / 2
        sx = from_box.x + from_box.w if fcx < tcx else from_box.x
        ex = to_box.x if fcx < tcx else to_box.x + to_box.w
        return QPointF(sx, my), QPointF(ex, my)

    return None


def _arrowhead_polygon(tip: QPointF, angle: float,
                       size: float = ARROWHEAD_SIZE) -> QPolygonF:
    """Create arrowhead triangle at tip pointing in direction angle (radians)."""
    s = size
    p1 = QPointF(
        tip.x() - s * math.cos(angle - math.pi / 6),
        tip.y() - s * math.sin(angle - math.pi / 6),
    )
    p2 = QPointF(
        tip.x() - s * math.cos(angle + math.pi / 6),
        tip.y() - s * math.sin(angle + math.pi / 6),
    )
    return QPolygonF([tip, p1, p2, tip])


# ── Routing (#138) ─────────────────────────────────────────────────
#
# A routed connector leaves each endpoint *perpendicular to a box side*
# rather than along the centre-to-centre ray a direct connector uses. That
# swap is what makes right angles and smooth curves possible, and it is also
# what forces the anchors to be spread (see ``spread_offsets``): every direct
# connector aims somewhere different and so lands somewhere different, but
# several routed connectors leaving one side would otherwise stack.

# How far a spline's control point reaches from its endpoint, as a fraction of
# the endpoint separation — enough to leave the box cleanly, clamped so a long
# connector doesn't balloon and a short one doesn't kink.
SPLINE_REACH = 0.42
SPLINE_REACH_MIN = 24.0
SPLINE_REACH_MAX = 220.0

# Corner rounding on an orthogonal bend — matches the rounded-box aesthetic.
ORTHO_RADIUS = 9.0

_NORMALS = {"n": (0.0, -1.0), "s": (0.0, 1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0)}


def anchor_side(rect: tuple, target: QPointF) -> str:
    """Which side of ``rect`` faces ``target`` — the side a routed connector exits.

    Picks by the dominant axis of the centre-to-target delta, scaled by the
    rect's own proportions so a wide, short box prefers its long sides rather
    than being decided by raw pixel distance.
    """
    x, y, w, h = rect
    dx = target.x() - (x + w / 2)
    dy = target.y() - (y + h / 2)
    if w > 0 and h > 0 and abs(dx) / w >= abs(dy) / h:
        return "e" if dx >= 0 else "w"
    return "s" if dy >= 0 else "n"


def point_on_side(rect: tuple, side: str, t: float = 0.5) -> QPointF:
    """The point ``t`` of the way along a rect's side (0..1, 0.5 = midpoint)."""
    x, y, w, h = rect
    if side == "n":
        return QPointF(x + w * t, y)
    if side == "s":
        return QPointF(x + w * t, y + h)
    if side == "w":
        return QPointF(x, y + h * t)
    return QPointF(x + w, y + h * t)


def spread_offsets(count: int) -> list[float]:
    """Where ``count`` connectors sit along a shared side: evenly, none at 0 or 1.

    One connector keeps the midpoint, so the common case is unchanged.
    """
    return [(i + 1) / (count + 1) for i in range(count)]


def ortho_points(start: QPointF, start_side: str,
                 end: QPointF, end_side: str) -> list[QPointF]:
    """Corner points of a right-angle route between two side anchors.

    Two parallel exits give a Z (three segments, turning at the midpoint of the
    gap); perpendicular exits give an L. Both are a pure function of the two
    anchors, so the route never depends on anything but the boards's geometry.
    """
    horiz_start = start_side in ("e", "w")
    horiz_end = end_side in ("e", "w")

    if horiz_start and horiz_end:
        mid = (start.x() + end.x()) / 2
        pts = [start, QPointF(mid, start.y()), QPointF(mid, end.y()), end]
    elif not horiz_start and not horiz_end:
        mid = (start.y() + end.y()) / 2
        pts = [start, QPointF(start.x(), mid), QPointF(end.x(), mid), end]
    elif horiz_start:
        pts = [start, QPointF(end.x(), start.y()), end]
    else:
        pts = [start, QPointF(start.x(), end.y()), end]

    # Drop points that coincide, then points that don't actually turn: an
    # aligned pair collapses a Z into one straight run, and a corner that isn't
    # a corner would still get handed to the rounding pass.
    out: list[QPointF] = []
    for p in pts:
        if not out or (abs(p.x() - out[-1].x()) > 0.01
                       or abs(p.y() - out[-1].y()) > 0.01):
            out.append(p)
    straightened = out[:1]
    for i in range(1, len(out) - 1):
        prev, cur, nxt = straightened[-1], out[i], out[i + 1]
        cross = ((cur.x() - prev.x()) * (nxt.y() - cur.y())
                 - (cur.y() - prev.y()) * (nxt.x() - cur.x()))
        if abs(cross) > 0.01:
            straightened.append(cur)
    if len(out) > 1:
        straightened.append(out[-1])
    return straightened


def _rounded_polyline(points: list[QPointF], radius: float) -> QPainterPath:
    """A polyline with its corners eased — sharp enough to read as orthogonal."""
    path = QPainterPath(points[0])
    for i in range(1, len(points) - 1):
        prev, corner, nxt = points[i - 1], points[i], points[i + 1]
        in_len = math.hypot(corner.x() - prev.x(), corner.y() - prev.y())
        out_len = math.hypot(nxt.x() - corner.x(), nxt.y() - corner.y())
        r = min(radius, in_len / 2, out_len / 2)
        if r < 0.5:
            path.lineTo(corner)
            continue
        ix = corner.x() + (prev.x() - corner.x()) / in_len * r
        iy = corner.y() + (prev.y() - corner.y()) / in_len * r
        ox = corner.x() + (nxt.x() - corner.x()) / out_len * r
        oy = corner.y() + (nxt.y() - corner.y()) / out_len * r
        path.lineTo(QPointF(ix, iy))
        path.quadTo(corner, QPointF(ox, oy))
    path.lineTo(points[-1])
    return path


def spline_path(start: QPointF, start_side: str,
                end: QPointF, end_side: str) -> QPainterPath:
    """A cubic curve leaving each end along its side normal.

    The control points are derived, never authored: reach is a clamped fraction
    of the endpoint separation, so the same two boxes always produce the same
    curve in the app and in a headless render.
    """
    span = math.hypot(end.x() - start.x(), end.y() - start.y())
    reach = max(SPLINE_REACH_MIN, min(SPLINE_REACH_MAX, span * SPLINE_REACH))
    sx, sy = _NORMALS[start_side]
    ex, ey = _NORMALS[end_side]
    path = QPainterPath(start)
    path.cubicTo(
        QPointF(start.x() + sx * reach, start.y() + sy * reach),
        QPointF(end.x() + ex * reach, end.y() + ey * reach),
        end,
    )
    return path


def routed_path(routing: str, start: QPointF, start_side: str,
                end: QPointF, end_side: str) -> QPainterPath:
    """The connector body for a routing, as a path."""
    if routing == "spline":
        return spline_path(start, start_side, end, end_side)
    if routing == "ortho":
        return _rounded_polyline(
            ortho_points(start, start_side, end, end_side), ORTHO_RADIUS)
    path = QPainterPath(start)
    path.lineTo(end)
    return path


def path_end_angle(path: QPainterPath, at_end: bool = True) -> float:
    """Direction the path is travelling at one of its ends, in radians.

    An arrowhead has to point along the curve it terminates, not along the
    chord between the endpoints — on a spline those differ sharply.
    """
    eps = 0.02
    if at_end:
        a, b = path.pointAtPercent(1.0 - eps), path.pointAtPercent(1.0)
    else:
        a, b = path.pointAtPercent(eps), path.pointAtPercent(0.0)
    dx, dy = b.x() - a.x(), b.y() - a.y()
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        p0, p1 = path.pointAtPercent(0.0), path.pointAtPercent(1.0)
        dx, dy = (p1.x() - p0.x(), p1.y() - p0.y()) if at_end else (
            p0.x() - p1.x(), p0.y() - p1.y())
    return math.atan2(dy, dx)


def _segment_outside(a: QPointF, b: QPointF, rect: QRectF):
    """The parts of segment ``a``→``b`` that lie outside ``rect``.

    Returns ``(head, tail)`` — the run before the rect and the run after it,
    either of which may be ``None``. ``(None, None)`` means the segment is
    wholly swallowed. Liang-Barsky rather than vertex sampling, because a
    flattened straight run has no vertices in the middle for a label to land
    between.
    """
    dx, dy = b.x() - a.x(), b.y() - a.y()
    t0, t1 = 0.0, 1.0
    for num, den in ((a.x() - rect.left(), -dx), (rect.right() - a.x(), dx),
                     (a.y() - rect.top(), -dy), (rect.bottom() - a.y(), dy)):
        if den == 0:
            if num < 0:
                return (a, b), None       # parallel and clear of the rect
            continue
        t = num / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    if t0 >= t1:
        return (a, b), None               # never enters the rect

    def at(t):
        return QPointF(a.x() + dx * t, a.y() + dy * t)

    head = (a, at(t0)) if t0 > 0.001 else None
    tail = (at(t1), b) if t1 < 0.999 else None
    if head is None and tail is None:
        return None, None
    if head is None:
        return tail, None                 # only the far side survives
    return head, tail


def split_path_at_rect(path: QPainterPath, rect: QRectF) -> list[QPainterPath]:
    """The path with the part inside ``rect`` removed — the label gap.

    A direct connector can be clipped analytically (``_line_rect_clip``), but a
    curve or a stair has no single parametric line to solve, so the path is
    walked instead and the runs that stay outside the label are rebuilt. Returns
    one path when the label misses the connector, two when it interrupts it.

    The walk uses Qt's own flattening rather than sampling ``pointAtPercent``:
    every connector is re-split on every redraw, and sampling in Python made a
    drag on a large board four times more expensive than the geometry needed.
    """
    runs: list[list[QPointF]] = []
    for polygon in path.toSubpathPolygons():
        current: list[QPointF] = []
        pts = list(polygon)
        for a, b in zip(pts, pts[1:]):
            head, tail = _segment_outside(a, b, rect)
            if head is None:              # wholly inside the label
                if len(current) > 1:
                    runs.append(current)
                current = []
                continue
            if not current:
                current.append(head[0])
            current.append(head[1])
            if tail is not None:          # the label interrupts this segment
                if len(current) > 1:
                    runs.append(current)
                current = [tail[0], tail[1]]
        if len(current) > 1:
            runs.append(current)

    if not runs:
        return []
    out = []
    for run in runs:
        sub = QPainterPath(run[0])
        for pt in run[1:]:
            sub.lineTo(pt)
        out.append(sub)
    return out
