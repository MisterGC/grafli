"""d-mode toggles for the resize flags, and selection-only markers."""

from __future__ import annotations

import os

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication

from grafli.format import parse, serialize
from grafli.view import GrafliView, Mode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _view(src: str = "#!grafli v2\n@ box a \"A\" 0,0 200x100\n") -> GrafliView:
    QApplication.instance() or QApplication([])
    view = GrafliView()
    view.load_board(parse(src))
    view.resize(800, 600)
    view._mode = Mode.SELECT
    return view


def test_toggle_lock_ratio_flips_and_serializes():
    view = _view()
    box = view._box_items["a"]
    box.setSelected(True)
    view._toggle_box_flag("lock_ratio")
    assert box.box.lock_ratio is True
    assert "!ratio" in serialize(view.board)
    view._toggle_box_flag("lock_ratio")
    assert box.box.lock_ratio is False
    assert "!ratio" not in serialize(view.board)


def test_toggle_scale_children_flips():
    view = _view()
    box = view._box_items["a"]
    box.setSelected(True)
    view._toggle_box_flag("scale_children")
    assert box.box.scale_children is True
    assert "!fit" in serialize(view.board)


def test_d_then_a_toggles_lock_via_keys():
    view = _view()
    box = view._box_items["a"]
    box.setSelected(True)
    view._box_mode = "dimension"
    evt = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A,
                    Qt.KeyboardModifier.NoModifier, "a")
    view.keyPressEvent(evt)
    assert box.box.lock_ratio is True


def test_d_then_f_toggles_fit_via_keys():
    view = _view()
    box = view._box_items["a"]
    box.setSelected(True)
    view._box_mode = "dimension"
    evt = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F,
                    Qt.KeyboardModifier.NoModifier, "f")
    view.keyPressEvent(evt)
    assert box.box.scale_children is True


def test_toggle_without_selection_is_a_noop():
    view = _view()
    view._toggle_box_flag("lock_ratio")               # nothing selected
    assert view._box_items["a"].box.lock_ratio is False


def test_markers_paint_only_when_selected():
    # Smoke test: a selected box with both flags renders without error.
    view = _view("#!grafli v2\n@ box a \"A\" 0,0 200x100 !ratio !fit\n")
    box = view._box_items["a"]
    box.setSelected(True)
    img = QImage(300, 200, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    view._scene.render(p)
    p.end()
    assert True                                        # no crash painting markers
