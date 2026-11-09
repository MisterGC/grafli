"""#293: a leaf box three or more containers deep draws its label above
its own fill."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli.format import parse

DEEP = ('#!grafli v4\n'
        '@ box host "Host" 0,0 900x700\n'
        '@ box sw "Software" 20,40 860x620 >host\n'
        '@ box api "Api" 40,80 500x500 >sw\n'
        '@ box ctl "Controller" 60,120 200x100 >api\n'
        '@ box svc "Service" 60,280 440x260 >api\n'
        '@ box repo "Repository" 80,340 200x100 >svc\n'
        '@ box db "DB" 600,80 260x300 >sw\n'
        '@ box tbl "Table" 620,140 200x100 >db\n'
        '@ box mon "Monitor" 950,0 200x100\n')

LEAVES = {"ctl": 3, "tbl": 3, "repo": 4, "mon": 0}


def _view(text: str):
    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


def test_deep_leaf_labels_stack_above_their_box():
    view = _view(DEEP)
    for bid, depth in LEAVES.items():
        assert view._box_depth(bid) == depth, bid
        item = view._box_items[bid]
        assert item._label.zValue() > item.zValue(), bid


def test_deep_leaf_labels_stay_above_every_note():
    view = _view(DEEP + '@ note n 950,200 "A note"\n')
    note_z = max(n.zValue() for n in view._note_items.values())
    for bid in LEAVES:
        assert view._box_items[bid]._label.zValue() > note_z, bid


def _ink_pixels(view, bid: str) -> int:
    """Render the scene over *bid*'s label and count pixels that differ
    from the box fill, i.e. the label's ink."""
    item = view._box_items[bid]
    label = item._label
    rect = label.mapRectToScene(label.boundingRect())
    w, h = int(rect.width()), int(rect.height())
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    view._scene.render(painter, QRectF(0, 0, w, h), rect)
    painter.end()
    fill = QColor(item.brush().color())
    count = 0
    for x in range(w):
        for y in range(h):
            c = img.pixelColor(x, y)
            if (abs(c.red() - fill.red()) + abs(c.green() - fill.green())
                    + abs(c.blue() - fill.blue())) > 120:
                count += 1
    return count


def test_a_render_four_levels_deep_shows_every_leaf_label():
    view = _view(DEEP)
    for bid in LEAVES:
        assert _ink_pixels(view, bid) > 20, bid
