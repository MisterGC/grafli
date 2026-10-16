"""`!dot` (#210): a connector's headed ends draw a filled dot instead of an
arrowhead, for direct, spline and stair routing, in `grafli render` and the
PDF export. Which ends carry one is still the operator (`->`, `<-`, `<->`).
Connectors without the flag draw exactly as before.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QGraphicsPolygonItem

from grafli.format import parse, serialize
from grafli.items import ArrowLineItem
from grafli.view import GrafliView, Mode

ROUTINGS = ("", " !spline", " !ortho")
PAIR = ('#!grafli v4\n'
        '@ box a "A" 0,0 200x100\n'
        '@ box b "B" 600,300 200x100\n')


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str) -> GrafliView:
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _ends(view: GrafliView) -> list[QGraphicsPolygonItem]:
    return [g for g in view._arrow_items if isinstance(g, QGraphicsPolygonItem)]


def _is_dot(item: QGraphicsPolygonItem) -> bool:
    """A dot is a ring of points all one radius from their centre; an
    arrowhead is a closed triangle."""
    pts = list(item.polygon())
    if len(pts) < 8:
        return False
    c = item.polygon().boundingRect().center()
    radii = [math.hypot(p.x() - c.x(), p.y() - c.y()) for p in pts]
    return max(radii) - min(radii) < 0.01


def _centre(item: QGraphicsPolygonItem) -> QPointF:
    return item.polygon().boundingRect().center()


def _polyline(view: GrafliView) -> list[QPointF]:
    lines = [g for g in view._arrow_items if isinstance(g, ArrowLineItem)]
    assert len(lines) == 1
    return [p for poly in lines[0].path().toSubpathPolygons()
            for p in list(poly)]


def _close(p: QPointF, q: QPointF) -> bool:
    return abs(p.x() - q.x()) < 0.01 and abs(p.y() - q.y()) < 0.01


# ── Which ends get a dot ──────────────────────────────────────────

@pytest.mark.parametrize("routing", ROUTINGS)
def test_a_dot_arrow_ends_in_a_dot_on_its_head_end(routing):
    view = _view(PAIR + f'@ arrow a -> b{routing} !dot\n')
    ends = _ends(view)
    assert len(ends) == 1 and _is_dot(ends[0])
    assert _close(_centre(ends[0]), _polyline(view)[-1])


@pytest.mark.parametrize("routing", ROUTINGS)
def test_both_ends_get_a_dot_on_a_two_headed_arrow(routing):
    view = _view(PAIR + f'@ arrow a <-> b{routing} !dot\n')
    ends = _ends(view)
    assert len(ends) == 2 and all(_is_dot(e) for e in ends)
    pts = _polyline(view)
    centres = [_centre(e) for e in ends]
    assert any(_close(c, pts[0]) for c in centres)
    assert any(_close(c, pts[-1]) for c in centres)


def test_from_end_dot_and_headless_line():
    view = _view(PAIR + '@ arrow a <- b !dot\n')
    ends = _ends(view)
    assert len(ends) == 1 and _is_dot(ends[0])
    assert _close(_centre(ends[0]), _polyline(view)[0])
    assert _ends(_view(PAIR + '@ arrow a -- b !dot\n')) == []


def test_a_plain_arrow_keeps_its_arrowhead():
    ends = _ends(_view(PAIR + '@ arrow a -> b\n'))
    assert len(ends) == 1 and not _is_dot(ends[0])


def test_a_thick_dot_is_wider_than_its_line():
    view = _view(PAIR + '@ arrow a -> b !thick !dot\n')
    line = next(g for g in view._arrow_items if isinstance(g, ArrowLineItem))
    dot = _ends(view)[0]
    assert dot.polygon().boundingRect().width() > line.pen().widthF()


def test_a_dot_end_selects_its_arrow():
    view = _view(PAIR + '@ arrow a -> b !dot\n')
    assert _ends(view)[0].data(0) is view.board.arrows[0]


def test_a_dot_pair_merges_but_a_mixed_pair_does_not():
    both = _view(PAIR + '@ arrow a -> b !dot\n@ arrow b -> a !dot\n')
    assert len([g for g in both._arrow_items
                if isinstance(g, ArrowLineItem)]) == 1
    assert len(_ends(both)) == 2 and all(_is_dot(e) for e in _ends(both))
    mixed = _view(PAIR + '@ arrow a -> b !dot\n@ arrow b -> a\n')
    assert len([g for g in mixed._arrow_items
                if isinstance(g, ArrowLineItem)]) == 2
    assert sorted(_is_dot(e) for e in _ends(mixed)) == [False, True]


# ── Render and export ─────────────────────────────────────────────

def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_dots_differently_from_heads(tmp_path: Path):
    _app()
    dot = _render(tmp_path, "dot", PAIR + '@ arrow a <-> b !dot\n')
    head = _render(tmp_path, "head", PAIR.replace("v4", "v1")
                   + '@ arrow a <-> b\n')
    assert dot.size() == head.size()
    assert dot != head


def test_a_plain_arrow_renders_the_same_next_to_a_cleared_dot(tmp_path: Path):
    """Setting `!dot` and clearing it again leaves the render unchanged: the
    arrowhead path is the one every board already draws."""
    _app()
    text = PAIR.replace("v4", "v1") + '@ arrow a -> b !ortho\n'
    view = _view(text)
    before = view._render_png_image(scale=1)
    view.board.arrows[0].head_shape = "dot"
    view._redraw_arrows()
    assert view._render_png_image(scale=1) != before
    view.board.arrows[0].head_shape = ""
    view._redraw_arrows()
    assert view._render_png_image(scale=1) == before


TOUR = ('@ bookmark bm "A" @a,b\n'
        '@ flow tour "Tour" bm\n')


def _stop_raster(view, board, out: Path) -> QImage:
    """The board raster the PDF export paints for the flow's one stop."""
    from grafli.pdfexport import export_flow_to_pdf
    shots: list[QImage] = []
    scene = view._scene
    original = scene.render

    def capture(painter, target, source, *args):
        original(painter, target, source, *args)
        shots.append(QImage(painter.device()))

    scene.render = capture
    try:
        export_flow_to_pdf(view, board.flow_by_id("tour"), out)
    finally:
        del scene.render
    assert out.read_bytes().startswith(b"%PDF")
    assert len(shots) == 1
    return shots[0]


