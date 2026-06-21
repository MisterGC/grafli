"""End-to-end concurrency wiring tests against the real MainWindow.

These drive the actual app.py save/reload paths (not just the sync core)
through a simulated external (AI) writer, with no Qt event loop — the
watcher/autosave timers never fire, so the race is deterministic and we
call _write_file / _on_file_changed by hand in the order a real race would
hit them.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from grafli.app import MainWindow


def _app():
    return QApplication.instance() or QApplication([])


def _open(tmp_path: Path) -> tuple[MainWindow, Path]:
    _app()
    f = tmp_path / "board.grafli"
    f.write_text('#!grafli v1\n@ box a "A" 0,0 100x100\n@ box b "B" 200,0 100x100\n')
    return MainWindow(str(f)), f


def test_autosave_does_not_clobber_external_edit(tmp_path):
    """The headline race: an external (AI) write lands, then an in-app edit
    autosaves before the watcher reloads. The save must merge, not clobber."""
    win, f = _open(tmp_path)
    # External AI edit on disk: relabel box b.
    f.write_text('#!grafli v1\n@ box a "A" 0,0 100x100\n@ box b "Renamed by AI" 200,0 100x100\n')
    # Pending in-app edit the watcher hasn't reloaded: drag box a.
    win.board.box_by_id("a").x = 50
    win.board.box_by_id("a").y = 50
    win._view.mark_dirty()
    win._write_file()                       # autosave fires
    disk = f.read_text()
    assert "Renamed by AI" in disk          # AI edit not clobbered
    assert '@ box a "A" 50,50' in disk       # human drag preserved


def test_reload_merges_external_edit_with_local_edits(tmp_path):
    """An external edit arriving via the watcher must fold into, not replace,
    unsaved in-app edits."""
    win, f = _open(tmp_path)
    win._write_file()                       # sync _last_written
    # External AI edit: add a new box c.
    f.write_text(win._last_written.replace(
        '@ box b "B" 200,0 100x100\n',
        '@ box b "B" 200,0 100x100\n@ box c "Added by AI" 400,0 100x100\n'))
    # Local pending edit: move box a.
    win.board.box_by_id("a").x = 99
    win._view.mark_dirty()
    win._on_file_changed()
    assert win.board.box_by_id("c") is not None        # AI add present
    assert win.board.box_by_id("a").x == 99            # local move kept


def test_writes_leave_no_temp_files(tmp_path):
    win, f = _open(tmp_path)
    win.board.box_by_id("a").label = "Edited"
    win._view.mark_dirty()
    win._write_file()
    leftovers = [p.name for p in tmp_path.iterdir() if ".tmp-" in p.name]
    assert leftovers == []
