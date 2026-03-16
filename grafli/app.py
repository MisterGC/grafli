"""Grafli desktop app — MainWindow and entry point."""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QFontDatabase,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
)

from grafli.constants import Mode
from grafli.filewatcher import JsonSafeWatcher
from grafli.format import Board, parse, serialize
from grafli.view import GrafliView


# ── Main window ─────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, file_path: str | None = None, *, debug: bool = False):
        super().__init__()
        self.setWindowTitle("Grafli")
        self.resize(1200, 800)

        self._view = GrafliView(self)
        if debug:
            self._view._debug_overlay = True
        self.setCentralWidget(self._view)

        self._file_path: Path | None = None
        self._board: Board | None = None
        self._watcher: JsonSafeWatcher | None = None

        self._autosave_timer = QTimer(self)

        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._autosave)
        self._last_written = ""

        self._setup_shortcuts()
        self._setup_status_bar()
        self.menuBar().setVisible(False)

        self._pending_zoom_fit = bool(file_path)

        if file_path:
            self._open_file(Path(file_path))

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending_zoom_fit:
            self._pending_zoom_fit = False
            QTimer.singleShot(0, lambda: self._zoom_fit(animate=False))

    def _title_for_path(self, path: Path | None, dirty: bool = False) -> str:
        if path is None:
            return "Grafli — untitled"
        label = f"{path.parent.name}/{path.name}"
        return f"Grafli — {label}{'*' if dirty else ''}"

    def _on_mode_changed(self, mode: Mode):
        label = mode.value.upper()
        if self._view._sticky_mode and mode in (Mode.RECT, Mode.TEXT):
            label += "+"
        self._status_mode.setText(label)

    def _setup_shortcuts(self):
        self._view.mode_changed.connect(self._on_mode_changed)

        shortcuts = [
            (QKeySequence.StandardKey.New, self._new_file),
            (QKeySequence.StandardKey.Open, self._open_dialog),
            (QKeySequence.StandardKey.Save, self._save_file),
            (QKeySequence.StandardKey.Quit, self.close),
            (QKeySequence.StandardKey.Undo, self._view._undo),
            (QKeySequence.StandardKey.Redo, self._view._redo),
            (QKeySequence.StandardKey.Copy, self._view._copy_selected),
            (QKeySequence.StandardKey.Paste, self._view._paste),
            (QKeySequence.StandardKey.ZoomIn, self._zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self._zoom_out),
        ]
        for key, slot in shortcuts:
            action = QAction(self)
            action.setShortcut(key)
            action.triggered.connect(slot)
            self.addAction(action)

        zoom_fit = QAction(self)
        zoom_fit.setShortcut(QKeySequence("Ctrl+0"))
        zoom_fit.triggered.connect(self._zoom_fit)
        self.addAction(zoom_fit)

    def _zoom_in(self):
        self._view.scale(1.15, 1.15)
        self._view._update_status_zoom()

    def _zoom_out(self):
        self._view.scale(1 / 1.15, 1 / 1.15)
        self._view._update_status_zoom()

    def _zoom_fit(self, animate: bool = True):
        if self._board and (self._board.boxes or self._board.notes):
            rect = self._view.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
            if animate:
                self._view._animate_to_rect(rect)
            else:
                self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                self._view._update_status_zoom()

    def _setup_status_bar(self):
        self._status_mode = QLabel("SELECT")
        self._status_breadcrumb = QLabel("")
        self._status_breadcrumb.setStyleSheet("color: #888888;")
        self._status_zoom = QLabel("100%")
        self._status_pos = QLabel("0, 0")
        self._status_sel = QLabel("")

        self._status_focus = QLabel("")
        self._status_focus.setStyleSheet("color: #6A9FB5; font-weight: bold;")

        self._status_warn = QLabel("")
        self._status_warn.setStyleSheet("color: #e04040; font-weight: bold;")

        self.statusBar().addWidget(self._status_mode)
        self.statusBar().addWidget(self._status_breadcrumb)
        self.statusBar().addWidget(self._status_focus)
        self.statusBar().addPermanentWidget(self._status_warn)
        self.statusBar().addPermanentWidget(self._status_sel)
        self.statusBar().addPermanentWidget(self._status_pos)
        self.statusBar().addPermanentWidget(self._status_zoom)

    def _new_file(self):
        if self._view.dirty and not self._confirm_discard():
            return
        self._board = Board()
        self._file_path = None
        self._stop_watching()
        self._view.load_board(self._board)
        self._view.mark_clean()
        self.setWindowTitle(self._title_for_path(None))

    def _open_dialog(self):
        if self._view.dirty and not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "", "Grafli files (*.grafli);;Legacy board files (*.board);;All Files (*)"
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path):
        if not path.exists():
            # Create an empty board file
            path.write_text("#!grafli v1\n# Untitled\n")

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")
            return

        self._file_path = path
        self._board = parse(text)
        self._view.load_board(self._board)
        self._view.mark_clean()
        self.setWindowTitle(self._title_for_path(path))
        self._start_watching()
        self._zoom_fit(animate=False)

    def _schedule_autosave(self):
        if self._file_path:
            self._autosave_timer.start()

    def _autosave(self):
        if self._board and self._file_path:
            self._write_file()

    def _write_file(self):
        if not self._board or not self._file_path:
            return
        text = serialize(self._board)
        self._last_written = text
        self._file_path.write_text(text, encoding="utf-8")
        self._view._dirty = False
        if self._file_path:
            self.setWindowTitle(self._title_for_path(self._file_path))

    def _save_file(self):
        if not self._board:
            return
        if not self._file_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save File", "", "Grafli files (*.grafli);;All Files (*)"
            )
            if not path:
                return
            self._file_path = Path(path)
            self._start_watching()

        self._write_file()

    def _start_watching(self):
        self._stop_watching()
        if not self._file_path:
            return
        self._watcher = JsonSafeWatcher(str(self._file_path))
        self._watcher.file_changed.connect(self._on_file_changed)
        self._watcher.start()

    def _stop_watching(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _on_file_changed(self):
        if not self._file_path or not self._file_path.exists():
            return
        try:
            text = self._file_path.read_text(encoding="utf-8")
        except OSError:
            return
        if text == self._last_written:
            return

        new_board = parse(text)

        # Smart merge: keep local positions for boxes that exist in both,
        # pick up new elements and drop removed ones from the file.
        if self._board:
            old_positions = {
                b.id: (b.x, b.y) for b in self._board.boxes
            }
            for box in new_board.boxes:
                if box.id in old_positions:
                    box.x, box.y = old_positions[box.id]

        self._board = new_board
        self._view.load_board(self._board)
        self._view.mark_clean()

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        if self._view.dirty:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Save before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        self._stop_watching()
        super().closeEvent(event)


# ── Entry point ─────────────────────────────────────────────────

def _register_bundled_fonts():
    fonts_dir = Path(__file__).parent / "fonts"
    for name in ("PatrickHand-Regular.ttf", "JetBrainsMonoNerdFont-Regular.ttf"):
        path = fonts_dir / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def main():
    parser = argparse.ArgumentParser(description="Grafli whiteboard")
    parser.add_argument("file", nargs="?", default=None, help="File to open")
    parser.add_argument("--debug", action="store_true", help="Enable debug overlay")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Grafli")
    _register_bundled_fonts()

    # Let Ctrl+C quit the app cleanly
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Timer gives Python a chance to process the signal inside Qt's loop
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    window = MainWindow(args.file, debug=args.debug)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
