"""Pure geometry helpers for arrow drawing between boxes."""

from __future__ import annotations

import heapq
import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

from grafli.constants import ARROWHEAD_SIZE


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


def _rect_centre(rect: tuple) -> QPointF:
    x, y, w, h = rect
    return QPointF(x + w / 2, y + h / 2)


# ── Sides of a rect ────────────────────────────────────────────────
#
# Every connector endpoint is a (side, t) pair on one of the four sides,
# whether it was derived from a ray, chosen for a routing, or pushed along by
# the spread pass. These three convert between that pair and a scene point.


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


def side_of_point(rect: tuple, pt: QPointF) -> str:
    """Which side of ``rect`` a point sits on (nearest edge)."""
    x, y, w, h = rect
    dists = {
        "w": abs(pt.x() - x), "e": abs(pt.x() - (x + w)),
        "n": abs(pt.y() - y), "s": abs(pt.y() - (y + h)),
    }
    return min(dists, key=dists.get)


# A connector may pin the side it leaves and the side it enters (#209). The file
# names them as a reader would; the geometry keeps its compass letters.
SIDE_NAMES = {"top": "n", "right": "e", "bottom": "s", "left": "w"}


def t_of_point(rect: tuple, side: str, pt: QPointF) -> float:
    """Where along a side a point sits, as 0..1."""
    x, y, w, h = rect
    if side in ("n", "s"):
        return 0.0 if w <= 0 else max(0.0, min(1.0, (pt.x() - x) / w))
    return 0.0 if h <= 0 else max(0.0, min(1.0, (pt.y() - y) / h))


def along_side(rect: tuple, side: str, pt: QPointF) -> float:
    """Where along a side a point lies, as a fraction that runs past 0..1 for
    a point beyond either end of the side — so two points both beyond it
    still rank against each other."""
    x, y, w, h = rect
    if side in ("n", "s"):
        return 0.0 if w <= 0 else (pt.x() - x) / w
    return 0.0 if h <= 0 else (pt.y() - y) / h


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
    f_rect: tuple, t_rect: tuple,
) -> tuple[QPointF, QPointF] | None:
    """Return edge-to-edge points when two rects share enough of an axis.

    Returns a (start, end) pair for a straight H or V segment, or None when
    the rects are diagonal (caller falls back to center-to-center logic).

    "Enough" means the shared range covers at least one of the two centres.
    That is the overlap a reader takes for deliberate alignment, and it is also
    what keeps the straight segment out of both elements' corners. Two elements
    that merely graze each other's range would otherwise get a line squeezed
    into the sliver they share, hugging one corner of each (#156).
    """
    fx, fy, fw, fh = f_rect
    tx, ty, tw, th = t_rect
    fcx, fcy = fx + fw / 2, fy + fh / 2
    tcx, tcy = tx + tw / 2, ty + th / 2

    x_lo = max(fx, tx)
    x_hi = min(fx + fw, tx + tw)
    y_lo = max(fy, ty)
    y_hi = min(fy + fh, ty + th)

    if x_lo < x_hi and (x_lo <= fcx <= x_hi or x_lo <= tcx <= x_hi):
        # Horizontal overlap -> straight vertical line
        mx = (x_lo + x_hi) / 2
        sy = fy + fh if fcy < tcy else fy
        ey = ty if fcy < tcy else ty + th
        return QPointF(mx, sy), QPointF(mx, ey)

    if y_lo < y_hi and (y_lo <= fcy <= y_hi or y_lo <= tcy <= y_hi):
        # Vertical overlap -> straight horizontal line
        my = (y_lo + y_hi) / 2
        sx = fx + fw if fcx < tcx else fx
        ex = tx if fcx < tcx else tx + tw
        return QPointF(sx, my), QPointF(ex, my)

    return None


# Where along a side a connector may attach, as fractions of the side's length.
# Outside this band an endpoint reads as a corner connection rather than as a
# link between two elements, so a natural position landing there is pulled back
# in (#156). Wide enough that a correction stays close to the centre-to-centre
# ray it replaces — a line that visibly misses the element it points at looks
# worse than a corner exit.
CENTRAL_BAND_LO = 0.25
CENTRAL_BAND_HI = 1.0 - CENTRAL_BAND_LO


def facing_sides(f_rect: tuple, t_rect: tuple) -> tuple[str, str]:
    """The opposite pair of sides two rects turn toward each other.

    Which axis dominates cannot be read off the centre delta alone: two boxes
    stacked with a sideways offset would count as a horizontal relation as soon
    as that offset is the larger number, however far apart they sit vertically.
    Each axis is therefore measured against the extent the two rects themselves
    cover on it, which asks the question that matters — on which axis do they
    actually stand clear of each other.
    """
    d = _rect_centre(t_rect) - _rect_centre(f_rect)
    span_x = (f_rect[2] + t_rect[2]) / 2
    span_y = (f_rect[3] + t_rect[3]) / 2
    reach_x = abs(d.x()) / span_x if span_x > 0 else math.inf
    reach_y = abs(d.y()) / span_y if span_y > 0 else math.inf
    if reach_x >= reach_y:
        return ("e", "w") if d.x() >= 0 else ("w", "e")
    return ("s", "n") if d.y() >= 0 else ("n", "s")


def _central_endpoint(rect: tuple, pt: QPointF,
                      other_centre: QPointF, facing: str) -> QPointF:
    """``pt`` moved out of the corner zone, or returned untouched.

    An endpoint already in the central band of its side is the one the reader
    expects — the clipped centre-to-centre ray — and stays exactly where it is.
    One in a corner zone moves onto the side that faces the other element,
    aiming at that element's centre, and is then held inside the band.
    """
    side = side_of_point(rect, pt)
    t = t_of_point(rect, side, pt)
    if CENTRAL_BAND_LO <= t <= CENTRAL_BAND_HI:
        return pt
    if side != facing:
        side = facing
        t = t_of_point(rect, side, other_centre)
    return point_on_side(rect, side, max(CENTRAL_BAND_LO,
                                         min(CENTRAL_BAND_HI, t)))


