"""#260: a render reads in the order a hand-made sketch does — the box
labels first, the connectors between them quieter, their labels quieter
still — in both themes."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.format import parse
from grafli.items import ArrowLineItem

BOARD = ('#!grafli v4\n'
         '@ box a "A" 0,0 200x80\n'
         '@ box b "B" 400,0 200x80\n'
         '@ arrow a -> b "feeds"\n')


def _view(text: str = BOARD):
    from grafli.view import GrafliView
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _contrast(color: QColor) -> int:
    return abs(color.lightness() - theme.SCENE_BG.lightness())


def test_a_plain_connector_draws_in_the_arrow_ink():
    lines = [g for g in _view()._arrow_items if isinstance(g, ArrowLineItem)]
    assert lines
    assert {g.pen().color().name() for g in lines} == {theme.ARROW_COLOR.name()}


def test_a_connector_is_quieter_than_a_box_label_in_both_themes():
    for name in ("light", "dark"):
        theme.set_theme(name)
        try:
            assert 0 < _contrast(theme.ARROW_COLOR) < _contrast(theme.INK)
        finally:
            theme.set_theme("light")


def _labels(view):
    from grafli.items import LabelItem
    return [g for g in view._arrow_items if isinstance(g, LabelItem)]


def test_an_arrow_label_is_set_in_the_proportional_face_and_muted_ink():
    from grafli.constants import SANS_FONT_FAMILY
    (label,) = _labels(_view())
    assert label.font().family() == SANS_FONT_FAMILY
    assert label.brush().color() == QColor(theme.INK_MUTED)
    assert _contrast(theme.INK_MUTED) < _contrast(theme.INK)


def test_diagnose_measures_an_arrow_label_in_the_face_it_is_drawn_in():
    from PySide6.QtGui import QFontMetricsF
    from grafli.app import _make_arrow_label_size_provider
    from grafli.edge_label import arrow_label_font
    _view()
    arrow = parse(BOARD).arrows[0]
    width, _ = _make_arrow_label_size_provider()(arrow)
    assert width == QFontMetricsF(arrow_label_font()).horizontalAdvance("feeds")
