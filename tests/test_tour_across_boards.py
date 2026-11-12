"""Tours across boards: a flow step ``<board>#<bookmark>`` is a stop in
another board; playing it enters that board through the board stack, Esc
comes back to the board the flow belongs to, and leaving a tour to look
around keeps its stop in the stack frame so `gu` resumes it (#165)."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _write(path: Path, *lines: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def _system(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """System → combat → impact, a tour on System with one stop on each
    level, and a detail board below combat to wander off into."""
    root = _write(
        tmp_path / "System.grafli",
        "#!grafli v3",
        '@ box player "Player" 0,0 120x60',
        '@ box combat "Combat" 400,0 120x60 &graph:combat',
        '@ bookmark r1 "The player" @player',
        '@ flow tour "A blow lands" r1 combat#c1 '
        'System-res/combat-res/impact.grafli#i1')
    combat = _write(
        tmp_path / "System-res" / "combat.grafli",
        "#!grafli v2",
        '@ box blow "blow()" 0,0 120x60',
        '@ box impact "impact()" 400,0 120x60 &graph:impact',
        '@ box detail "detail" 0,400 120x60 &graph:detail',
        '@ bookmark c1 "The blow" @blow')
    impact = _write(
        tmp_path / "System-res" / "combat-res" / "impact.grafli",
        "#!grafli v2",
        '@ box hit "hit test" 0,0 120x60',
        '@ bookmark i1 "The hit test" @hit')
    detail = _write(
        tmp_path / "System-res" / "combat-res" / "detail.grafli",
        "#!grafli v1",
        '@ box d "deep detail" 0,0 120x60')
    return root, combat, impact, detail


def _window(path: Path) -> MainWindow:
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


def _key(win: MainWindow, *keys):
    for key in keys:
        QTest.keyClick(win._view, key)
    _app().processEvents()


def _stop(win: MainWindow) -> tuple[int, str]:
    overlay = win._view._flow_overlay
    return overlay["index"], overlay["label"]


def test_a_tour_plays_down_three_boards_in_order_and_returns_to_the_root(
        tmp_path: Path):
    root, combat, impact, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    assert win._file_path == root
    assert _stop(win) == (0, "The player")

    _key(win, Qt.Key.Key_Space)
    assert win._file_path == combat
    assert _stop(win) == (1, "The blow")
    assert win._status_breadcrumb.text() == "System › combat"

    _key(win, Qt.Key.Key_Space)
    assert win._file_path == impact
    assert _stop(win) == (2, "The hit test")
    assert win._board_path() == ["System", "combat", "impact"]

    # The flow stays the root's: Esc ends it back where it started.
    _key(win, Qt.Key.Key_Escape)
    assert win._file_path == root
    assert view._flow_player is None
    assert win._board_path() == []
    win.close()


def test_stepping_back_climbs_the_boards_again(tmp_path: Path):
    root, combat, impact, _ = _system(tmp_path)
    win = _window(root)
    win._view.play_flow("tour")
    _key(win, Qt.Key.Key_Space, Qt.Key.Key_Space)
    assert win._file_path == impact

    _key(win, Qt.Key.Key_Left)
    assert win._file_path == combat
    assert _stop(win) == (1, "The blow")
    assert win._board_path() == ["System", "combat"]
    _key(win, Qt.Key.Key_Left)
    assert win._file_path == root
    assert _stop(win) == (0, "The player")
    assert win._board_path() == []
    win.close()


def test_leaving_at_stop_two_and_gu_back_resumes_at_stop_two(tmp_path: Path):
    root, combat, impact, detail = _system(tmp_path)
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    _key(win, Qt.Key.Key_Space)
    assert win._file_path == combat

    # Look around: select a box with a level and go down into it.
    view._box_items["detail"].setSelected(True)
    _key(win, Qt.Key.Key_G, Qt.Key.Key_D)
    assert win._file_path == detail
    assert view._flow_player is None
    assert view._toast_text == "Tour paused at stop 2 — gu resumes it"

    _key(win, Qt.Key.Key_G, Qt.Key.Key_U)
    assert win._file_path == combat
    assert view._flow_player is not None and view._flow_player.active
    assert _stop(win) == (1, "The blow")

    # And it plays on from there.
    _key(win, Qt.Key.Key_Space)
    assert win._file_path == impact
    assert _stop(win) == (2, "The hit test")
    win.close()


def test_return_on_a_level_leaves_the_tour_too(tmp_path: Path):
    root, combat, _, detail = _system(tmp_path)
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    _key(win, Qt.Key.Key_Space)
    view._box_items["detail"].setSelected(True)
    _key(win, Qt.Key.Key_Return)
    assert win._file_path == detail
    _key(win, Qt.Key.Key_G, Qt.Key.Key_U)
    assert win._file_path == combat
    assert _stop(win) == (1, "The blow")
    win.close()


def test_other_keys_still_belong_to_the_tour(tmp_path: Path):
    root, _, _, _ = _system(tmp_path)
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    view._box_items["player"].setSelected(True)
    # x deletes outside a tour; during one it is swallowed as before.
    _key(win, Qt.Key.Key_X)
    assert view.board.box_by_id("player") is not None
    assert view._flow_player is not None and view._flow_player.active
    win.close()


def test_a_stop_in_a_missing_board_shows_as_missing(tmp_path: Path):
    root = _write(
        tmp_path / "Lone.grafli",
        "#!grafli v3",
        '@ box a "A" 0,0 120x60',
        '@ bookmark b1 "A" @a',
        '@ flow tour "Tour" b1 nowhere#x')
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    _key(win, Qt.Key.Key_Space)
    assert win._file_path == root
    assert _stop(win) == (1, "(missing bookmark)")
    assert view._toast_text == "nowhere.grafli is gone"
    assert not (tmp_path / "Lone-res" / "nowhere.grafli").exists()
    win.close()


def _panel_texts(win: MainWindow) -> list[str]:
    from PySide6.QtWidgets import QLabel
    from grafli.flowspanel import FlowsPanel
    panel = win.findChild(FlowsPanel)
    panel.refresh()
    return [lbl.text() for lbl in panel.findChildren(QLabel)
            if lbl.isVisibleTo(panel)]


def test_the_flows_panel_shows_where_the_tour_waits(tmp_path: Path):
    root, combat, _, detail = _system(tmp_path)
    win = _window(root)
    view = win._view
    view.play_flow("tour")
    _key(win, Qt.Key.Key_Space)
    view._box_items["detail"].setSelected(True)
    _key(win, Qt.Key.Key_G, Qt.Key.Key_D)
    assert win._file_path == detail
    hint = "Tour “A blow lands” paused at stop 2/3 — gu resumes it"
    assert hint in _panel_texts(win)
    _key(win, Qt.Key.Key_G, Qt.Key.Key_U)
    assert hint not in _panel_texts(win)
    win.close()


def test_the_flows_panel_names_a_stop_in_another_board(tmp_path: Path):
    from grafli.flowspanel import FlowsPanel
    root, _, _, _ = _system(tmp_path)
    win = _window(root)
    panel = win.findChild(FlowsPanel)
    panel._expanded_flows.add("tour")
    texts = _panel_texts(win)
    assert "↪ c1  in combat" in texts
    assert not any(t.startswith("⚠") for t in texts)
    win.close()
