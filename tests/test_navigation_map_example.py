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
from grafli import theme
from grafli.format import parse, resolve_code_ref
from grafli.map_palette import load_palette
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
    # The deep link &graph:enter#b_algo frames the algorithm.
    assert win._file_path == level3
    assert _selected(win) == {"algo"}
    assert win._board_path() == ["navigation-map", "Open dispatch",
                                 "_enter_board"]

    _press_gu(win)
    assert win._file_path == level2
    assert _selected(win) == {"enter"}
    _press_gu(win)
    assert win._file_path == root
    assert _selected(win) == {"open"}
    win.close()


REPO = EXAMPLES.parent
_IDENT = re.compile(r"[A-Za-z_][\w.]*(?:\(\))?")
_NOTE_REF = re.compile(r"@(\S+?):(\d+)(?:\s+(\S+))?")
_DOC_REF = re.compile(r"`([\w./-]+\.py):(\d+)(?:-(\d+))?`")


def _board_refs(board_path: Path) -> list[tuple[str, Path, int, int, str]]:
    """(where, file, first line, last line, symbol) of every ``@path:line``
    ref in the notes of a board. The symbol is the identifier written after
    the ref on its line; none written is an empty symbol."""
    refs = []
    board = parse(board_path.read_text(encoding="utf-8"))
    for note in board.notes:
        for text in note.text.splitlines():
            for m in _NOTE_REF.finditer(text):
                line = int(m.group(2))
                path, _ = resolve_code_ref(board, board_path.parent,
                                           m.group(1))
                refs.append((f"{board_path.name} note {note.id}: {text.strip()}",
                             path, line, line, m.group(3) or ""))
    return refs


def _doc_refs(doc_path: Path) -> list[tuple[str, Path, int, int, str]]:
    """The same for the ```path.py:line``` refs in a box doc (repo-relative
    paths, ``a-b`` ranges allowed). The symbol is the last backticked
    identifier before the ref in its paragraph."""
    refs = []
    text = doc_path.read_text(encoding="utf-8")
    for para in re.split(r"\n\s*\n", text):
        for m in _DOC_REF.finditer(para):
            symbol = ""
            for t in re.finditer(r"`([^`]+)`", para[:m.start()]):
                if _IDENT.fullmatch(t.group(1)):
                    symbol = t.group(1)
            first = int(m.group(2))
            refs.append((f"{doc_path.name}: {m.group(0)}", REPO / m.group(1),
                         first, int(m.group(3) or first), symbol))
    return refs


def _all_refs() -> list[tuple[str, Path, int, int, str]]:
    refs = [r for board in BOARDS for r in _board_refs(board)]
    for doc in sorted((EXAMPLES / "navigation-map-res").rglob("*.md")):
        refs.extend(_doc_refs(doc))
    return refs


def test_every_source_ref_points_at_its_symbol():
    """Each ref opens a line within two lines of the symbol its text names;
    a ref whose text names none fails rather than passing unchecked."""
    refs = _all_refs()
    assert len(refs) >= 40, len(refs)
    problems = []
    for where, path, first, last, symbol in refs:
        if len(symbol) < 4:
            problems.append(f"{where}: no symbol of 4+ characters to check "
                            "the ref against")
            continue
        if not path.is_file():
            problems.append(f"{where}: {path} is not a file")
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        window = "\n".join(lines[max(first - 3, 0):last + 2])
        if symbol.removesuffix("()") not in window:
            problems.append(f"{where}: {symbol} not within 2 lines of "
                            f"{path.name}:{first}-{last}")
    assert not problems, "\n".join(problems)


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


def test_every_part_rests_in_its_layer_colour_on_every_level():
    """Each part box on each level names an entry of the map's palette and
    sits its label at the top; the link back to the map is not a part."""
    for board_path in BOARDS:
        names = {e.name for e in load_palette(board_path)}
        assert len(names) >= 3, board_path.name
        for box in parse(board_path.read_text(encoding="utf-8")).boxes:
            if box.attach_kind == "link":
                continue
            assert box.color.removeprefix("%") in names, (board_path.name,
                                                          box.id)
            assert box.anchor == "topcenter", (board_path.name, box.id)


def test_the_opened_map_fills_its_boxes_with_the_layer_colours(tmp_path: Path):
    root = _copy(tmp_path)
    palette = {e.name: e.color for e in load_palette(root)}
    win = _window(root)
    fills = set()
    for bid, item in win._view._box_items.items():
        expected = theme.resolve_color(palette[item.box.color[1:]])
        fill = item.brush().color().name().upper()
        assert fill == expected.upper(), bid
        fills.add(fill)
    assert len(fills) == 4
    win.close()


def test_the_overlay_colours_every_part_of_the_top_level():
    overlay = load_overlay(EXAMPLES / "navigation-map-res" / "tests.overlay.json")
    parts = {b.id for b in parse(ROOT.read_text(encoding="utf-8")).boxes}
    assert set(overlay.entries) == parts
    assert overlay.producer and overlay.revision


def test_the_tour_passes_the_slide_check(capsys):
    from grafli.app import _cmd_export
    assert _cmd_export([str(ROOT), "--flow", "enter", "--check", "--json"]) == 0
    assert '"overloaded": []' in capsys.readouterr().out