def endpoint_pair(f_rect: tuple, t_rect: tuple,
                  allow_aligned: bool = True) -> tuple[QPointF, QPointF]:
    """Where a direct connector between two elements attaches to each.

    Conceptually centre-to-centre: the straight segment clipped to both edges
    is what a reader expects, so it is kept whenever both of its ends already
    land in the central band of their side. Only an end that would sit in a
    corner is moved (#156).

    ``allow_aligned`` enables the straight-segment shortcut for elements whose
    ranges overlap deliberately; the caller withholds it where that shortcut
    has never applied. Pure geometry throughout, so the app and a headless
    render place every endpoint identically.
    """
    if allow_aligned:
        aligned = _aligned_edge_points(f_rect, t_rect)
        if aligned:
            return aligned

    f_mid, t_mid = _rect_centre(f_rect), _rect_centre(t_rect)
    s_pt = _rect_edge_point(*f_rect, t_mid)
    e_pt = _rect_edge_point(*t_rect, f_mid)
    f_face, t_face = facing_sides(f_rect, t_rect)
    return (_central_endpoint(f_rect, s_pt, t_mid, f_face),
            _central_endpoint(t_rect, e_pt, f_mid, t_face))


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


def _dot_polygon(centre: QPointF, radius: float, steps: int = 24) -> QPolygonF:
    """A filled dot at a connector end (`!dot`, #210), as a polygon so it is
    selected, recoloured and hit-tested like an arrowhead."""
    return QPolygonF([
        QPointF(centre.x() + radius * math.cos(2 * math.pi * i / steps),
                centre.y() + radius * math.sin(2 * math.pi * i / steps))
        for i in range(steps)])


# ── Routing (#138) ─────────────────────────────────────────────────
#
# A routed connector leaves each endpoint *perpendicular to a box side*
# rather than along the centre-to-centre ray a direct connector uses. That
# swap is what makes right angles and smooth curves possible, and it is also
# what forces the anchors to be spread: every direct connector aims somewhere
# different and so lands somewhere different, but several routed connectors
# leaving one side would otherwise stack.

# How far a spline's control point reaches from its endpoint, as a fraction of
# the endpoint separation — enough to leave the box cleanly, clamped so a long
# connector doesn't balloon and a short one doesn't kink.
SPLINE_REACH = 0.42
SPLINE_REACH_MIN = 24.0
SPLINE_REACH_MAX = 220.0

# Corner rounding on an orthogonal bend — matches the rounded-box aesthetic.
ORTHO_RADIUS = 9.0

# Where a Z-bend's mid-line may sit, as fractions of the gap, ordered by
# distance from the middle. A tie goes to the route we would have drawn anyway,
# so obstacle awareness never moves a connector that was already clear.
ORTHO_MID_FRACTIONS = (0.5, 0.42, 0.58, 0.34, 0.66,
                       0.26, 0.74, 0.18, 0.82, 0.1, 0.9)

# How far clear of a box a mid-line derived from that box's edge sits.
ORTHO_MID_CLEARANCE = 10.0

# Work bounds for the mid-line search. Each obstacle contributes two candidates,
# so without these the cost of one connector grows with the square of how many
# boxes it spans — a whole-board connector on a large board then dominates the
# redraw. Both caps keep what is nearest the default mid-line, which is also
# what matters most: we want the smallest deviation that clears the route, so a
# far-off candidate is worthless even when it happens to be free.
ORTHO_MAX_CANDIDATES = 16
ORTHO_MAX_OBSTACLES = 24

# How many columns a detour tries, nearest the straight line first (#284).
ORTHO_MAX_DETOURS = 16

_NORMALS = {"n": (0.0, -1.0), "s": (0.0, 1.0), "e": (1.0, 0.0), "w": (-1.0, 0.0)}


