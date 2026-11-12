"""#283: an arrow draws over the containers it ends in, title strip
included, and behind the ones it only passes."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse
from grafli.items import ArrowLineItem, LabelItem

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _view(text: str):
    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _arrow_items(view, src: str, dst: str):
    items = [g for g in view._arrow_items
             if not isinstance(g, LabelItem)
             and getattr(g.data(0), "from_id", None) == src
             and getattr(g.data(0), "to_id", None) == dst]
    assert items, f"no drawn arrow {src} -> {dst}"
    return items


def _z(view, src: str, dst: str) -> float:
    zs = {g.zValue() for g in _arrow_items(view, src, dst)}
    assert len(zs) == 1, "an arrow's line and heads share one place"
    return zs.pop()


def _container(view, cid: str) -> tuple[float, float]:
    item = view._box_items[cid]
    return item.zValue(), item._label.zValue()


NESTED = ('#!grafli v4\n'
          '@ box outer "Outer" 0,0 800x400\n'
          '@ box inner "Inner" 20,40 400x300 >outer\n'
          '@ box leaf "Leaf" 60,120 160x80 >inner\n'
          '@ box side "Side" 500,120 160x80 >outer\n'
          '@ box wall "Wall" 0,500 800x200\n'
          '@ box wall_in "Wall in" 20,540 300x120 >wall\n'
          '@ box a "A" 300,800 160x80\n'
          '@ box b "B" 300,-300 160x80\n'
          '@ box c "C" -400,600 160x80\n'
          '@ box d "D" 1000,600 160x80\n'
          '@ arrow b -> leaf "in"\n'
          '@ arrow leaf -> side "across"\n'
          '@ arrow b -> a "past"\n'
          '@ arrow c -> d "through"\n'
          '@ arrow leaf -> a "out"\n')


def test_an_arrow_draws_above_every_container_around_its_end():
    view = _view(NESTED)
    for src, dst, holders in (("b", "leaf", ("outer", "inner")),
                              ("leaf", "side", ("outer", "inner")),
                              ("leaf", "a", ("outer", "inner"))):
        z = _z(view, src, dst)
        for cid in holders:
            body, title = _container(view, cid)
            assert z > body and z > title, (src, dst, cid)


def test_an_arrow_draws_below_a_container_it_only_passes():
    view = _view(NESTED)
    # b -> a crosses Outer, Inner and Wall; c -> d crosses Wall and Wall in;
    # leaf -> a leaves Outer and crosses Wall on its way down.
    for src, dst, passed in (("b", "a", ("outer", "inner", "wall")),
                             ("c", "d", ("wall", "wall_in")),
                             ("leaf", "a", ("wall",))):
        z = _z(view, src, dst)
        for cid in passed:
            body, title = _container(view, cid)
            assert z < body and z < title, (src, dst, cid)


def test_an_arrow_ending_at_a_container_draws_above_it():
    view = _view(NESTED + '@ arrow a -> wall "to the wall"\n')
    body, title = _container(view, "wall")
    assert _z(view, "a", "wall") > max(body, title)


def test_a_container_stays_below_the_containers_inside_it():
    view = _view(NESTED)
    assert _container(view, "outer")[0] < _container(view, "inner")[0]
    assert _container(view, "wall")[0] < _container(view, "wall_in")[0]


def test_boxes_and_notes_still_draw_above_every_arrow():
    view = _view(NESTED)
    top = max(g.zValue() for g in view._arrow_items
              if isinstance(g, ArrowLineItem))
    for bid in ("leaf", "side", "a", "b"):
        assert view._box_items[bid].zValue() > top


def _pixel_on_line(view, item: ArrowLineItem, y: float) -> QColor:
    """Render the scene around where *item* crosses height *y* and return
    the colour at the line's own x there."""
    path = item.mapToScene(item.path())
    best = min((path.pointAtPercent(t / 400) for t in range(401)),
               key=lambda p: abs(p.y() - y))
    rect = QRectF(best.x() - 4, best.y() - 4, 9, 9)
    img = QImage(9, 9, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    view._scene.render(painter, QRectF(0, 0, 9, 9), rect)
    painter.end()
    return img.pixelColor(4, 4)


def test_layers_map_arrows_into_scene_items_cross_the_view_title_unbroken():
    view = _view((EXAMPLES / "layers-map.grafli").read_text())
    body, title = _container(view, "view")
    label = view._box_items["view"]._label
    strip = label.mapRectToScene(label.boundingRect())
    ink = theme.ARROW_COLOR
    for src in ("render", "slides", "html"):
        z = _z(view, src, "scene")
        assert z > body and z > title, src
        lines = [g for g in _arrow_items(view, src, "scene")
                 if isinstance(g, ArrowLineItem)
                 and g.sceneBoundingRect().top() <= strip.center().y()
                 <= g.sceneBoundingRect().bottom()]
        assert lines, src
        seen = _pixel_on_line(view, lines[0], strip.center().y())
        # Drawn on top, the line keeps its own ink across the strip.
        assert (abs(seen.red() - ink.red()) + abs(seen.green() - ink.green())
                + abs(seen.blue() - ink.blue())) < 60, (src, seen.name())
