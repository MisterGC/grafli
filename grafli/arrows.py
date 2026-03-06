"""Pure geometry helpers for arrow drawing between boxes."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPolygonF

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


def _arrowhead_polygon(tip: QPointF, angle: float) -> QPolygonF:
    """Create arrowhead triangle at tip pointing in direction angle (radians)."""
    s = ARROWHEAD_SIZE
    p1 = QPointF(
        tip.x() - s * math.cos(angle - math.pi / 6),
        tip.y() - s * math.sin(angle - math.pi / 6),
    )
    p2 = QPointF(
        tip.x() - s * math.cos(angle + math.pi / 6),
        tip.y() - s * math.sin(angle + math.pi / 6),
    )
    return QPolygonF([tip, p1, p2, tip])