def _segment_hits_rect(a: QPointF, b: QPointF, rect: QRectF) -> bool:
    """Whether segment ``a``→``b`` touches ``rect`` at all (Liang-Barsky)."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    t0, t1 = 0.0, 1.0
    for num, den in ((a.x() - rect.left(), -dx), (rect.right() - a.x(), dx),
                     (a.y() - rect.top(), -dy), (rect.bottom() - a.y(), dy)):
        if den == 0:
            if num < 0:
                return False              # parallel to this edge and outside it
            continue
        t = num / den
        if den < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
    return t0 < t1


def _relevant(start: QPointF, end: QPointF,
              obstacles: list[QRectF] | None) -> list[QRectF]:
    """Obstacles inside the anchors' bounding box — the only ones reachable.

    Every candidate route stays within that box, so anything outside it can be
    rejected before the candidate loop. This is what keeps the search cheap on a
    large board: the cost tracks local crowding, not the box count.
    """
    if not obstacles:
        return []
    # Two aligned anchors span a box of no width, and Qt finds such a box
    # intersecting nothing — so it is widened by half a pixel each way.
    span = QRectF(QPointF(min(start.x(), end.x()), min(start.y(), end.y())),
                  QPointF(max(start.x(), end.x()), max(start.y(), end.y()))
                  ).adjusted(-0.5, -0.5, 0.5, 0.5)
    return [r for r in obstacles if r.intersects(span)]


def _z_points(start: QPointF, end: QPointF,
              mid: float, horizontal: bool) -> list[QPointF]:
    """The four corners of a Z-bend whose mid-line sits at ``mid``."""
    if horizontal:
        return [start, QPointF(mid, start.y()), QPointF(mid, end.y()), end]
    return [start, QPointF(start.x(), mid), QPointF(end.x(), mid), end]


def _crossed(points: list[QPointF], obstacles: list[QRectF],
             limit: int | None = None) -> int:
    """How many obstacles the polyline touches.

    Stops once ``limit`` is reached — a candidate already worse than the best
    one so far needs no exact score, only the news that it lost.
    """
    hits = 0
    for rect in obstacles:
        if any(_segment_hits_rect(points[i], points[i + 1], rect)
               for i in range(len(points) - 1)):
            hits += 1
            if limit is not None and hits >= limit:
                break
    return hits


def _best_mid(start: QPointF, end: QPointF,
              horizontal: bool, obstacles: list[QRectF],
              default: float | None = None) -> float:
    """Where to put a Z-bend's mid-line so it crosses as few boxes as possible.

    Every candidate lies between the two anchors, so the route can slide but
    never detour outside their bounding box — that confinement is what keeps
    this from becoming a router (see #142). When nothing is clear the middle of
    the gap wins, so a hard case stays predictable rather than contorted.

    ``default`` replaces the middle of the gap as the line to keep when it is
    clear: the turn line a sibling pass gave this arrow (``turn_lines``).
    """
    lo = start.x() if horizontal else start.y()
    hi = end.x() if horizontal else end.y()
    if default is None:
        default = (lo + hi) / 2
    if not obstacles:
        return default

    # The overwhelmingly common case is a route that was already clear, so score
    # the default first and leave. Everything below only runs for a connector
    # that actually has a problem to solve.
    plain = _z_points(start, end, default, horizontal)
    blockers = [r for r in obstacles
                if any(_segment_hits_rect(plain[i], plain[i + 1], r)
                       for i in range(len(plain) - 1))]
    if not blockers:
        return default

    # Judge against the obstacles nearest the mid-line we would otherwise draw;
    # those are the ones sliding it can actually dodge.
    def axis_gap(rect: QRectF) -> float:
        near, far = ((rect.left(), rect.right()) if horizontal
                     else (rect.top(), rect.bottom()))
        return max(near - default, default - far, 0.0)

    if len(obstacles) > ORTHO_MAX_OBSTACLES:
        obstacles = heapq.nsmallest(ORTHO_MAX_OBSTACLES, obstacles, key=axis_gap)

    span = hi - lo
    candidates = [default] + [lo + span * f for f in ORTHO_MID_FRACTIONS]
    # A fixed ladder can step straight over a narrow gap between two boxes, so
    # also try the positions just clear of the edges of what is actually in the
    # way — a corridor, where one exists, is bounded by exactly those edges.
    for rect in blockers:
        near, far = ((rect.left(), rect.right()) if horizontal
                     else (rect.top(), rect.bottom()))
        candidates.append(near - ORTHO_MID_CLEARANCE)
        candidates.append(far + ORTHO_MID_CLEARANCE)

    inner_lo, inner_hi = (lo, hi) if lo <= hi else (hi, lo)
    candidates = [c for c in candidates if inner_lo <= c <= inner_hi]
    candidates.sort(key=lambda c: (abs(c - default), c))

    best, best_score = default, None
    for mid in candidates[:ORTHO_MAX_CANDIDATES]:
        score = _crossed(_z_points(start, end, mid, horizontal),
                         obstacles, best_score)
        if best_score is None or score < best_score:
            best, best_score = mid, score
            if score == 0:
                break
    return best


def _detour(start: QPointF, end: QPointF, horizontal: bool,
            obstacles: list[QRectF]) -> list[QPointF] | None:
    """A stair around the boxes between two facing ends, or None (#284).

    The route leaves its start, turns in the gap before the first box in its
    way, runs along a free column beside the boxes, turns in the gap after
    the last one and enters its end: five runs where a Z has three. A
    layered layout puts the turns in the gaps between layers and the column
    between two boxes of the layer it skips, the way one sketches it by hand.

    Only boxes between the two ends along the way they face can be in the
    way, so only those are looked at. The columns tried are those just clear
    of such a box's edges, nearest the straight line first; the first column
    whose route touches no box wins. None when there is none, and the caller
    keeps its Z, so a hard case stays as predictable as it was.
    """
    def main(p: QPointF) -> float:
        return p.x() if horizontal else p.y()

    def cross(p: QPointF) -> float:
        return p.y() if horizontal else p.x()

    def at(m: float, c: float) -> QPointF:
        return QPointF(m, c) if horizontal else QPointF(c, m)

    def extent(r: QRectF, along: bool) -> tuple[float, float]:
        if along == horizontal:
            return r.left(), r.right()
        return r.top(), r.bottom()

    s0, e0 = main(start), main(end)
    sc, ec = cross(start), cross(end)
    d = 1.0 if e0 > s0 else -1.0
    lo, hi = min(s0, e0), max(s0, e0)
    band = [r for r in obstacles
            if extent(r, True)[0] < hi and extent(r, True)[1] > lo]
    if not band:
        return None
    default = (sc + ec) / 2

    def cross_gap(r: QRectF) -> float:
        near, far = extent(r, False)
        return max(near - default, default - far, 0.0)

    if len(band) > ORTHO_MAX_OBSTACLES:
        band = heapq.nsmallest(ORTHO_MAX_OBSTACLES, band, key=cross_gap)

    def entry(r: QRectF) -> float:
        """Where the route meets *r* going from start to end."""
        a, b = extent(r, True)
        return a if d > 0 else b

    def exit_(r: QRectF) -> float:
        a, b = extent(r, True)
        return b if d > 0 else a

    def spanning(c0: float, c1: float) -> list[QRectF]:
        """The band's boxes a run across from *c0* to *c1* could touch."""
        a, b = min(c0, c1), max(c0, c1)
        return [r for r in band
                if extent(r, False)[0] <= b and extent(r, False)[1] >= a]

    columns: list[float] = []
    for r in band:
        near, far = extent(r, False)
        columns += [near - ORTHO_MID_CLEARANCE, far + ORTHO_MID_CLEARANCE]
    columns.sort(key=lambda c: (abs(c - default), c))

    for c in columns[:ORTHO_MAX_DETOURS]:
        first = spanning(sc, c) or band
        last = spanning(c, ec) or band
        # Turn half way into the gap between an end and the nearest box
        # the turn has to clear.
        near = min((entry(r) for r in first), key=lambda m: d * m)
        far = max((exit_(r) for r in last), key=lambda m: d * m)
        m1, m2 = (s0 + near) / 2, (far + e0) / 2
        if not (d * (m1 - s0) > 0.01 and d * (e0 - m2) > 0.01
                and d * (m2 - m1) >= 0):
            continue
        pts = _tidy([start, at(m1, sc), at(m1, c), at(m2, c),
                     at(m2, ec), end])
        if _crossed(pts, band, 1) == 0:
            return pts
    return None


def ortho_points(start: QPointF, start_side: str,
                 end: QPointF, end_side: str,
                 obstacles: list[QRectF] | None = None,
                 ends: tuple[QRectF, QRectF] | None = None,
                 mid: float | None = None) -> list[QPointF]:
    """Corner points of a right-angle route between two side anchors.

    Two parallel exits give a Z (three segments, turning at a mid-line in the
    gap); perpendicular exits give an L. The route is a pure function of the two
    anchors and ``obstacles`` — never of a previous route — so the same board
    always draws the same picture in the app and in a headless render.

    ``obstacles`` are rects the mid-line should avoid; the caller excludes the
    connector's own endpoints. Only the Z case has a free parameter to spend, so
    an L is unaffected. A Z whose ends face each other and that no mid-line
    clears steps around the boxes in its way instead (``_detour``, #284).

    ``ends`` — the rects of the two endpoints — marks a connector with pinned
    sides (#209). Its route must leave and enter along those sides, so where
    the plain stair would run back across its own box it is replaced by one
    that steps out first.

    ``mid`` is where a Z turns when that line is clear, in place of the middle
    of the gap: arrows leaving one side of a box each get their own (#306).
    """
    horiz_start = start_side in ("e", "w")
    horiz_end = end_side in ("e", "w")

    if horiz_start == horiz_end:
        near = _relevant(start, end, obstacles)
        mid = _best_mid(start, end, horiz_start, near, mid)
        pts = _z_points(start, end, mid, horiz_start)
        if (near and _crossed(pts, near, 1)
                and _along(start, end, start_side) > 0.01
                and _along(end, start, end_side) > 0.01):
            pts = _detour(start, end, horiz_start, obstacles) or pts
    elif horiz_start:
        pts = [start, QPointF(end.x(), start.y()), end]
    else:
        pts = [start, QPointF(start.x(), end.y()), end]

    pts = _tidy(pts)
    if ends is None or _keeps_to_sides(pts, start_side, end_side):
        return pts
    return _pinned_stair(start, start_side, end, end_side,
                         [*ends, *(obstacles or [])])


# How far apart the turn lines of two right-angle arrows leaving one side of a
# box sit (#306): wide enough to read as two runs, and two eased corners of
# ORTHO_RADIUS still clear each other.
ORTHO_TURN_SEP = 14.0


def _isotonic(values: list[float]) -> list[float]:
    """The non-decreasing sequence nearest ``values`` in least squares
    (pool adjacent violators)."""
    blocks: list[list[float]] = []            # [sum, count]
    for v in values:
        blocks.append([v, 1.0])
        while (len(blocks) > 1 and blocks[-2][0] / blocks[-2][1]
               > blocks[-1][0] / blocks[-1][1]):
            s, c = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += c
    out: list[float] = []
    for s, c in blocks:
        out += [s / c] * int(c)
    return out


def turn_lines(routes: list[tuple[QPointF, str, QPointF, str]]
               ) -> list[float | None]:
    """Where each right-angle arrow leaving one side of one box turns (#306).

    ``routes`` are ``(start, start_side, end, end_side)`` of the arrows that
    leave the same side of the same box. Two Z-bends that turn the same way
    from that side would turn at the same line and draw their runs on top of
    each other until they split. Each gets its own line instead, nested so
    they never cross: the arrow starting furthest out in the direction they
    turn turns nearest the box, and the others turn one step further out
    each. The lines stay as close as that allows to where each arrow would
    turn on its own — the middle of its gap — and inside its gap.

    Returns the turn line per route, or None for a route that keeps its own:
    an L, a straight run, one whose end lies behind the side, or one with no
    sibling turning its way.
    """
    out: list[float | None] = [None] * len(routes)
    if len(routes) < 2:
        return out
    side = routes[0][1]
    horizontal = side in ("e", "w")
    sgn = 1.0 if side in ("e", "s") else -1.0

    def main(p: QPointF) -> float:
        return p.x() if horizontal else p.y()

    def cross(p: QPointF) -> float:
        return p.y() if horizontal else p.x()

    ways: dict[float, list[tuple[int, float]]] = {}
    for i, (start, _s_side, end, e_side) in enumerate(routes):
        if (e_side in ("e", "w")) != horizontal:
            continue                          # an L turns at its end
        turn = cross(end) - cross(start)
        gap = (main(end) - main(start)) * sgn
        if abs(turn) < 0.5 or gap <= 0.0:
            continue
        ways.setdefault(1.0 if turn > 0 else -1.0, []).append((i, gap))

    for way, members in ways.items():
        if len(members) < 2:
            continue
        # Furthest out the way they turn first: that one turns nearest the box.
        members.sort(key=lambda m: (-way * cross(routes[m[0]][0]), m[0]))
        sep = min(ORTHO_TURN_SEP,
                  min(gap for _i, gap in members) / (len(members) + 1))
        depths = _isotonic([gap / 2 - k * sep
                            for k, (_i, gap) in enumerate(members)])
        for k, ((i, gap), depth) in enumerate(zip(members, depths)):
            margin = min(ORTHO_RADIUS, gap / 2)
            depth = max(margin, min(gap - margin, depth + k * sep))
            out[i] = main(routes[i][0]) + sgn * depth
    return out


def _tidy(pts: list[QPointF]) -> list[QPointF]:
    """Drop points that coincide, then points that don't actually turn: an
    aligned pair collapses a Z into one straight run, and a corner that isn't
    a corner would still get handed to the rounding pass. A point where the
    route doubles back is a turn and stays."""
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
        dot = ((cur.x() - prev.x()) * (nxt.x() - cur.x())
               + (cur.y() - prev.y()) * (nxt.y() - cur.y()))
        if abs(cross) > 0.01 or dot < 0:
            straightened.append(cur)
    if len(out) > 1:
        straightened.append(out[-1])
    return straightened


# How far a pinned connector steps straight out of its side before it turns,
# when the other end lies behind that side (#209) — enough for the turn to read
# as leaving the box, short enough to stay close to it.
PINNED_STUB = 18.0


def _along(a: QPointF, b: QPointF, side: str) -> float:
    """How far ``a``→``b`` travels along the outward normal of ``side``."""
    nx, ny = _NORMALS[side]
    return (b.x() - a.x()) * nx + (b.y() - a.y()) * ny


def _keeps_to_sides(pts: list[QPointF], start_side: str, end_side: str) -> bool:
    """Whether a route leaves out of its start side and enters into its end
    side, rather than running back across the box it starts or ends on."""
    return (len(pts) >= 2 and _along(pts[0], pts[1], start_side) > 0.01
            and _along(pts[-1], pts[-2], end_side) > 0.01)


def _stub_points(start: QPointF, start_side: str,
                 end: QPointF, end_side: str) -> tuple[QPointF, QPointF]:
    """The two points a pinned connector steps out to before it turns.

    Two ends pinned to the same side step out to the same line, past whichever
    end sits further out, so a U-turn comes back square instead of cutting the
    corner of the box that sticks out more.
    """
    sx, sy = _NORMALS[start_side]
    ex, ey = _NORMALS[end_side]
    p1 = QPointF(start.x() + sx * PINNED_STUB, start.y() + sy * PINNED_STUB)
    p2 = QPointF(end.x() + ex * PINNED_STUB, end.y() + ey * PINNED_STUB)
    if start_side == end_side:
        if start_side in ("e", "w"):
            far = max if start_side == "e" else min
            x = far(p1.x(), p2.x())
            p1, p2 = QPointF(x, p1.y()), QPointF(x, p2.y())
        else:
            far = max if start_side == "s" else min
            y = far(p1.y(), p2.y())
            p1, p2 = QPointF(p1.x(), y), QPointF(p2.x(), y)
    return p1, p2


def _reversals(pts: list[QPointF]) -> int:
    """How often a route doubles back on the segment it just drew."""
    return sum(
        1 for a, b, c in zip(pts, pts[1:], pts[2:])
        if ((b.x() - a.x()) * (c.x() - b.x())
            + (b.y() - a.y()) * (c.y() - b.y())) < 0)


def _pinned_stair(start: QPointF, start_side: str,
                  end: QPointF, end_side: str,
                  blockers: list[QRectF]) -> list[QPointF]:
    """A right-angle route that leaves and enters along pinned sides.

    Only used when the plain stair would run back across its own box — a
    U-turn, or an end pinned to the side facing away from the other. Each end
    steps out of its side, and the two stub points are joined by whichever of a
    few right-angle shapes crosses the fewest boxes, the endpoints' own boxes
    included; a tie keeps the shorter shape and then the listed order.
    """
    p1, p2 = _stub_points(start, start_side, end, end_side)
    mx, my = (p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2
    candidates = [
        [start, p1, QPointF(p1.x(), p2.y()), p2, end],
        [start, p1, QPointF(p2.x(), p1.y()), p2, end],
        [start, p1, QPointF(p1.x(), my), QPointF(p2.x(), my), p2, end],
        [start, p1, QPointF(mx, p1.y()), QPointF(mx, p2.y()), p2, end],
    ]
    best, best_key = None, None
    for pts in candidates:
        pts = _tidy(pts)
        key = (_reversals(pts), _crossed(pts, blockers), len(pts))
        if best_key is None or key < best_key:
            best, best_key = pts, key
    return best


def pinned_direct_points(start: QPointF, start_side: str,
                         end: QPointF, end_side: str) -> list[QPointF]:
    """The run of a direct connector between two pinned anchors (#209).

    Straight when it can leave and enter through the pinned sides; otherwise it
    steps out of each side first and runs straight between the two stub points,
    so a U-turn or a back-facing pin still reads as leaving that side.
    """
    if (_along(start, end, start_side) > 0.01
            and _along(end, start, end_side) > 0.01):
        return [start, end]
    p1, p2 = _stub_points(start, start_side, end, end_side)
    return _tidy([start, p1, p2, end])


def polyline_path(points: list[QPointF]) -> QPainterPath:
    """A path through ``points`` with sharp corners."""
    path = QPainterPath(points[0])
    for pt in points[1:]:
        path.lineTo(pt)
    return path


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
                end: QPointF, end_side: str,
                obstacles: list[QRectF] | None = None,
                ends: tuple[QRectF, QRectF] | None = None,
                mid: float | None = None) -> QPainterPath:
    """The connector body for a routing, as a path.

    ``obstacles`` lets a stair slide its mid-line clear of intervening boxes;
    the other routings have no free parameter to spend and ignore it. ``ends``
    marks a connector with pinned sides (see ``ortho_points``); a spline already
    leaves along each side's normal and needs nothing more. ``mid`` is a
    stair's turn line from ``turn_lines``.
    """
    if routing == "spline":
        return spline_path(start, start_side, end, end_side)
    if routing == "ortho":
        return _rounded_polyline(
            ortho_points(start, start_side, end, end_side, obstacles, ends,
                         mid),
            ORTHO_RADIUS)
    path = QPainterPath(start)
    path.lineTo(end)
    return path


def label_anchor(start: QPointF, end: QPointF,
                 path: QPainterPath | None = None) -> QPointF:
    """Where an arrow's label is centred, before its ``@dx,dy`` offset.

    The one place this is decided: the canvas draws the label here, and the
    inline label editor and the arrow-mode badge open here, so editing a
    label never starts away from it. A shaped connector (routed, bowed,
    pinned) puts it on the path (``label_point``); a straight one at the
    middle between its two ends."""
    if path is not None:
        return label_point(path)
    return QPointF((start.x() + end.x()) / 2, (start.y() + end.y()) / 2)


def label_point(path: QPainterPath) -> QPointF:
    """Where a connector's label sits: the middle of its longest straight run.

    The middle of the whole path can fall on a short jog of a stair, where
    the label hides the turn and reads as belonging to neither run (#260). A
    tie goes to the run nearest the path's middle; a path with no straight
    run (a spline, a bow) keeps the label at its middle."""
    middle = path.pointAtPercent(0.5)
    best, best_len, best_off = None, 0.0, 0.0
    prev = None
    for i in range(path.elementCount()):
        el = path.elementAt(i)
        pt = QPointF(el.x, el.y)
        if el.type == QPainterPath.ElementType.LineToElement and prev is not None:
            length = math.hypot(pt.x() - prev.x(), pt.y() - prev.y())
            mid = QPointF((prev.x() + pt.x()) / 2, (prev.y() + pt.y()) / 2)
            off = math.hypot(mid.x() - middle.x(), mid.y() - middle.y())
            if (length > best_len + 0.5
                    or (abs(length - best_len) <= 0.5 and off < best_off)):
                best, best_len, best_off = mid, length, off
        if el.type in (QPainterPath.ElementType.MoveToElement,
                       QPainterPath.ElementType.LineToElement):
            prev = pt
        elif el.type == QPainterPath.ElementType.CurveToElement:
            prev = None               # control points follow; resynced below
        else:
            prev = pt                 # last data point of a curve is its end
    return best if best is not None else middle


# ── Label placement in free space (#303) ───────────────────────────
#
# A label centred on its anchor can land on a box the connector passes, on its
# own end box when the connector is short, or on another connector's label
# where two cross or fan out. ``place_label`` keeps the anchor when the label
# is clear there, and otherwise moves it to the nearest free spot along its
# connector: on the line where there is room, beside it where there is not.

# The plate drawn behind a label reaches this far past its text on each side.
# The one definition: ``LabelItem`` paints its plate with it, the line is
# clipped around it, and placement and ``grafli diagnose`` size plates by it.
LABEL_PAD = 4.0
# How finely a label slides along its connector looking for room.
LABEL_SLIDE_STEP = 6.0
# The space between the line and a label set beside it.
LABEL_BESIDE_GAP = 3.0


def label_plate(centre: QPointF, w: float, h: float) -> QRectF:
    """The plate of a ``w`` x ``h`` label centred on ``centre``."""
    return QRectF(centre.x() - w / 2 - LABEL_PAD, centre.y() - h / 2 - LABEL_PAD,
                  w + 2 * LABEL_PAD, h + 2 * LABEL_PAD)


def place_label(path: QPainterPath, w: float, h: float, anchor: QPointF,
                blocked: list[QRectF]) -> QPointF:
    """Where a ``w`` x ``h`` label riding ``path`` is centred: the free spot
    nearest ``anchor``.

    Free means its plate touches none of the ``blocked`` rects — the boxes it
    must stay off and the plates of the labels already placed. The anchor
    itself wins when it is free, so a board with room keeps every label where
    it was. Otherwise the label slides along the path, the free spot nearest
    the anchor winning. Only a path with no room on it sets the label beside
    the line: a label on its line interrupts it and reads as that line's,
    one beside it can sit as near another line where two meet. With no free
    spot anywhere the anchor stays: the label still names its connector, and
    ``grafli diagnose`` reports it.
    """
    def free(centre: QPointF) -> bool:
        plate = label_plate(centre, w, h)
        return not any(plate.intersects(r) for r in blocked)

    if free(anchor):
        return anchor
    length = path.length()
    if length < 1:
        return anchor
    reach = max(w, h) + 2 * (LABEL_PAD + LABEL_BESIDE_GAP)
    zone = path.boundingRect().adjusted(-reach, -reach, reach, reach)
    blocked = [r for r in blocked if r.intersects(zone)]

    steps = max(1, int(length // LABEL_SLIDE_STEP))
    samples = []
    for i in range(steps + 1):
        pct = path.percentAtLength(length * i / steps)
        samples.append((length * i / steps, pct, path.pointAtPercent(pct)))
    here = min(samples, key=lambda s: math.hypot(s[2].x() - anchor.x(),
                                                 s[2].y() - anchor.y()))[0]

    candidates = []
    for at, pct, pt in samples:
        slide = abs(at - here)
        candidates.append((0, slide, pt))
        # Qt's angle runs counter-clockwise from 3 o'clock on a y-down canvas;
        # the normal below points up, or right on a vertical run, first.
        rad = math.radians(path.angleAtPercent(pct))
        nx, ny = math.sin(rad), math.cos(rad)
        if ny > 1e-9 or (abs(ny) <= 1e-9 and nx < 0):
            nx, ny = -nx, -ny
        # The plate's half-extent across the line, so all of it clears it.
        off = abs(nx) * w / 2 + abs(ny) * h / 2 + LABEL_PAD + LABEL_BESIDE_GAP
        for side, sign in ((1, 1.0), (2, -1.0)):
            candidates.append((side, slide,
                               QPointF(pt.x() + sign * nx * off,
                                       pt.y() + sign * ny * off)))
    # On the line before beside it; nearest first; above (or right) first.
    candidates.sort(key=lambda c: (c[0] > 0, c[1], c[0]))
    for _side, _slide, centre in candidates:
        if free(centre):
            return centre
    return anchor


def label_ground(board, from_id: str, to_id: str) -> set[str]:
    """The containers a connector's label may sit on: every box enclosing
    either end. Its label rides inside them like the connector does; any
    other box, note or image — its own two ends included — it stays off."""
    out: set[str] = set()
    for elem_id in (from_id, to_id):
        elem = (board.box_by_id(elem_id) or board.note_by_id(elem_id)
                or next((im for im in board.images if im.id == elem_id), None))
        parent = getattr(elem, "parent", "") if elem is not None else ""
        while parent and parent not in out:
            out.add(parent)
            box = board.box_by_id(parent)
            parent = box.parent if box is not None else ""
    return out


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


# ── Anchor spreading for unrouted connectors (experiment) ──────────
#
# A direct connector attaches where the centre-to-centre ray leaves the box.
# That is the right *natural* position, but several connectors to targets in
# the same general direction all land within a few pixels of each other, so a
# hub node ends up with a knot of arrowheads at one corner. These helpers keep
# the natural position and only push neighbours apart when they crowd — a
# board with room to breathe is left exactly as it was.

# Minimum gap between two connectors on the same box side, in scene units.
ANCHOR_MIN_SEP = 26.0
# How much of a routed connector's natural offset from the side centre it keeps.
# A direct connector's anchor *is* its ray, so a near-corner exit reads fine —
# the line simply continues. A routed one leaves perpendicular and then turns,
# so the same anchor leaves it curving out of a cramped corner. Keeping a
# fraction of the offset preserves the ordering information (a connector whose
# target lies right still sits right of one whose target lies left) while
# holding the anchor in the roomy middle of the side.
ROUTED_CENTRE_BIAS = 0.34
# Anchors stay off the very corners, which read as ambiguous.
ANCHOR_MARGIN = 0.06


def relax_positions(desired: list[float], min_sep: float,
                    order_key: list | None = None) -> list[float]:
    """Push crowded anchors apart along a side, preserving their order.

    Order is what keeps connectors from swapping places and crossing each
    other; separation is what stops them stacking. A set that is already
    comfortably spread comes back untouched, so this only changes the boards
    that actually had a knot.

    ``order_key`` ranks the anchors when that differs from where they want to
    sit — a routed anchor is pulled toward the middle of its side, so ranking by
    the pulled value could drop it below a neighbour it should stay clear of and
    invert the pair into a crossing. Rank by where the connector's own target
    puts it; place by where it wants to be.
    """
    n = len(desired)
    if n < 2:
        return list(desired)
    if order_key is None:
        order_key = desired
    lo, hi = ANCHOR_MARGIN, 1.0 - ANCHOR_MARGIN
    min_sep = min(min_sep, (hi - lo) / (n - 1))

    order = sorted(range(n), key=lambda i: order_key[i])
    vals = [max(lo, min(hi, desired[i])) for i in order]
    for i in range(1, n):                       # push right
        vals[i] = max(vals[i], vals[i - 1] + min_sep)
    if vals[-1] > hi:                           # ran off the end — push back
        vals[-1] = hi
        for i in range(n - 2, -1, -1):
            vals[i] = min(vals[i], vals[i + 1] - min_sep)
    if vals[0] < lo:                            # no room either way — share it
        step = (hi - lo) / (n - 1)
        vals = [lo + step * i for i in range(n)]

    out = [0.0] * n
    for slot, i in enumerate(order):
        out[i] = vals[slot]
    return out


# ── Self-connectors and parallel edges ─────────────────────────────
#
# Both are cases where a connector's own two endpoints don't determine its
# shape. A self-connector has one endpoint, so there is no centre-to-centre ray
# to follow at all (#139); parallel connectors between one pair have *identical*
# endpoints, so nothing local to a connector tells it apart from its sibling
# (#140). Each therefore takes one extra input — which corner is free, which
# slot in the fan — and stays a pure function of that plus the element rects.

# The adjacent side pairs a self-connector can loop over, in the order they are
# tried. A pair carrying no other connector wins; a tie keeps this order, so the
# app and a headless render pick the same corner.
SELF_LOOP_SIDES = (("n", "e"), ("e", "s"), ("s", "w"), ("w", "n"))
# How close to the shared corner each end of the loop sits, along its side.
# Close enough that the loop reads as a loop rather than as a connector
# wandering around the element, clear enough that it isn't a kink in the corner.
SELF_LOOP_T = 0.72
# How far the loop bulges past the corner, as a fraction of the element's
# smaller side, clamped so a tiny note still gets a visible loop and a large
# container doesn't get a balloon.
SELF_LOOP_REACH = 0.62
SELF_LOOP_REACH_MIN = 40.0
SELF_LOOP_REACH_MAX = 120.0

# How far apart a fan pushes the middles of two connectors between the same
# pair. The anchor pass has already separated their ends, so the fan only has to
# open up the run between them — where the labels sit. Modest on purpose: a wide
# bow reads as a detour rather than as a second connector.
PARALLEL_FAN_STEP = 22.0
PARALLEL_FAN_MAX_SPAN = 110.0

# Which way "further along the side" points. Anchors are spread by increasing
# ``t`` (see relax_positions), so a fan measured against this direction puts
# every connector's bow on the same side as its own anchor — bowing the other
# way would send it across the sibling it is being separated from.
_SIDE_ALONG = {"n": (1.0, 0.0), "s": (1.0, 0.0), "e": (0.0, 1.0), "w": (0.0, 1.0)}


def pick_self_loop_sides(load: dict[str, int]) -> tuple[str, str]:
    """The adjacent side pair a self-connector loops over.

    ``load`` counts the connectors already attached to each side, so the loop
    settles on the emptiest corner of the element instead of landing on top of
    its neighbours.
    """
    return min(SELF_LOOP_SIDES,
               key=lambda pair: load.get(pair[0], 0) + load.get(pair[1], 0))


def pinned_self_loop_sides(out_pin: str, in_pin: str,
                           load: dict[str, int]) -> tuple[str, str]:
    """The sides a self-connector with one or both sides pinned loops over.

    A pinned side is kept; an unpinned one takes the adjacent side that the
    loop pairs it with in ``SELF_LOOP_SIDES``, as the emptiest corner would.
    """
    if out_pin and in_pin:
        return out_pin, in_pin
    if out_pin:
        return next(p for p in SELF_LOOP_SIDES if p[0] == out_pin)
    return next(p for p in SELF_LOOP_SIDES if p[1] == in_pin)


def self_loop_ts(out_side: str, in_side: str) -> tuple[float, float]:
    """Where the two ends of a self-loop sit on their sides, as 0..1.

    Both sit near the corner the two sides share; which end of a side that is
    depends on the corner, since ``t`` always runs left-to-right or top-to-bottom.
    """
    if out_side == in_side:                  # a pinned loop on one side
        return 1.0 - SELF_LOOP_T, SELF_LOOP_T
    corner = {out_side, in_side}
    if corner in ({"n", "s"}, {"e", "w"}):
        return 0.5, 0.5                      # pinned to opposite sides

    def near(side: str) -> float:
        at_high_end = ("e" in corner) if side in ("n", "s") else ("s" in corner)
        return SELF_LOOP_T if at_high_end else 1.0 - SELF_LOOP_T

    return near(out_side), near(in_side)


def self_loop_path(rect: tuple, start: QPointF, start_side: str,
                   end: QPointF, end_side: str) -> QPainterPath:
    """A loop leaving one side of ``rect`` and re-entering an adjacent one.

    Same construction as a spline — leave along each side's normal — with the
    bulge derived from the element's own size rather than from the distance
    between the two ends, which on a loop is only ever a corner apart.
    """
    _x, _y, w, h = rect
    reach = max(SELF_LOOP_REACH_MIN,
                min(SELF_LOOP_REACH_MAX, min(w, h) * SELF_LOOP_REACH))
    sx, sy = _NORMALS[start_side]
    ex, ey = _NORMALS[end_side]
    path = QPainterPath(start)
    path.cubicTo(
        QPointF(start.x() + sx * reach, start.y() + sy * reach),
        QPointF(end.x() + ex * reach, end.y() + ey * reach),
        end,
    )
    return path


def fan_offsets(n: int) -> list[float]:
    """Lateral offsets for ``n`` connectors between the same pair.

    Symmetric about the straight run, so a fan grows outward from where the
    single connector would have been. The span is capped, so a pair with many
    connectors tightens rather than sweeping across the board.
    """
    if n < 2:
        return [0.0] * n
    step = min(PARALLEL_FAN_STEP, PARALLEL_FAN_MAX_SPAN / (n - 1))
    return [(i - (n - 1) / 2) * step for i in range(n)]


def fan_normal(start: QPointF, end: QPointF,
               start_side: str) -> tuple[float, float]:
    """Unit vector a positive fan offset bows toward."""
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0, 0.0
    nx, ny = -dy / length, dx / length
    ax, ay = _SIDE_ALONG[start_side]
    along = nx * ax + ny * ay
    # A connector running along its own side has no ordering to agree with, so
    # break the tie on the vector itself and keep the choice deterministic.
    if along < 0 or (along == 0 and (nx < 0 or (nx == 0 and ny < 0))):
        nx, ny = -nx, -ny
    return nx, ny


def bowed_path(start: QPointF, end: QPointF, start_side: str,
               offset: float) -> QPainterPath:
    """The run between two anchors, bowed sideways by ``offset`` at its middle.

    A zero offset gives back the straight line, so the only boards this touches
    are the ones that actually have connectors to separate.
    """
    path = QPainterPath(start)
    if abs(offset) < 1e-9:
        path.lineTo(end)
        return path
    nx, ny = fan_normal(start, end, start_side)
    # A quadratic passes through (P0 + 2C + P1) / 4 at its middle, so the
    # control point carries twice the offset the apex should show.
    path.quadTo(
        QPointF((start.x() + end.x()) / 2 + nx * offset * 2,
                (start.y() + end.y()) / 2 + ny * offset * 2),
        end,
    )
    return path

