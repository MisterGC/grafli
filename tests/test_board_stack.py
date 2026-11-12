"""Moving between boards: entering a linked board pushes a frame, `gu` goes
back to the board you came from as you left it, the breadcrumb shows the board
path, and the Ctrl+O / Ctrl+I jumplist belongs to one board."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser

from grafli.app import MainWindow
from grafli.buffers import BoardFrame, BufferManager, ViewState


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _board(path: Path, *boxes: tuple) -> Path:
    """Write a board of boxes (id, label, x, y[, attachment])."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#!grafli v1"]
    for bid, label, x, y, *attach in boxes:
        tail = f" {attach[0]}" if attach else ""
        lines.append(f'@ box {bid} "{label}" {x},{y} 120x60{tail}')
    path.write_text("\n".join(lines) + "\n")
    return path


def _system(tmp_path: Path) -> tuple[Path, Path, Path]:
    """system → Combat (&graph) → impact() (&graph), two levels deep."""
    root = _board(tmp_path / "System.grafli",
                  ("player", "Player", 0, 0),
                  ("combat", "Combat", 2500, 1800, "&graph:combat"))
    combat = _board(tmp_path / "System-res" / "combat.grafli",
                    ("blow", "blow()", 0, 0),
                    ("impact", "impact()", 900, 600, "&graph:impact"))
    impact = _board(tmp_path / "System-res" / "combat-res" / "impact.grafli",
                    ("hit", "hit test", 0, 0))
    return root, combat, impact


def _window(path: Path) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    view = win._view
    # Instant navigation, so transforms can be asserted right away.
    view._animate_to_rect = lambda rect, **_: view.goto_rect(rect,
                                                             animate=False)
    view.transitions_enabled = lambda: False   # no zoom into the level
    return win


def _enter(win: MainWindow, box_id: str):
    """Select *box_id* and open its attachment, as Return does."""
    view = win._view
    view._scene.clearSelection()
    view._box_items[box_id].setSelected(True)
    view._open_resource()
    _app().processEvents()   # let the on-open fit run, as it does live


def _press_gu(win: MainWindow):
    QTest.keyClick(win._view, Qt.Key.Key_G)
    QTest.keyClick(win._view, Qt.Key.Key_U)
    _app().processEvents()


def _transform(win: MainWindow) -> tuple[float, ...]:
    t = win._view.transform()
    return (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy())


def _selected_boxes(win: MainWindow) -> list[str]:
    return [bid for bid, it in win._view._box_items.items() if it.isSelected()]


def test_gu_twice_lands_on_the_root_as_you_left_it(tmp_path: Path):
    root, combat, impact = _system(tmp_path)
    win = _window(root)
    view = win._view
    # A place on the root that a fit would never produce: zoomed in on
    # Combat, scrolled to it, Combat selected.
    _enter(win, "combat")
    win._go_up()            # back first, so the root is reached by gu below
    view.goto_rect(QRectF(2400, 1700, 400, 300), animate=False)
    view._scene.clearSelection()
    view._box_items["combat"].setSelected(True)
    root_transform = _transform(win)
    root_scroll = (view.horizontalScrollBar().value(),
                   view.verticalScrollBar().value())

    _enter(win, "combat")
    assert win._file_path == combat
    view.goto_rect(QRectF(800, 500, 300, 200), animate=False)
    combat_transform = _transform(win)
    _enter(win, "impact")
    assert win._file_path == impact

    _press_gu(win)
    assert win._file_path == combat
    assert _transform(win) == combat_transform
    assert _selected_boxes(win) == ["impact"]

    _press_gu(win)
    assert win._file_path == root
    assert _transform(win) == root_transform
    assert (view.horizontalScrollBar().value(),
            view.verticalScrollBar().value()) == root_scroll
    assert _selected_boxes(win) == ["combat"]
    win.close()


def test_gu_on_the_root_toasts_already_at_the_top(tmp_path: Path):
    root, _, _ = _system(tmp_path)
    win = _window(root)
    _press_gu(win)
    assert win._file_path == root
    assert win._view._toast_text == "Already at the top"
    win.close()


def test_help_sheet_lists_gu(tmp_path: Path, monkeypatch):
    root, _, _ = _system(tmp_path)
    win = _window(root)
    shown: list[str] = []

    def _exec(dlg):
        shown.extend(b.toPlainText() for b in dlg.findChildren(QTextBrowser))
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()

    assert "Back to the board you came from" in "\n".join(shown)
    win.close()


def test_breadcrumb_shows_the_labels_entered_through(tmp_path: Path):
    root, _, _ = _system(tmp_path)
    win = _window(root)
    crumb = win._status_breadcrumb
    _enter(win, "combat")
    _enter(win, "impact")
    win._view._scene.clearSelection()
    assert crumb.text() == "System \u203a Combat \u203a impact()"
    # A selected box adds its place within the board after the board path.
    win._view._box_items["hit"].setSelected(True)
    assert crumb.text() == "System \u203a Combat \u203a impact() \u203a hit test"

    _press_gu(win)
    assert crumb.text().startswith("System \u203a Combat")
    _press_gu(win)
    # On the root the breadcrumb is what it always was: the box ancestry.
    assert crumb.text() == "Combat"
    win.close()


def test_a_grafli_link_enters_the_board_too(tmp_path: Path):
    other = _board(tmp_path / "other.grafli", ("o", "O", 0, 0))
    root = _board(tmp_path / "root.grafli",
                  ("ref", "See other", 0, 0, "&link:other.grafli"))
    win = _window(root)
    _enter(win, "ref")
    assert win._file_path == other
    assert win._status_breadcrumb.text() == "root \u203a See other"
    _press_gu(win)
    assert win._file_path == root
    win.close()


def test_entering_from_off_the_chain_starts_a_new_chain(tmp_path: Path):
    stack = BufferManager()
    a, b, c, d = (tmp_path / f"{n}.grafli" for n in "abcd")
    stack.push_frame(BoardFrame(a, ViewState(), b, "B"))
    assert stack.board_path(b) == ["a", "B"]
    # Switched to c some other way (Ctrl+K), then entered d from there.
    stack.push_frame(BoardFrame(c, ViewState(), d, "D"))
    assert stack.board_path(d) == ["c", "D"]
    assert stack.frame_for(b) is None
    assert stack.pop_frame().child_path == d
    assert stack.frame_for(c) is None


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
