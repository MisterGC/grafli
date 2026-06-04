"""Pasting a clipboard image: non-ARGB32 sources are normalized before save.

A QImage straight from the macOS clipboard can carry a format/stride that
crashes the PNG writer (segfault in QImageWriter::write). _paste_clipboard_image
must convert to a canonical format first, so any source format saves cleanly.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _window(tmp):
    QApplication.instance() or QApplication([])
    f = os.path.join(tmp, "t.grafli")
    with open(f, "w") as fh:
        fh.write('#!grafli v2\n@ box a "A" 0,0 120x60\n')
    from grafli.app import MainWindow
    w = MainWindow(f)
    w.resize(900, 600)
    return w


def _paste_format(fmt) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmp:
        w = _window(tmp)
        img = QImage(640, 400, fmt)
        img.fill(0x3366AA)
        w._view._paste_clipboard_image(QPointF(50, 50), img)
        images = w._view._board.images
        assert len(images) == 1
        saved = os.path.join(tmp, images[0].image_path)
        assert os.path.exists(saved)
        reloaded = QImage(saved)
        assert not reloaded.isNull()
        return reloaded.width(), reloaded.height()


def test_paste_rgb888_image_saves_valid_png():
    # The format the old code crashed on (non-ARGB32, packed 24-bit).
    assert _paste_format(QImage.Format.Format_RGB888) == (640, 400)


def test_paste_argb32_image_saves_valid_png():
    assert _paste_format(QImage.Format.Format_ARGB32) == (640, 400)


def test_paste_indexed8_image_saves_valid_png():
    assert _paste_format(QImage.Format.Format_Indexed8) == (640, 400)


def test_paste_null_image_is_a_noop():
    with tempfile.TemporaryDirectory() as tmp:
        w = _window(tmp)
        w._view._paste_clipboard_image(QPointF(0, 0), QImage())
        assert len(w._view._board.images) == 0
