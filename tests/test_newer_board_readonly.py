"""A board whose `#!grafli vN` is newer than this build opens read-only
(#158): a toast names the version, and nothing — autosave, save, open
migration, `grafli fmt`, `grafli diagnose --fix` — writes the file."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow, _cmd_diagnose, _cmd_fmt

# v9 syntax this build doesn't know, an unattached annotation (which the
# open migration would move into a vault doc) and off-grid coordinates
# (which fmt would quantize).
NEWER = ('#!grafli v9\n'
         '@ box a "A" 0.4,0 100x100 # legacy annotation\n'
         '@ box b "B" 200,0 100x100\n'
         '@ arrow a -> b ~id=calls\n'
         '@ lens deep @a\n')


def _app():
    return QApplication.instance() or QApplication([])


def _open(tmp_path: Path, text: str = NEWER) -> tuple[MainWindow, Path]:
    _app()
    f = tmp_path / "board.grafli"
    f.write_text(text)
    return MainWindow(str(f)), f


def test_newer_board_opens_with_a_toast_naming_the_version(tmp_path):
    win, f = _open(tmp_path)
    assert "read-only" in win._view._toast_text
    assert "v9" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    # Open must not migrate the annotation into the vault.
    assert f.read_text() == NEWER
    assert not (tmp_path / "board-res").exists()


def test_newer_board_edits_are_not_written(tmp_path):
    win, f = _open(tmp_path)
    win.board.box_by_id("b").label = "edited"
    win._view.mark_dirty()
    assert win._write_file(manual=True) is False
    assert "changes are not saved" in win._view._toast_text
    win._autosave()
    assert f.read_text() == NEWER


def test_known_board_still_saves(tmp_path):
    text = '#!grafli v2\n@ box a "A" 0,0 100x100\n@ bookmark bm "S" @a\n'
    win, f = _open(tmp_path, text)
    assert "[read-only]" not in win.windowTitle()
    win.board.box_by_id("a").label = "edited"
    win._view.mark_dirty()
    assert win._write_file() is True
    assert f.read_text().startswith('#!grafli v2\n@ box a "edited"')


def test_board_turning_newer_on_disk_stops_saving(tmp_path):
    win, f = _open(tmp_path, '#!grafli v1\n@ box a "A" 0,0 100x100\n')
    f.write_text(NEWER)
    win._on_file_changed()
    assert "read-only" in win._view._toast_text
    win.board.box_by_id("a").label = "edited"
    win._view.mark_dirty()
    assert win._write_file() is False
    assert f.read_text() == NEWER


def test_fmt_leaves_newer_board_untouched(tmp_path, capsys):
    f = tmp_path / "board.grafli"
    f.write_text(NEWER)
    assert _cmd_fmt([str(f)]) == 2
    assert f.read_text() == NEWER
    assert "v9" in capsys.readouterr().err


def test_diagnose_fix_leaves_newer_board_untouched(tmp_path, capsys):
    f = tmp_path / "board.grafli"
    # Overlapping boxes: a fixable finding diagnose --fix would rewrite.
    text = ('#!grafli v9\n@ box a "A" 0,0 100x100\n'
            '@ box b "B" 10,10 100x100\n')
    f.write_text(text)
    _cmd_diagnose([str(f), "--fix"])
    assert f.read_text() == text
    assert "not fixed" in capsys.readouterr().err


def test_a_v3_build_opens_a_card_board_read_only(tmp_path, monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = ('#!grafli v4\n@ box c "Card" 0,0 200x150 !card\n'
            '@ note n 20,60 "body" >c\n')
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "v4" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()


def test_a_v3_build_opens_an_ink_board_read_only(tmp_path, monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = ('#!grafli v4\n@ box b "Dark" 0,0 200x80 %primary !ink\n'
            '@ note n 0,120 "rose text" %rose !ink\n')
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "v4" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    assert f.read_text() == text


def test_a_v3_build_opens_a_sans_board_read_only(tmp_path, monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = '#!grafli v4\n@ box b "Title" 0,0 200x80 !sans\n'
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "v4" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    assert f.read_text() == text


def test_a_v3_build_opens_a_sans_note_board_read_only(tmp_path, monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = '#!grafli v4\n@ note n 0,0 "A sans note" !sans\n'
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    assert f.read_text() == text


def test_a_v3_build_opens_an_outline_board_read_only(tmp_path, monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = '#!grafli v4\n@ box b "Later" 0,0 200x80 !dashed\n'
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "v4" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    assert f.read_text() == text


def test_a_v3_build_opens_a_number_marker_board_read_only(tmp_path,
                                                          monkeypatch):
    from grafli import format as fmt
    features = {k: v for k, v in fmt.VERSION_FEATURES.items()
                if v[0] < 4}
    monkeypatch.setattr(fmt, "VERSION_FEATURES", features)
    text = ('#!grafli v4\n@ box b "Step" 0,0 80x80 *solid-3\n'
            '@ box z "Start" 0,120 80x80 *0\n')
    win, f = _open(tmp_path, text)
    assert "read-only" in win._view._toast_text
    assert "v4" in win._view._toast_text
    assert "[read-only]" in win.windowTitle()
    assert f.read_text() == text
