"""Image connectors render, and images simplify at low zoom (#150).

Connect mode always accepted images and the `@ arrow` line landed in the
file — but the renderer dropped any connector with an image endpoint. The
LOD indicator is stateless: purely a function of the current zoom.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.items import IMAGE_LOD_PX

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50">'
       b'<rect width="100" height="50" fill="#36a"/></svg>')


def _view(src: str, tmp: Path):
    QApplication.instance() or QApplication([])
    from grafli.view import GrafliView
    (tmp / "art.svg").write_bytes(SVG)
    view = GrafliView()
    view.base_dir = str(tmp)
    view.load_board(parse("#!grafli v1\n" + src))
    view.resize(900, 600)
    return view


def test_connectors_with_image_endpoints_render(tmp_path: Path):
    view = _view(
        '@ box a "A" 0,0 160x80\n'
        '@ note n1 0,220 "a note"\n'
        '@ image i1 "art.svg" 320,0 240x120\n'
        '@ arrow a -> i1 "uses"\n'
        '@ arrow n1 -> i1 "describes"\n',
        tmp_path,
    )
    # Before the fix both connectors were silently dropped at draw time.
    assert len(view._arrow_items) > 0
    labels = {getattr(it, "text", lambda: "")() for it in view._arrow_items
              if hasattr(it, "text")}
    assert {"uses", "describes"} <= labels


def test_image_connector_promoted_to_graph_edge_renders(tmp_path: Path):
    view = _view(
        '@ box a "A" 0,0 160x80\n'
        '@ image i1 "art.svg" 320,0 240x120\n'
        '@ arrow a -> i1 "flow" ~kind=graph\n',
        tmp_path,
    )
    assert len(view._arrow_items) > 0


def test_lod_indicator_follows_the_zoom(tmp_path: Path):
    view = _view('@ image i1 "art.svg" 0,0 240x120\n', tmp_path)
    item = view._image_items["i1"]
    assert not item._lod_indicator()        # 120px shorter side at 100%
    view.scale(0.2, 0.2)                    # 24px on screen -> indicator
    assert item._lod_indicator()
    view.resetTransform()
    assert not item._lod_indicator()


def test_lod_indicator_paint_smoke(tmp_path: Path):
    view = _view('@ image i1 "art.svg" 0,0 240x120\n', tmp_path)
    view.scale(0.1, 0.1)
    item = view._image_items["i1"]
    assert item._lod_indicator()
    img = QImage(64, 32, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    item.paint(p, None)
    p.end()


def test_smallest_image_still_shows_art_at_full_zoom(tmp_path: Path):
    # The 40px minimum element size sits above the indicator threshold.
    view = _view('@ image i1 "art.svg" 0,0 40x40\n', tmp_path)
    assert 40 >= IMAGE_LOD_PX
    assert not view._image_items["i1"]._lod_indicator()
