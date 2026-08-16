"""Where a direct connector attaches to its two elements (#156).

The rules are pinned as *rules* — an endpoint sits in the central band of the
side that faces the other element, an already-central pair keeps the plain
centre-to-centre line, a sliver overlap gets no straight segment — rather than
as coordinates, so retuning the band doesn't rewrite them.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication, QGraphicsPolygonItem

from grafli import arrows
from grafli.format import parse
from grafli.items import ArrowLineItem
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    return view


def _points(view, label: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for gfx in view._arrow_items:
        arrow = gfx.data(0)
        if not isinstance(gfx, ArrowLineItem) or arrow is None:
            continue
        if arrow.label != label:
            continue
        for poly in gfx.path().toSubpathPolygons():
            out.extend((round(p.x(), 3), round(p.y(), 3)) for p in poly)
    return out


def _ends(view, label: str) -> tuple[QPointF, QPointF]:
    pts = _points(view, label)
    return QPointF(*pts[0]), QPointF(*pts[-1])


def _band(rect: tuple, pt: QPointF) -> float:
    """Where ``pt`` sits along the side it lies on, as 0..1."""
    return arrows.t_of_point(rect, arrows.side_of_point(rect, pt), pt)


def _is_central(rect: tuple, pt: QPointF) -> bool:
    return (arrows.CENTRAL_BAND_LO - 1e-6
            <= _band(rect, pt)
            <= arrows.CENTRAL_BAND_HI + 1e-6)


# The reported board: b and c graze each other's x range, c and d sit
# diagonally with the horizontal distance dominating.
_REPRO = """#!grafli v1
@ box a "A" 0,0 320x160
@ box b "B" 1240,-60 320x160
@ box c "C" 990,690 320x160
@ box d "D" 120,1060 320x160
@ arrow b -> c "bc"
@ arrow c -> d "cd"
"""

_B = (1240.0, -60.0, 320.0, 160.0)
_C = (990.0, 690.0, 320.0, 160.0)
_D = (120.0, 1060.0, 320.0, 160.0)


# ── The corner zone ────────────────────────────────────────────────

def test_an_endpoint_never_lands_in_a_corner():
    """The rule: whatever the direction, both ends sit in the central band."""
    rect = (0.0, 0.0, 320.0, 160.0)
    for dx in range(-1200, 1201, 60):
        for dy in range(-1200, 1201, 60):
            other = (rect[0] + dx, rect[1] + dy, 200.0, 120.0)
            if abs(dx) < 340 and abs(dy) < 180:
                continue                       # overlapping, not a connection
            start, end = arrows.endpoint_pair(rect, other, allow_aligned=False)
            assert _is_central(rect, start), (dx, dy, start)
            assert _is_central(other, end), (dx, dy, end)


def test_a_near_diagonal_leaves_the_side_that_faces_the_other_element():
    """The reported c -> d case: dominantly horizontal, so left side to right
    side — not the corner where the ray happens to cross first."""
    start, end = arrows.endpoint_pair(_C, _D)
    assert arrows.side_of_point(_C, start) == "w"
    assert arrows.side_of_point(_D, end) == "e"
    assert _is_central(_C, start) and _is_central(_D, end)


def test_facing_sides_answer_the_same_question_from_both_ends():
    """A connector has one relation, so its two ends must agree on the axis."""
    opposite = {"n": "s", "s": "n", "e": "w", "w": "e"}
    for rect in ((0.0, 0.0, 320.0, 160.0), (0.0, 0.0, 90.0, 400.0)):
        for dx in (-900, -200, 0, 200, 900):
            for dy in (-900, -200, 0, 200, 900):
                other = (rect[0] + dx, rect[1] + dy, 240.0, 100.0)
                near, far = arrows.facing_sides(rect, other)
                assert opposite[near] == far
                assert arrows.facing_sides(other, rect) == (far, near)


def test_a_sideways_offset_does_not_make_a_stacked_pair_horizontal():
    """Two boxes stacked with an offset larger than nothing still face each
    other top-to-bottom; the centre delta alone would say otherwise."""
    upper = (0.0, 0.0, 320.0, 160.0)
    lower = (200.0, 190.0, 320.0, 160.0)
    assert arrows.facing_sides(upper, lower) == ("s", "n")


# ── What must not change ───────────────────────────────────────────

def test_a_centred_pair_keeps_the_plain_centre_to_centre_line():
    """The no-op guarantee: a ray already leaving centrally is left alone."""
    f_rect = (0.0, 0.0, 200.0, 100.0)
    t_rect = (600.0, 60.0, 200.0, 100.0)
    start, end = arrows.endpoint_pair(f_rect, t_rect, allow_aligned=False)
    f_mid = QPointF(f_rect[0] + 100, f_rect[1] + 50)
    t_mid = QPointF(t_rect[0] + 100, t_rect[1] + 50)
    assert start == arrows._rect_edge_point(*f_rect, t_mid)
    assert end == arrows._rect_edge_point(*t_rect, f_mid)


def test_an_aligned_pair_still_gets_the_straight_segment():
    """Deliberate alignment — the shared range covers both centres — keeps the
    straight run that makes a row or a column read as one."""
    view = _view('#!grafli v2\n@ box a "A" 0,0 200x100\n'
                 '@ box b "B" 600,0 200x100\n@ arrow a -> b\n')
    assert _points(view, "") == [(200.0, 50.0), (600.0, 50.0)]


def test_a_sliver_overlap_falls_back_to_the_slanted_line():
    """The reported b -> c case: an overlap that covers neither centre is not
    an alignment, so nothing is squeezed into it."""
    assert arrows._aligned_edge_points(_B, _C) is None
    start, end = arrows.endpoint_pair(_B, _C)
    assert abs(start.x() - end.x()) > 1.0        # slanted, not vertical
    assert _is_central(_B, start) and _is_central(_C, end)


def test_an_overlap_covering_one_centre_is_an_alignment():
    """Where the criterion sits: one centre inside the shared range is enough,
    which is what a reader takes for a deliberate column."""
    upper = (0.0, 0.0, 320.0, 160.0)
    lower = (100.0, 400.0, 320.0, 160.0)
    aligned = arrows._aligned_edge_points(upper, lower)
    assert aligned is not None
    start, end = aligned
    assert start.x() == end.x()


# ── On the board ───────────────────────────────────────────────────

def test_the_reported_board_draws_both_connectors_clear_of_the_corners():
    view = _view(_REPRO)
    bc_start, bc_end = _ends(view, "bc")
    assert abs(bc_start.x() - bc_end.x()) > 1.0
    assert _is_central(_B, bc_start) and _is_central(_C, bc_end)
    cd_start, cd_end = _ends(view, "cd")
    assert arrows.side_of_point(_C, cd_start) == "w"
    assert arrows.side_of_point(_D, cd_end) == "e"


def test_the_arrowhead_follows_the_endpoint_it_was_moved_to():
    """The head comes off the path, so a corrected end takes it along."""
    view = _view(_REPRO)
    _start, end = _ends(view, "cd")
    tips = [gfx.polygon()[0] for gfx in view._arrow_items
            if isinstance(gfx, QGraphicsPolygonItem)
            and getattr(gfx.data(0), "label", None) == "cd"]
    assert len(tips) == 1
    assert abs(tips[0].x() - end.x()) < 0.01
    assert abs(tips[0].y() - end.y()) < 0.01


def test_a_routed_connector_inherits_the_corrected_side():
    """Routed anchors derive their side from the natural endpoint, so switching
    a connector to a routing must not send it back to the corner."""
    view = _view(_REPRO.replace('@ arrow c -> d "cd"',
                                '@ arrow c -> d "cd" !spline'))
    anchors = view._connector_anchors(
        [(a.from_id, a.to_id, a.head_to, a.head_from, a, None)
         for a in view.board.arrows])
    idx = next(i for i, a in enumerate(view.board.arrows) if a.label == "cd")
    _s, s_side, _e, e_side, _moved = anchors[idx]
    assert (s_side, e_side) == ("w", "e")


def test_notes_and_images_get_the_same_placement():
    """Every endpoint type resolves through one rect-based geometry."""
    src = ("#!grafli v2\n"
           '@ box b "B" 990,690 320x160\n'
           '@ note n 120,1060 "a note"\n'
           '@ image i "missing.png" 120,1400 320x160\n'
           '@ arrow b -> n "to note"\n'
           '@ arrow b -> i "to image"\n')
    view = _view(src)
    b_rect = (990.0, 690.0, 320.0, 160.0)
    for label, elem_id in (("to note", "n"), ("to image", "i")):
        start, end = _ends(view, label)
        elem = (view.board.note_by_id(elem_id)
                or view.board.image_by_id(elem_id))
        assert _is_central(b_rect, start), label
        assert _is_central(view._elem_rect(elem), end), label


def test_placement_is_pure_geometry():
    """Same rects, same answer — the app and a headless render must agree."""
    once = arrows.endpoint_pair(_C, _D)
    twice = arrows.endpoint_pair(_C, _D)
    assert once == twice
