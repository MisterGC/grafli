"""Whiteboard desktop app — MainWindow and entry point."""

from __future__ import annotations

import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QToolBar,
)

from whiteboard.constants import COLOR_PALETTE, Mode, _resolve_color
from whiteboard.filewatcher import JsonSafeWatcher
from whiteboard.format import Board, parse, serialize
from whiteboard.items import BoxItem, NoteItem
from whiteboard.view import WhiteboardView


# ── Main window ─────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, file_path: str | None = None):
        super().__init__()
        self.setWindowTitle("Whiteboard")
        self.resize(1200, 800)

        self._view = WhiteboardView(self)
        self.setCentralWidget(self._view)

        self._file_path: Path | None = None
        self._board: Board | None = None
        self._watcher: JsonSafeWatcher | None = None

        self._autosave_timer = QTimer(self)

        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._autosave)
        self._last_written = ""

        self._setup_toolbar()
        self._setup_actions()
        self._setup_status_bar()

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
            return "Whiteboard — untitled"
        label = f"{path.parent.name}/{path.name}"
        return f"Whiteboard — {label}{'*' if dirty else ''}"

    def _setup_toolbar(self):
        toolbar = QToolBar("Tools", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        group = QActionGroup(self)
        group.setExclusive(True)

        modes = [
            ("Select (V)", Mode.SELECT),
            ("Rect (R)", Mode.RECT),
            ("Text (T)", Mode.TEXT),
            ("Connect (C)", Mode.CONNECT),
        ]

        self._mode_actions: dict[Mode, QAction] = {}
        for label, mode in modes:
            action = QAction(label, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked, m=mode: self._view.set_mode(m))
            group.addAction(action)
            toolbar.addAction(action)
            self._mode_actions[mode] = action

        self._mode_actions[Mode.SELECT].setChecked(True)

        toolbar.addSeparator()

        # Color button
        self._color_action = QAction("Color", self)
        color_menu = QMenu(self)
        for name, color_str in COLOR_PALETTE:
            action = color_menu.addAction(name)
            hex_color = _resolve_color(color_str)
            if hex_color:
                px = QPixmap(16, 16)
                px.fill(QColor(hex_color))
                action.setIcon(QIcon(px))
            action.triggered.connect(
                lambda checked, c=color_str: self._apply_color_to_selected(c)
            )
        self._color_action.setMenu(color_menu)
        toolbar.addAction(self._color_action)

        # Anchor dropdown
        self._anchor_action = QAction("Anchor", self)
        anchor_menu = QMenu(self)
        for name, value in [("Center", ""), ("Top Left", "topleft"), ("Top Center", "topcenter")]:
            action = anchor_menu.addAction(name)
            action.triggered.connect(
                lambda checked, a=value: self._apply_anchor_to_selected(a)
            )
        self._anchor_action.setMenu(anchor_menu)
        toolbar.addAction(self._anchor_action)

        # Size dropdown
        self._textsize_action = QAction("Size", self)
        textsize_menu = QMenu(self)
        for name, value in [("Small", "small"), ("Medium", ""), ("Large", "large"), ("XL", "xlarge"), ("XXL", "xxlarge")]:
            action = textsize_menu.addAction(name)
            action.triggered.connect(
                lambda checked, s=value: self._apply_textsize_to_selected(s)
            )
        self._textsize_action.setMenu(textsize_menu)
        toolbar.addAction(self._textsize_action)

        # Sync toolbar checkmarks when mode changes programmatically
        self._view.mode_changed.connect(self._on_mode_changed)

    def _on_mode_changed(self, mode: Mode):
        action = self._mode_actions.get(mode)
        if action:
            action.setChecked(True)
        self._status_mode.setText(mode.value.upper())

    def _apply_color_to_selected(self, color: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_color(color)
            elif isinstance(item, NoteItem):
                item.set_color(color)
        self._view.mark_dirty()

    def _apply_anchor_to_selected(self, anchor: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_anchor(anchor)
        self._view.mark_dirty()

    def _apply_textsize_to_selected(self, textsize: str):
        self._view._push_undo()
        for item in self._view.scene().selectedItems():
            if isinstance(item, BoxItem):
                item.set_textsize(textsize)
            elif isinstance(item, NoteItem):
                item.set_textsize(textsize)
        self._view.mark_dirty()

    def _setup_actions(self):
        menu = self.menuBar().addMenu("&File")

        new_action = QAction("&New", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_file)
        menu.addAction(new_action)

        open_action = QAction("&Open...", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_dialog)
        menu.addAction(open_action)

        save_action = QAction("&Save", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_file)
        menu.addAction(save_action)

        menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)

        # Edit menu
        edit_menu = self.menuBar().addMenu("&Edit")

        undo_action = QAction("&Undo", self)
        undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        undo_action.triggered.connect(self._view._undo)
        edit_menu.addAction(undo_action)

        redo_action = QAction("&Redo", self)
        redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        redo_action.triggered.connect(self._view._redo)
        edit_menu.addAction(redo_action)

        edit_menu.addSeparator()

        copy_action = QAction("&Copy", self)
        copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        copy_action.triggered.connect(self._view._copy_selected)
        edit_menu.addAction(copy_action)

        paste_action = QAction("&Paste", self)
        paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        paste_action.triggered.connect(self._view._paste)
        edit_menu.addAction(paste_action)

        # View menu
        view_menu = self.menuBar().addMenu("&View")

        grid_action = QAction("Show &Grid", self)
        grid_action.setCheckable(True)
        grid_action.setChecked(True)
        grid_action.triggered.connect(self._view.toggle_grid)
        view_menu.addAction(grid_action)

        # Zoom shortcuts
        zoom_in = QAction("Zoom In", self)
        zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        zoom_in.triggered.connect(self._zoom_in)
        self.addAction(zoom_in)

        zoom_out = QAction("Zoom Out", self)
        zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        zoom_out.triggered.connect(self._zoom_out)
        self.addAction(zoom_out)

        zoom_fit = QAction("Zoom to Fit", self)
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
        self._status_zoom = QLabel("100%")
        self._status_pos = QLabel("0, 0")
        self._status_sel = QLabel("")

        self._status_warn = QLabel("")
        self._status_warn.setStyleSheet("color: #e04040; font-weight: bold;")

        self.statusBar().addWidget(self._status_mode)
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
            self, "Open Board", "", "Board Files (*.board);;All Files (*)"
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path):
        if not path.exists():
            # Create an empty board file
            path.write_text("# Untitled Board\n")

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
                self, "Save Board", "", "Board Files (*.board);;All Files (*)"
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
    app = QApplication(sys.argv)
    app.setApplicationName("Whiteboard")
    _register_bundled_fonts()

    # Let Ctrl+C quit the app cleanly
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Timer gives Python a chance to process the signal inside Qt's loop
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    window = MainWindow(file_path)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
