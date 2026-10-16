"""`!card`: a box with children keeps its node look (#203) — its fill,
border, rounded corners and a node's label size, centred — while a plain
parent still draws as a flat container with a small top-left heading."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from grafli.format import parse

BOARD = ('#!grafli v4\n'
         '@ box c "Card" 0,0 260x150 %teal !card\n'
         '@ note cn 30,60 "body" >c\n'
         '@ box p "Plain" 320,0 260x150 %teal\n'
         '@ note pn 350,60 "body" >p\n'
         '@ box leaf "Leaf" 640,0 260x150 %teal !card\n')


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(text: str = BOARD):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def test_a_card_with_a_child_keeps_its_fill_border_and_corners():
    view = _view()
    card, plain = view._box_items["c"], view._box_items["p"]
    assert card._is_parent and plain._is_parent
    assert card.pen().style() != Qt.PenStyle.NoPen
    assert card.brush().color().alphaF() == 1.0
    assert not card._container_look()
    # The plain parent is still the flat container.
    assert plain.pen().style() == Qt.PenStyle.NoPen
    assert plain.brush().color().alphaF() < 1.0
    assert plain._container_look()


def test_a_card_label_keeps_a_node_size_and_centring():
    view = _view()
    card, plain = view._box_items["c"], view._box_items["p"]
    leaf = view._box_items["leaf"]
    assert card._label.font() == leaf._label.font()
    assert plain._label.font() != leaf._label.font()
    assert card._get_effective_anchor() == "topcenter"
    centre = card.pos().x() + card.box.w / 2
    br = card._label.boundingRect()
    assert abs(card._label.pos().x() + br.width() / 2 - centre) < 1.0
    # The plain parent keeps the small top-left heading.
    assert plain._get_effective_anchor() == "topleft"
    assert plain._get_effective_textsize() == "small"


def test_a_card_without_children_is_an_ordinary_node():
    view = _view()
    leaf = view._box_items["leaf"]
    assert leaf._get_effective_anchor() == ""
    assert not leaf._container_look()


def _render(tmp_path: Path, name: str, text: str) -> QImage:
    from grafli.app import _cmd_render
    board = tmp_path / f"{name}.grafli"
    board.write_text(text)
    out = tmp_path / f"{name}.png"
    assert _cmd_render([str(board), str(out)]) == 0
    return QImage(str(out))


def test_render_draws_the_card(tmp_path: Path):
    _app()
    card = _render(tmp_path, "card", BOARD)
    plain = _render(tmp_path, "plain", BOARD.replace(" !card", "")
                    .replace("v4", "v1"))
    assert card != plain


def test_switching_to_card_refreshes_the_label():
    view = _view(BOARD.replace(" %teal !card", " %teal", 1))
    item = view._box_items["c"]
    assert item._get_effective_anchor() == "topleft"
    small = item._label.font()
    item.set_style("card")
    assert item._get_effective_anchor() == "topcenter"
    assert item._label.font() != small
    item.set_style("")
    assert item._label.font() == small
