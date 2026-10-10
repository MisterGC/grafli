"""`A` cycles off → Connectivity → each overlay file → off (#168)."""

from __future__ import annotations

import json
import os
import subprocess

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication

from grafli.format import parse
from grafli.heat import DegreeProvider
from grafli.overlay_file import OverlayProvider
from grafli.view import GrafliView

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_BOARD = """\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ box c "C" 600,0 120x60
@ arrow a -> b ""
@ arrow b -> c ""
@ note n 0,200 "a remark"
"""

TESTS = {
    "title": "Tests",
    "producer": "scripts/overlay_tests.py",
    "kind": "category",
    "categories": [
        {"id": "pass", "label": "Passing", "color": "#00ff00"},
        {"id": "fail", "label": "Failing", "color": "#ff0000"},
    ],
    "entries": {
        "a": {"category": "fail", "note": "drifts", "refs": ["@src/a.py:3"]},
        "b": {"category": "pass"},
    },
}

CHURN = {
    "title": "Churn",
    "kind": "value",
    "scale": {"min": 0, "max": 10},
    "entries": {"b": {"value": 10}},
}


def _view(tmp_path, src: str = _BOARD, **overlays) -> GrafliView:
    QApplication.instance() or QApplication([])
    board = tmp_path / "map.grafli"
    board.write_text(src)
    if overlays:
        vault = tmp_path / "map-res"
        vault.mkdir(exist_ok=True)
        for name, data in overlays.items():
            _write(tmp_path, name, data)
    view = GrafliView()
    view._file_path = board      # the view is its own window here
    view.load_board(parse(src))
    view.resize(900, 600)
    return view


def _write(tmp_path, name, data):
    path = tmp_path / "map-res" / f"{name}.overlay.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def _key(view, key=Qt.Key.Key_A):
    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key,
                                 Qt.KeyboardModifier.NoModifier))


def _fill(view, box_id):
    brush = view._box_items[box_id].brush()
    return brush.style(), brush.color().name()


class _RecordingPainter(QPainter):
    def __init__(self, device):
        super().__init__(device)
        self.texts: list[str] = []

    def drawText(self, *args):
        self.texts.append(args[-1])
        super().drawText(*args)


def _legend_texts(view) -> list[str]:
    img = QImage(900, 600, QImage.Format.Format_ARGB32)
    painter = _RecordingPainter(img)
    try:
        view._draw_overlay_legend(painter)
    finally:
        painter.end()
    return painter.texts


def test_a_cycles_connectivity_then_each_file_by_name_then_off(tmp_path):
    view = _view(tmp_path, tests=TESTS, churn=CHURN)

    _key(view)
    assert isinstance(view._heat_provider, DegreeProvider)
    assert view._toast_text == "Connectivity"
    _key(view)
    assert view._heat_provider.overlay.name == "churn"
    assert view._toast_text == "Overlay: Churn"
    _key(view)
    assert view._heat_provider.overlay.name == "tests"
    _key(view)
    assert not view._complexity_active
    assert view._toast_text == "Overlays off"


def test_a_category_file_colours_the_right_boxes_and_missing_ids_are_no_data(
        tmp_path):
    view = _view(tmp_path, tests=TESTS)
    _key(view)
    _key(view)

    assert _fill(view, "a") == (Qt.BrushStyle.SolidPattern, "#ff0000")
    assert _fill(view, "b") == (Qt.BrushStyle.SolidPattern, "#00ff00")
    assert _fill(view, "c")[0] == Qt.BrushStyle.BDiagPattern


def test_a_value_file_colours_by_its_scale_and_missing_ids_are_no_data(
        tmp_path):
    view = _view(tmp_path, churn=CHURN)
    _key(view)
    _key(view)

    hot = view._heat_to_color(1.0).name()
    assert _fill(view, "b") == (Qt.BrushStyle.SolidPattern, hot)
    assert _fill(view, "a")[0] == Qt.BrushStyle.BDiagPattern
    assert _fill(view, "c")[0] == Qt.BrushStyle.BDiagPattern


