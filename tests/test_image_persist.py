"""Regression: pasted images survive a reload (no grey placeholder)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_pasted_image_loads_after_reload():
    _app()
    from grafli.app import MainWindow
    from grafli.format import serialize

    d = Path(tempfile.mkdtemp())
    fp = d / "test.grafli"
    fp.write_text('@ box a "A" 0,0 120x60\n')

    w = MainWindow(str(fp))
    img = QImage(200, 100, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    w._view._paste_clipboard_image(QPointF(300, 300), img)
    assert len(w._view._board.images) == 1
    fp.write_text(serialize(w._view._board))
    w.close()

    # Reopen the file in a fresh window: the image must resolve, not fall back
    # to the grey placeholder.
    w2 = MainWindow(str(fp))
    items = list(w2._view._image_items.values())
    assert len(items) == 1
    assert items[0]._base_dir == str(d)
    assert items[0]._placeholder is False
    w2.close()
