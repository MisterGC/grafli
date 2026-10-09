"""Moving between boards: the Ctrl+O / Ctrl+I jumplist belongs to one board."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _board(path: Path, *boxes: tuple[str, str, int, int]) -> Path:
    lines = ["#!grafli v1"]
    for bid, label, x, y in boxes:
        lines.append(f'@ box {bid} "{label}" {x},{y} 120x60')
    path.write_text("\n".join(lines) + "\n")
    return path


def _window(path: Path) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    view = win._view
    # Instant navigation, so transforms can be asserted right away.
    view._animate_to_rect = lambda rect: view.goto_rect(rect, animate=False)
    return win


def test_jumplist_does_not_cross_a_board_switch(tmp_path: Path):
    a = _board(tmp_path / "a.grafli", ("a1", "A1", 0, 0), ("a2", "A2", 3000, 2000))
    b = _board(tmp_path / "b.grafli", ("b1", "B1", 0, 0))
    win = _window(a)
    view = win._view
    view._nav_stack = [QRectF(0, 0, 100, 100), QRectF(3000, 2000, 100, 100)]
    view._nav_index = 1

    win._open_file(b)
    assert view._nav_stack == []
    view._nav_back()
    assert view._toast_text == "No earlier view to jump back to"

    # Back on A, its own history is there again.
    win._toggle_last_buffer()
    assert view._nav_stack == [QRectF(0, 0, 100, 100),
                               QRectF(3000, 2000, 100, 100)]
    assert view._nav_index == 1
    win.close()
