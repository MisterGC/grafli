"""The worked explanation-map example (examples/navigation-map.grafli, #171):
its walk from the overview into the algorithm and back, source refs that
point at real lines, a tour whose stops all resolve across the three levels,
and an overlay keyed by the top level's parts."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow, _step_bookmark
from grafli.format import parse
from grafli.overlay_file import load_overlay

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
ROOT = EXAMPLES / "navigation-map.grafli"
LEVEL2 = EXAMPLES / "navigation-map-res" / "open.grafli"
LEVEL3 = EXAMPLES / "navigation-map-res" / "open-res" / "enter.grafli"
BOARDS = (ROOT, LEVEL2, LEVEL3)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _copy(tmp_path: Path) -> Path:
    """The example in *tmp_path*, so opening it can never touch the repo."""
    shutil.copy(ROOT, tmp_path / ROOT.name)
    shutil.copytree(EXAMPLES / "navigation-map-res",
                    tmp_path / "navigation-map-res")
    return tmp_path / ROOT.name


def _window(path: Path) -> MainWindow:
    app = _app()
    win = MainWindow(str(path))
    win.resize(1200, 800)
    win.show()
    app.processEvents()
    view = win._view
    view._animate_to_rect = lambda rect, **_: view.goto_rect(rect,
                                                             animate=False)
    view.transitions_enabled = lambda: False
    return win


def _enter(win: MainWindow, box_id: str):
    view = win._view
    view._scene.clearSelection()
    view._box_items[box_id].setSelected(True)
    view._open_resource()
    _app().processEvents()


def _press_gu(win: MainWindow):
    QTest.keyClick(win._view, Qt.Key.Key_G)
    QTest.keyClick(win._view, Qt.Key.Key_U)
    _app().processEvents()


def _selected(win: MainWindow) -> set[str]:
    view = win._view
    items = {**view._box_items, **view._note_items}
    return {eid for eid, item in items.items() if item.isSelected()}


def test_walk_from_the_overview_into_the_algorithm_and_back(tmp_path: Path):
    root = _copy(tmp_path)
    level2 = root.parent / "navigation-map-res" / "open.grafli"
    level3 = root.parent / "navigation-map-res" / "open-res" / "enter.grafli"
    win = _window(root)

    _enter(win, "open")
    assert win._file_path == level2
    _enter(win, "enter")
    # The deep link &graph:enter#b_algo frames the algorithm and its refs.
    assert win._file_path == level3
    assert _selected(win) == {"algo", "source"}
    assert win._board_path() == ["navigation-map", "Open dispatch",
                                 "_enter_board"]

    _press_gu(win)
    assert win._file_path == level2
    assert _selected(win) == {"enter"}
    _press_gu(win)
    assert win._file_path == root
    assert _selected(win) == {"open"}
    win.close()


def _code_refs(board_path: Path) -> list[tuple[Path, int]]:
    refs = []
    for note in parse(board_path.read_text(encoding="utf-8")).notes:
        for m in re.finditer(r"@(\S+?):(\d+)", note.text):
            refs.append((board_path.parent / m.group(1), int(m.group(2))))
    return refs


def test_every_source_ref_points_at_a_line_of_a_file():
    refs = [ref for board in BOARDS for ref in _code_refs(board)]
    assert len(refs) >= 15
    for path, line in refs:
        assert path.is_file(), path
        assert line <= len(path.read_text(encoding="utf-8").splitlines()), \
            (path, line)


def test_the_tour_crosses_all_three_levels_and_frames_arrows():
    board = parse(ROOT.read_text(encoding="utf-8"))
    flow = board.flow_by_id("enter")
    homes = set()
    for step in flow.steps:
        bm = _step_bookmark(ROOT, board, step.ref)
        assert bm is not None, step.ref
        homes.add(step.ref.rpartition("#")[0] or "root")
    assert len(homes) == 3
    arrow_ids = {a.id for a in board.arrows if a.id}
    path_stops = [bm for bm in board.bookmarks
                  if set(bm.focus) <= arrow_ids]
    assert len(path_stops) >= 4


def test_the_overlay_colours_every_part_of_the_top_level():
    overlay = load_overlay(EXAMPLES / "navigation-map-res" / "tests.overlay.json")
    parts = {b.id for b in parse(ROOT.read_text(encoding="utf-8")).boxes}
    assert set(overlay.entries) == parts
    assert overlay.producer and overlay.revision
