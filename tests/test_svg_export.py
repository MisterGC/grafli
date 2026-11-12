"""The SVG export paints in board coordinates.

Its viewBox is the board's padded bounds, so the board has to be painted at
its own coordinates for the picture to show it; the HTML export places its
click areas from board rects on the same SVG.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from grafli.format import parse

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(text: str):
    QApplication.instance() or QApplication([])
    from grafli.view import GrafliView
    view = GrafliView()
    view.load_board(parse(text))
    return view


def test_svg_viewbox_shows_the_board_where_it_lies():
    # Bounds far from the origin: a shifted paint would miss the viewBox.
    view = _view('#!grafli v2\n@ box a "A" 300,400 120x60 #222222\n')
    svg = bytes(view._render_svg_bytes(padding=20))
    renderer = QSvgRenderer(QByteArray(svg))
    box = QRectF(view._box_items["a"].sceneBoundingRect())
    assert renderer.viewBoxF().contains(box)

    # Rasterise at one pixel per board unit and look inside the box.
    vb = renderer.viewBoxF()
    image = QImage(int(vb.width()), int(vb.height()),
                   QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    inside = image.pixelColor(int(box.center().x() - vb.x()),
                              int(box.top() + 10 - vb.y()))
    assert inside.name() == "#222222"