def test_leaving_the_overlay_restores_the_board(tmp_path):
    view = _view(tmp_path, tests=TESTS)
    before = _fill(view, "c")
    for _ in range(3):
        _key(view)

    assert not view._complexity_active
    assert _fill(view, "c") == before


def test_editing_the_shown_file_recolours_the_board(tmp_path):
    view = _view(tmp_path, tests=TESTS)
    _key(view)
    _key(view)
    assert _fill(view, "c")[0] == Qt.BrushStyle.BDiagPattern

    edited = json.loads(json.dumps(TESTS))
    edited["entries"]["c"] = {"category": "fail"}
    _write(tmp_path, "tests", edited)
    view._overlay_watcher._check()     # one poll of the file watcher

    assert _fill(view, "c") == (Qt.BrushStyle.SolidPattern, "#ff0000")


def test_a_shown_file_that_breaks_turns_the_overlay_off(tmp_path):
    view = _view(tmp_path, tests=TESTS)
    _key(view)
    _key(view)

    _write(tmp_path, "tests", "{")
    view._overlay_watcher._check()

    assert not view._complexity_active
    assert view._toast_kind == "error"
    assert view._toast_text.startswith("tests.overlay.json: not JSON")


def test_a_broken_file_is_skipped_with_an_error(tmp_path):
    view = _view(tmp_path, broken="[]", tests=TESTS)
    _key(view)
    _key(view)

    assert view._heat_provider.overlay.name == "tests"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_a_revision_behind_head_shows_the_legend_as_stale(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    revs = []
    for text in ("one", "two"):
        (repo / "f.txt").write_text(text)
        _git(repo, "add", "f.txt")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit",
             "-qm", text)
        revs.append(_git(repo, "rev-parse", "HEAD"))
    view = _view(tmp_path, tests={
        **TESTS, "source": {"repo": "repo", "revision": revs[0][:7]}})
    _key(view)
    _key(view)

    texts = _legend_texts(view)
    assert texts[:2] == ["Tests", "scripts/overlay_tests.py"]
    assert " ".join(texts[2:4]) == (
        f"⚠ stale: analysed at {revs[0][:7]}, repo is at {revs[1][:7]}")

    _write(tmp_path, "tests", {
        **TESTS, "source": {"repo": "repo", "revision": revs[1]}})
    view._overlay_watcher._check()
    assert not any("stale" in t for t in _legend_texts(view))


def test_the_legend_shows_categories_and_the_selected_elements_note_and_refs(
        tmp_path, monkeypatch):
    view = _view(tmp_path, tests=TESTS)
    _key(view)
    _key(view)
    assert _legend_texts(view) == ["Tests", "scripts/overlay_tests.py",
                                   "Passing", "Failing", "no data"]

    view._box_items["a"].setSelected(True)
    texts = _legend_texts(view)
    assert texts[-3:] == ["a: Failing", "drifts", "@src/a.py:3"]

    opened = []
    monkeypatch.setattr(view, "_open_code_ref", opened.append)
    rect, _ref = view._overlay_ref_rects[0]
    assert view._overlay_legend_press(rect.center())
    assert opened == [f"@{tmp_path / 'src/a.py'}:3"]

    view._box_items["a"].setSelected(False)
    view._box_items["c"].setSelected(True)
    assert _legend_texts(view)[-1] == "c: no data"


def test_a_board_without_overlay_files_shows_no_extra_ui(tmp_path):
    view = _view(tmp_path)
    _key(view)

    assert view._complexity_active
    assert isinstance(view._heat_provider, DegreeProvider)
    assert view._toast_text == ""
    assert _legend_texts(view) == []
    assert not view._overlay_legend_press(QPointF(800, 500))
    assert getattr(view, "_overlay_watcher", None) is None

    _key(view)
    assert not view._complexity_active
    assert view._toast_text == ""


def test_escape_leaves_an_overlay_and_a_starts_over(tmp_path):
    view = _view(tmp_path, tests=TESTS)
    _key(view)
    _key(view)
    assert isinstance(view._heat_provider, OverlayProvider)

    _key(view, Qt.Key.Key_Escape)
    assert not view._complexity_active
    _key(view)
    assert isinstance(view._heat_provider, DegreeProvider)
