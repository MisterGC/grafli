"""The heatmap (A) is Connectivity, counts graph arrows only, and paints
whatever its provider reads (#159)."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser

from grafli.format import parse
from grafli.heat import DegreeProvider, HeatLegend, HeatReading
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


_BOARD = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ box c "C" 600,0 120x60
@ arrow a -> b ""
@ arrow b -> c ""
@ note n 0,200 "a remark"
"""

_WITH_ANNOTATION = _BOARD + '@ arrow a -> n ""\n'


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(900, 600)
    return view


def _key(view, key):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.NoModifier))


def test_annotation_arrow_does_not_change_a_box_heat():
    plain = _view(_BOARD)
    annotated = _view(_WITH_ANNOTATION)
    _key(plain, Qt.Key.Key_A)
    _key(annotated, Qt.Key.Key_A)

    assert annotated._complexity_active
    assert annotated._complexity_node_heat == plain._complexity_node_heat
    assert annotated._complexity_node_heat["a"] == 0.5


def test_explicit_graph_kind_on_a_note_arrow_still_counts():
    view = _view(_BOARD + '@ arrow a -> n "" ~kind=graph\n')
    _key(view, Qt.Key.Key_A)

    assert view._complexity_node_heat["a"] == 1.0


def test_only_annotation_arrows_has_nothing_to_analyse():
    src = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ note n 0,200 "a remark"
@ arrow a -> n ""
"""
    view = _view(src)
    _key(view, Qt.Key.Key_A)

    assert not view._complexity_active
    assert view._toast_text == "No connectors to analyse"


class _RecordingPainter(QPainter):
    def __init__(self, device):
        super().__init__(device)
        self.texts: list[str] = []

    def drawText(self, *args):
        self.texts.append(args[-1])
        super().drawText(*args)


def _legend_texts(view) -> list[str]:
    view._minimap_visible = True
    view._minimap_rect = QRect(700, 450, 180, 120)
    img = QImage(900, 600, QImage.Format.Format_ARGB32)
    painter = _RecordingPainter(img)
    try:
        view._draw_complexity_legend(painter)
    finally:
        painter.end()
    return painter.texts


def test_legend_says_connectivity():
    view = _view(_BOARD)
    _key(view, Qt.Key.Key_A)

    texts = _legend_texts(view)
    assert texts[0] == "Connectivity"
    assert "COMPLEXITY" not in texts


def test_help_sheet_says_connectivity(monkeypatch):
    view = _view(_BOARD)
    shown: list[str] = []

    def _exec(dlg):
        shown.extend(b.toPlainText() for b in dlg.findChildren(QTextBrowser))
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    view._show_cheatsheet()

    sheet = "\n".join(shown)
    assert "Connectivity heatmap" in sheet
    assert "Complexity" not in sheet


def test_degree_count_is_the_default_provider():
    view = _view(_BOARD)

    assert isinstance(view._heat_provider, DegreeProvider)


class _FixedProvider:
    def analysable(self, board):
        return True

    def read(self, board):
        return HeatReading({"c": 1.0}, HeatLegend("Tests", "pass", "fail"))


def test_renderer_paints_any_provider():
    view = _view(_BOARD)
    view._heat_provider = _FixedProvider()
    _key(view, Qt.Key.Key_A)

    assert view._complexity_node_heat == {"c": 1.0}
    assert _legend_texts(view) == ["Tests", "pass", "fail"]
    # A box the reading leaves out paints cold, the hot one glows.
    assert view._box_items["c"].graphicsEffect() is not None
    assert view._box_items["a"].graphicsEffect() is None

    _key(view, Qt.Key.Key_A)
    assert not view._complexity_active
    assert view._complexity_legend is None
