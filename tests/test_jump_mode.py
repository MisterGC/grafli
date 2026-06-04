"""Jump-to mode (f / Ctrl+J): activation and input isolation."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str) -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(1000, 700)
    view._mode = Mode.SELECT
    return view


# A box and an image, both in view — the image used to crash _start_jump_mode.
_WITH_IMAGE = """\
#!grafli v2
@ box b "Alpha" 0,0 120x60
@ image img1 "shots/x.png" 200,0 160x100
"""


def test_jump_mode_activates_with_image_in_viewport():
    # Regression: _render_jump_label called .brush() on an ImageItem, which has
    # no brush — the exception aborted _start_jump_mode before it set the flag,
    # so jump never activated and later keys leaked to global shortcuts.
    view = _view(_WITH_IMAGE)
    view._start_jump_mode()
    assert view._jump_active is True
    assert len(view._jump_map) == 2          # box + image both got hints


def test_letter_key_is_consumed_while_jump_active_not_global():
    # While inputting a jump label, 'a' must not toggle the complexity heatmap.
    view = _view(_WITH_IMAGE)
    view._start_jump_mode()
    assert view._jump_active
    assert view._complexity_active is False
    evt = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                    Qt.KeyboardModifier.NoModifier, "a")
    view.keyPressEvent(evt)
    # 'a' was routed to the jump handler, so analyze/complexity didn't toggle on.
    assert view._complexity_active is False