def test_the_pdf_export_draws_the_dots(tmp_path: Path):
    text = PAIR + '@ arrow a <-> b !dot\n' + TOUR
    dot = _stop_raster(_view(text), parse(text), tmp_path / "dot.pdf")
    plain_text = text.replace(" !dot", "").replace("v4", "v2")
    head = _stop_raster(_view(plain_text), parse(plain_text),
                        tmp_path / "head.pdf")
    assert dot.size() == head.size()
    assert dot != head


# ── Style mode `s` `e` ─────────────────────────────────────────────

def _overlay_view(src: str) -> GrafliView:
    view = _view("#!grafli v1\n" + src)
    view.resize(900, 600)
    view._mode = Mode.SELECT
    view._select_arrow(view.board.arrows[0])
    return view


def _press(view, *keys):
    from PySide6.QtTest import QTest
    for key in keys:
        QTest.keyClick(view, key)


def _row(view, label: str) -> int:
    return next(i for i, a in enumerate(view._elem_overlay_axes)
                if a["label"] == label)


BOXES = ('@ box a "A" 0,0 200x100\n'
         '@ box b "B" 600,300 200x100\n')


def test_s_e_offers_an_ends_row():
    view = _overlay_view(BOXES + '@ arrow a -> b\n')
    _press(view, Qt.Key.Key_S, Qt.Key.Key_E)
    assert view._elem_overlay_active
    axis = view._elem_overlay_axes[_row(view, "Ends")]
    assert axis["options"] == [("Arrow", ""), ("Dot", "dot")]
    assert axis["get"]() == ""


def test_s_e_toggles_dot_previews_and_saves_v4():
    view = _overlay_view(BOXES + '@ arrow a <-> b\n')
    _press(view, Qt.Key.Key_S, Qt.Key.Key_E)
    view._elem_overlay_row = _row(view, "Ends")
    _press(view, Qt.Key.Key_L)                        # Arrow -> Dot
    assert all(_is_dot(e) for e in _ends(view))       # live preview
    _press(view, Qt.Key.Key_Return)
    assert view.board.arrows[0].head_shape == "dot"
    out = serialize(view.board)
    assert out.startswith("#!grafli v4\n")
    assert "@ arrow a <-> b !dot" in out
    view._open_element_overlay()
    view._elem_overlay_row = _row(view, "Ends")
    view._elem_overlay_cycle(-1)                      # Dot -> Arrow
    view._commit_element_overlay()
    assert view.board.arrows[0].head_shape == ""
    assert not any(_is_dot(e) for e in _ends(view))


def test_ends_cancel_reverts_and_commit_is_undoable():
    view = _overlay_view(BOXES + '@ arrow a -> b\n')
    view._open_element_overlay()
    view._elem_overlay_row = _row(view, "Ends")
    view._elem_overlay_cycle(1)
    assert view.board.arrows[0].head_shape == "dot"
    view._cancel_element_overlay()
    assert view.board.arrows[0].head_shape == ""
    assert not any(_is_dot(e) for e in _ends(view))
    before = len(view._undo_stack)
    view._open_element_overlay()
    view._elem_overlay_row = _row(view, "Ends")
    view._elem_overlay_cycle(1)
    view._commit_element_overlay()
    assert len(view._undo_stack) == before + 1
    view._undo()
    assert view.board.arrows[0].head_shape == ""
    assert serialize(view.board).startswith("#!grafli v1\n")
