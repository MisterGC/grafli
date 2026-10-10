"""Tours through a box (D10): `gt` on a selected box lists the flows with a
stop whose focus holds the box or one of its containers, in a picker like
the buffer picker; picking one plays it from that stop. Without any, a toast
says no tour passes through the box (#166)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QTextBrowser

from grafli.app import MainWindow
from grafli.flows import tours_through
from grafli.format import parse


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


BOARD = "\n".join([
    "#!grafli v3",
    '@ box sys "System" 0,0 800x600',
    '@ box combat "Combat" 20,40 400x300 >sys',
    '@ box blow "blow()" 40,80 120x60 >combat',
    '@ box hud "HUD" 900,0 120x60',
    '@ box lonely "Lonely" 900,200 120x60',
    '@ bookmark b_sys "The whole system" @sys',
    '@ bookmark b_hud "The HUD" @hud',
    '@ bookmark b_combat "Combat" @combat',
    '@ bookmark b_blow "The blow" @blow,hud',
    '@ flow a "Combat tour" b_hud b_combat b_blow',
    '@ flow b "Blow only" b_hud other#b_blow b_blow',
    '@ flow c "HUD tour" b_hud',
    '@ flow d "Elsewhere" other#b_blow',
    '@ flow e "Overview" b_sys b_hud',
]) + "\n"


def _found(board, box_id: str) -> list[tuple[str, int]]:
    return [(flow.id, index) for flow, index in tours_through(board, box_id)]


def test_lists_the_flows_through_the_box_or_its_containers_at_the_first_stop():
    board = parse(BOARD)
    # a: first through the container combat (stop 2), not the box (stop 3);
    # b: the box itself at stop 3 — the cross-board stop 2 doesn't count;
    # c and d never pass; e passes through the outer container sys.
    assert _found(board, "blow") == [("a", 1), ("b", 2), ("e", 0)]
    assert _found(board, "combat") == [("a", 1), ("e", 0)]
    assert _found(board, "hud") == [("a", 0), ("b", 0), ("c", 0), ("e", 1)]
    assert _found(board, "lonely") == []
    assert _found(board, "nope") == []


def test_a_parent_cycle_does_not_hang():
    board = parse("\n".join([
        "#!grafli v2",
        '@ box x "X" 0,0 100x100 >y',
        '@ box y "Y" 0,0 100x100 >x',
        '@ bookmark bx "X" @y',
        '@ flow f "F" bx',
    ]) + "\n")
    assert _found(board, "x") == [("f", 0)]


# ── gt in the window ──


def _window(tmp_path: Path) -> MainWindow:
    path = tmp_path / "System.grafli"
    path.write_text(BOARD)
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    app.processEvents()
    view = win._view
    view._animate_to_rect = lambda rect, **_: view.goto_rect(rect,
                                                             animate=False)
    view.transitions_enabled = lambda: False
    return win


def _select(win: MainWindow, box_id: str):
    """Zoom in on the box first — a nested box stays hidden by the level of
    detail at the fit zoom, and a hidden item can't be selected."""
    view = win._view
    item = view._box_items[box_id]
    view.goto_rect(item.sceneBoundingRect(), animate=False)
    _app().processEvents()
    view._scene.clearSelection()
    item.setSelected(True)
    assert item.isSelected()


def _press(widget, *keys):
    for key in keys:
        QTest.keyClick(widget, key)
    _app().processEvents()


def _picker_lines(win: MainWindow) -> list[str]:
    lst = win._view._fuzzy_overlay._list
    return [lst.item(i).text() for i in range(lst.count())]


def test_gt_lists_the_tours_and_picking_one_plays_from_that_stop(
        tmp_path: Path):
    win = _window(tmp_path)
    view = win._view
    _select(win, "blow")
    _press(view, Qt.Key.Key_G, Qt.Key.Key_T)

    overlay = view._fuzzy_overlay
    assert overlay is not None
    assert overlay._title.text() == "Tours through blow()"
    assert _picker_lines(win) == [
        "Combat tour  stop 2/3 · Combat",
        "Blow only  stop 3/3 · The blow",
        "Overview  stop 1/2 · The whole system",
    ]

    _press(overlay._input, Qt.Key.Key_Down, Qt.Key.Key_Return)
    assert view._fuzzy_overlay is None
    player = view._flow_player
    assert player is not None and player.active
    assert player.flow.id == "b"
    assert view._flow_overlay["index"] == 2
    assert view._flow_overlay["label"] == "The blow"
    win.close()


def test_gt_picker_filters_and_esc_plays_nothing(tmp_path: Path):
    win = _window(tmp_path)
    view = win._view
    _select(win, "blow")
    _press(view, Qt.Key.Key_G, Qt.Key.Key_T)
    overlay = view._fuzzy_overlay
    QTest.keyClicks(overlay._input, "over")
    _app().processEvents()
    assert _picker_lines(win) == ["Overview  stop 1/2 · The whole system"]

    _press(overlay._input, Qt.Key.Key_Escape)
    assert view._fuzzy_overlay is None
    assert view._flow_player is None
    win.close()


def test_gt_toasts_when_no_tour_passes_through_the_box(tmp_path: Path):
    win = _window(tmp_path)
    view = win._view
    _select(win, "lonely")
    _press(view, Qt.Key.Key_G, Qt.Key.Key_T)
    assert view._fuzzy_overlay is None
    assert view._flow_player is None
    assert view._toast_text == "no tour passes through Lonely"
    win.close()


def test_gt_toasts_without_a_selected_box(tmp_path: Path):
    win = _window(tmp_path)
    view = win._view
    view._scene.clearSelection()
    _press(view, Qt.Key.Key_G, Qt.Key.Key_T)
    assert view._fuzzy_overlay is None
    assert view._toast_text == "Select a box to find the tours through it"
    win.close()


def test_help_sheet_lists_gt(tmp_path: Path, monkeypatch):
    win = _window(tmp_path)
    shown: list[str] = []

    def _exec(dlg):
        shown.extend(b.toPlainText() for b in dlg.findChildren(QTextBrowser))
        return 0

    monkeypatch.setattr(QDialog, "exec", _exec)
    win._view._show_cheatsheet()

    text = "\n".join(shown)
    assert "gt" in text
    assert "Pick a tour through the box, play from there" in text
    win.close()
