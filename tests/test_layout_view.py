"""The app's `=` key runs the shared layout driver on the loaded board."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BOARD = """\
#!grafli v1
@ box svc "Services" 0,0 300x600 ^topleft
@ box api "API" 40,500 160x80 >svc
@ box db "DB" 40,60 160x80 >svc
@ box ui "UI" 600,600 160x80
@ arrow api -> db
@ arrow ui -> svc
"""


def test_layout_key_ranks_children_and_siblings():
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(_BOARD))
    view._layout_selected()
    board = view.board
    api, db = board.box_by_id("api"), board.box_by_id("db")
    svc, ui = board.box_by_id("svc"), board.box_by_id("ui")
    assert api.y < db.y      # api -> db inside the container
    assert ui.y < svc.y      # ui -> svc at the root
    for c in (api, db):      # children moved along with their container
        assert svc.x <= c.x and c.x + c.w <= svc.x + svc.w
        assert svc.y <= c.y and c.y + c.h <= svc.y + svc.h
