"""Grafli desktop app — MainWindow and entry point."""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import (
    QAction,
    QFontDatabase,
    QKeySequence,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from grafli.buffers import BufferManager, BufferState, ViewState
from grafli.constants import Mode
from grafli.filewatcher import JsonSafeWatcher
from grafli.format import Board, merge_box_positions, parse, serialize
from grafli.fuzzy import FuzzyItem, FuzzyOverlay
from grafli.sidepanel import PanelToggleButton, SidePanel
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

        # Side panel + toggle button
        self._side_panel = SidePanel(self)
        self._panel_toggle = PanelToggleButton(self._view.viewport())

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._side_panel)
        layout.addWidget(self._view, stretch=1)
        self.setCentralWidget(container)

        # Restore panel visibility from settings (hidden by default)
        settings = QSettings("Grafli", "Grafli")
        panel_visible = settings.value("sidepanel/visible", False, type=bool)
        self._side_panel.setVisible(panel_visible)
        self._setup_panel()

        self._file_path: Path | None = None
        self._watcher: JsonSafeWatcher | None = None
        self._buffers = BufferManager()

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(300)
        self._autosave_timer.timeout.connect(self._autosave)
        self._last_written = ""

        self._presenting = False
        self._present_panel_visible = True
        self._view.playback_ended.connect(self._on_playback_ended)

        self._setup_shortcuts()
        self._setup_status_bar()
        self.menuBar().setVisible(False)

        self._pending_zoom_fit = bool(file_path)

        if file_path:
            self._open_file(Path(file_path))
        else:
            # Start with an empty untitled buffer
            board = Board()
            self._view.load_board(board)
            buf = BufferState(
                file_path=None, last_written="", board=board,
                view_state=ViewState(),
            )
            self._buffers.add(buf)
            self._buffers.switch_to(0)

    @property
    def board(self) -> Board | None:
        return self._view.board

    def showEvent(self, event):
        super().showEvent(event)
        self._panel_toggle.reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pending_zoom_fit and self.isVisible():
            self._pending_zoom_fit = False
            QTimer.singleShot(0, lambda: self._zoom_fit(animate=False))

    def _title_for_path(self, path: Path | None, dirty: bool = False) -> str:
        if path is None:
            return "Grafli — untitled"
        label = f"{path.parent.name}/{path.name}"
        return f"Grafli — {label}{'*' if dirty else ''}"

    def _on_mode_changed(self, mode: Mode):
        self._status_mode.setText(mode.value.upper())
        self._side_panel.update_mode(mode)

    def _setup_panel(self):
        self._panel_toggle.clicked.connect(self._toggle_panel)
        self._panel_toggle.reposition()
        self._side_panel.tool_activated.connect(self._on_tool_activated)
        self._side_panel.update_mode(self._view.mode)
        self._side_panel.update_selection(False)
        self._view.selection_changed_for_panel.connect(
            self._side_panel.update_selection
        )
        self._side_panel.attach_view(self._view)

    def _toggle_panel(self):
        visible = not self._side_panel.isVisible()
        self._side_panel.setVisible(visible)
        QSettings("Grafli", "Grafli").setValue("sidepanel/visible", visible)
        # Keep keyboard focus on the canvas — the panel is mouse-only.
        self._view.setFocus()

    def _on_tool_activated(self, action_id: str):
        self._view.setFocus()
        actions = {
            "mode_select":  lambda: self._view.set_mode(Mode.SELECT),
            "mode_rect":    lambda: self._view.set_mode(Mode.RECT),
            "mode_text":    lambda: self._view.set_mode(Mode.TEXT),
            "mode_connect": lambda: self._view.set_mode(Mode.CONNECT),
            "edit_label":   self._view._edit_selected,
            "delete":       self._view._delete_selected,
            "style":        lambda: self._view._set_box_mode("style"),
            "dimension":    lambda: self._view._set_box_mode("dimension"),
            "undo":         self._view._undo,
            "redo":         self._view._redo,
            "layout":       self._view._layout_selected,
            "slide_ratio":  self._view._snap_selection_to_slide_ratio,
            "lock_ratio":   lambda: self._view._toggle_box_flag("lock_ratio"),
            "scale_fit":    lambda: self._view._toggle_box_flag("scale_children"),
            "search":       self._view._start_search,
            "grid":         self._view.toggle_grid,
            "minimap":      self._view._toggle_minimap,
            "dim_notes":    self._view._toggle_notes_hidden,
            "dim_arrows":   self._view._toggle_arrows_dimmed,
            "complexity":   self._view._toggle_complexity,
            "yank_png":     self._view._yank_png_to_clipboard,
            "export_svg":   self._view._export_svg_file,
        }
        if action_id == "export_flow_pdf":
            self._export_flow_pdf()
            return
        handler = actions.get(action_id)
        if handler:
            handler()

    # ── Present (fullscreen demo) mode ───────────────────────────

    def _present_current(self):
        """F5: present the selected/current flow fullscreen, chrome hidden.

        Starts on the first stop, paused — drive it with Space/←/→ and cycle
        play/loop with p; Esc exits back to the editor.
        """
        if self._presenting:
            self._exit_present()
            return
        board = self.board
        flow_id = None
        if self._view._active_flow is not None:
            flow_id = self._view._active_flow.id
        elif board and board.flows:
            flow_id = board.flows[0].id
        if not flow_id:
            self._view._record_shortcut("no flow to present")
            return

        self._present_panel_visible = self._side_panel.isVisible()
        self._side_panel.hide()
        self.statusBar().hide()
        self._panel_toggle.hide()
        self._presenting = True
        self.showFullScreen()
        self._view.setFocus()
        self._view.play_flow(flow_id)

    def _exit_present(self):
        if not self._presenting:
            return
        self._presenting = False
        if self._view._flow_player is not None:
            self._view._flow_player.stop()
        self.showNormal()
        self._side_panel.setVisible(self._present_panel_visible)
        self.statusBar().show()
        self._panel_toggle.show()
        self._panel_toggle.reposition()
        self._view.setFocus()

    def _on_playback_ended(self):
        # Esc during a presentation stops playback — leave fullscreen too.
        if self._presenting:
            self._exit_present()

    def _export_flow_pdf(self, flow=None):
        """Export ``flow`` to a PDF; when not given, pick one (auto if single)."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        board = self._view.board
        flows = board.flows if board else []
        if not flows:
            self._view._record_shortcut("no flows to export")
            return
        if flow is None:
            if len(flows) == 1:
                flow = flows[0]
            else:
                labels = [f"{f.label}  ({f.id})" for f in flows]
                choice, ok = QInputDialog.getItem(
                    self, "Export flow", "Flow:", labels, 0, False,
                )
                if not ok:
                    return
                flow = flows[labels.index(choice)]

        default_name = ""
        if self._file_path:
            default_name = str(self._file_path.with_name(
                f"{self._file_path.stem}-{flow.id}.pdf"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export flow to PDF", default_name,
            "PDF files (*.pdf);;All Files (*)",
        )
        if not path:
            return
        from grafli.pdfexport import export_flow_to_pdf
        slides, overloaded = export_flow_to_pdf(self._view, flow, path)
        msg = f"PDF exported ({slides} slides)"
        if overloaded:
            msg += f" · {len(overloaded)} overloaded — trim or split"
        self._view._record_shortcut(msg)

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

        present = QAction(self)
        present.setShortcut(QKeySequence("F5"))
        present.triggered.connect(self._present_current)
        self.addAction(present)

        # Buffer shortcuts
        act_fuzzy_picker = QAction(self)
        act_fuzzy_picker.setShortcut(
            QKeySequence("Meta+K") if sys.platform == "darwin"
            else QKeySequence("Ctrl+K")
        )
        act_fuzzy_picker.triggered.connect(self._open_fuzzy_picker)
        self.addAction(act_fuzzy_picker)

        act_toggle_last = QAction(self)
        act_toggle_last.setShortcut(QKeySequence("Ctrl+6"))
        act_toggle_last.triggered.connect(self._toggle_last_buffer)
        self.addAction(act_toggle_last)

    def _zoom_in(self):
        self._view.scale(1.15, 1.15)
        self._view._update_status_zoom()

    def _zoom_out(self):
        self._view.scale(1 / 1.15, 1 / 1.15)
        self._view._update_status_zoom()

    def _zoom_fit(self, animate: bool = True):
        if self.board and (self.board.boxes or self.board.notes):
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

        self._status_buf = QLabel("")
        self._status_buf.setStyleSheet("color: #6A9FB5;")

        self.statusBar().addWidget(self._status_mode)
        self.statusBar().addWidget(self._status_breadcrumb)
        self.statusBar().addWidget(self._status_focus)
        self.statusBar().addPermanentWidget(self._status_warn)
        self.statusBar().addPermanentWidget(self._status_buf)
        self.statusBar().addPermanentWidget(self._status_sel)
        self.statusBar().addPermanentWidget(self._status_pos)
        self.statusBar().addPermanentWidget(self._status_zoom)

    def _update_buf_status(self):
        if self._buffers.count > 1:
            self._status_buf.setText(
                f"[{self._buffers.active_index + 1}/{self._buffers.count}]"
            )
        else:
            self._status_buf.setText("")

    # ── Buffer management ────────────────────────────────────────

    def _new_file(self):
        board = Board()
        vs = ViewState()
        buf = BufferState(
            file_path=None, last_written="", board=board, view_state=vs,
        )
        self._snapshot_current()
        idx = self._buffers.add(buf)
        self._switch_buffer(idx)

    def _open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "",
            "Grafli files (*.grafli);;Legacy board files (*.board);;All Files (*)",
        )
        if path:
            self._open_file(Path(path))

    def _open_file(self, path: Path):
        # If already open, just switch to it
        existing = self._buffers.find_by_path(path)
        if existing >= 0:
            self._snapshot_current()
            self._switch_buffer(existing)
            return

        if not path.exists():
            path.write_text("#!grafli v1\n# Untitled\n")

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "Error", f"Could not open file:\n{e}")
            return

        board = parse(text)
        from grafli.resources import migrate_all
        if migrate_all(path, board):
            text = serialize(board)
            path.write_text(text, encoding="utf-8")
        mtime = self._get_mtime(path)
        vs = ViewState()
        buf = BufferState(
            file_path=path, last_written=text, board=board,
            view_state=vs, file_mtime=mtime,
        )

        self._snapshot_current()
        idx = self._buffers.add(buf)
        self._switch_buffer(idx, zoom_fit=True)

    def _snapshot_current(self):
        """Snapshot the current buffer state before switching away."""
        buf = self._buffers.active
        if buf is None:
            return
        self._view._cancel_interactions()
        self._flush_autosave()
        self._stop_watching()
        buf.view_state = self._view.snapshot_state()
        buf.board = self._view.board or Board()
        buf.file_path = self._file_path
        buf.last_written = self._last_written

    def _switch_buffer(self, index: int, *, zoom_fit: bool = False):
        """Switch the active buffer to the given index."""
        if not self._buffers.switch_to(index):
            return
        buf = self._buffers.active
        if buf is None:
            return

        # Check if file changed on disk while we were away
        if buf.file_path and buf.file_path.exists():
            disk_mtime = self._get_mtime(buf.file_path)
            if disk_mtime > buf.file_mtime:
                try:
                    text = buf.file_path.read_text(encoding="utf-8")
                except OSError:
                    text = None
                if text is not None and text != buf.last_written:
                    new_board = parse(text)
                    # Smart merge positions
                    old_positions = {
                        b.id: (b.x, b.y) for b in buf.board.boxes
                    }
                    for box in new_board.boxes:
                        if box.id in old_positions:
                            box.x, box.y = old_positions[box.id]
                    buf.board = new_board
                    buf.last_written = text
                    buf.view_state.dirty = False
                buf.file_mtime = disk_mtime

        # Set the path before loading so the scene rebuild can resolve image
        # paths (relative to the file's directory) instead of falling back to
        # grey placeholders.
        self._file_path = buf.file_path
        self._view.load_board(buf.board)
        self._view.restore_state(buf.view_state)
        self._last_written = buf.last_written
        self._view.set_mode(Mode.SELECT)

        self._start_watching()
        self.setWindowTitle(
            self._title_for_path(self._file_path, dirty=self._view.dirty)
        )
        self._update_buf_status()

        if zoom_fit:
            # Defer so the viewport has its real size — fitInView with a
            # not-yet-laid-out (or zero-size) viewport lands far zoomed out.
            QTimer.singleShot(0, lambda: self._zoom_fit(animate=False))

    def close_buffer(self):
        """Close the active buffer (called from Q key or programmatically)."""
        if self._buffers.count <= 0:
            return

        if self._view.dirty:
            name = self._file_path.name if self._file_path else "untitled"
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                f"Save '{name}' before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Save:
                self._save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        self._stop_watching()
        idx = self._buffers.active_index
        self._buffers.remove(idx)

        if self._buffers.count == 0:
            # Last buffer closed — create empty
            self._new_file()
        else:
            target = min(idx, self._buffers.count - 1)
            self._buffers._active_index = target
            self._switch_buffer_direct(target)

    def _switch_buffer_direct(self, index: int):
        """Load buffer at index without snapshotting current (already removed)."""
        self._buffers._active_index = index
        buf = self._buffers.active
        if buf is None:
            return

        if buf.file_path and buf.file_path.exists():
            disk_mtime = self._get_mtime(buf.file_path)
            if disk_mtime > buf.file_mtime:
                try:
                    text = buf.file_path.read_text(encoding="utf-8")
                except OSError:
                    text = None
                if text is not None and text != buf.last_written:
                    new_board = parse(text)
                    old_positions = {
                        b.id: (b.x, b.y) for b in buf.board.boxes
                    }
                    for box in new_board.boxes:
                        if box.id in old_positions:
                            box.x, box.y = old_positions[box.id]
                    buf.board = new_board
                    buf.last_written = text
                    buf.view_state.dirty = False
                buf.file_mtime = disk_mtime

        # Set the path before loading so image paths resolve during the scene
        # rebuild (see _switch_buffer).
        self._file_path = buf.file_path
        self._view.load_board(buf.board)
        self._view.restore_state(buf.view_state)
        self._last_written = buf.last_written
        self._view.set_mode(Mode.SELECT)
        self._start_watching()
        self.setWindowTitle(
            self._title_for_path(self._file_path, dirty=self._view.dirty)
        )
        self._update_buf_status()

    def _toggle_last_buffer(self):
        prev = self._buffers.prev_index
        if prev >= 0 and prev < self._buffers.count and prev != self._buffers.active_index:
            self._snapshot_current()
            self._switch_buffer(prev)

    # ── Fuzzy finders ────────────────────────────────────────────

    @staticmethod
    def _parent_grafli_name(path: Path) -> str:
        """If *path* lives inside a <stem>-res/ dir, return the parent stem."""
        parent_dir = path.parent.name
        if parent_dir.endswith("-res"):
            return parent_dir[:-4]
        return ""

    def _open_fuzzy_picker(self):
        if self._view._fuzzy_overlay:
            return

        # Collect open buffer paths for dedup
        open_paths: dict[Path, int] = {}
        for i, buf in enumerate(self._buffers.buffers):
            if buf.file_path:
                open_paths[buf.file_path.resolve()] = i

        items: list[FuzzyItem] = []

        # Detect duplicate filenames among open buffers
        buf_names: dict[str, list[int]] = {}
        for i, buf in enumerate(self._buffers.buffers):
            n = buf.file_path.name if buf.file_path else "untitled"
            buf_names.setdefault(n, []).append(i)

        # For duplicates, compute shortest distinguishing parent suffix
        disambig: dict[int, str] = {}
        for indices in buf_names.values():
            if len(indices) < 2:
                continue
            paths = [self._buffers.buffers[i].file_path for i in indices]
            if not all(paths):
                continue
            parent_parts = [list(p.parts[:-1]) for p in paths]
            max_depth = max(len(pp) for pp in parent_parts)
            labels = [str(p.parent) for p in paths]
            for depth in range(1, max_depth + 1):
                labels = [
                    str(Path(*pp[-depth:])) if depth <= len(pp)
                    else str(paths[j].parent)
                    for j, pp in enumerate(parent_parts)
                ]
                if len(set(labels)) == len(labels):
                    break
            for j, i in enumerate(indices):
                disambig[i] = labels[j]

        # Open buffers first
        for i, buf in enumerate(self._buffers.buffers):
            name = buf.file_path.name if buf.file_path else "untitled"
            if i in disambig:
                name = f"{name} ({disambig[i]})"
            dirty = "*" if buf.view_state.dirty else ""
            if i == self._buffers.active_index and self._view.dirty:
                dirty = "*"
            current = " [current]" if i == self._buffers.active_index else ""
            parent = self._parent_grafli_name(buf.file_path) if buf.file_path else ""
            child_tag = f" [child of {parent}]" if parent else ""
            items.append(FuzzyItem(
                display=f"{name}{dirty}",
                detail=f"[open]{child_tag}{current}",
                data=("buffer", i),
            ))

        # Remaining .grafli files from cwd
        cwd = Path.cwd()
        grafli_files = sorted(
            (p for p in cwd.rglob("*.grafli")
             if ".git" not in p.parts and "__pycache__" not in p.parts),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for p in grafli_files:
            if p.resolve() in open_paths:
                continue
            try:
                rel = p.relative_to(cwd)
            except ValueError:
                rel = p
            parent = self._parent_grafli_name(p)
            detail = f"[child of {parent}]" if parent else ""
            items.append(FuzzyItem(
                display=str(rel),
                detail=detail,
                data=("file", p),
            ))

        overlay = FuzzyOverlay("Open / Switch", items, self._view.viewport())
        overlay.selected.connect(self._on_fuzzy_selected)
        overlay.cancelled.connect(self._on_fuzzy_cancelled)
        self._view._fuzzy_overlay = overlay

    def _on_fuzzy_selected(self, item: FuzzyItem):
        self._view._fuzzy_overlay = None
        kind, value = item.data
        if kind == "buffer":
            if value != self._buffers.active_index:
                self._snapshot_current()
                self._switch_buffer(value)
        else:
            self._open_file(value)

    def _on_fuzzy_cancelled(self):
        self._view._fuzzy_overlay = None

    # ── File operations ──────────────────────────────────────────

    def _flush_autosave(self):
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._autosave()

    def _schedule_autosave(self):
        if self._file_path:
            self._autosave_timer.start()

    def _autosave(self):
        if self.board and self._file_path:
            self._write_file()

    def _write_file(self):
        if not self.board or not self._file_path:
            return
        text = serialize(self.board)
        self._last_written = text
        self._file_path.write_text(text, encoding="utf-8")
        self._view._dirty = False
        # Update mtime in active buffer
        buf = self._buffers.active
        if buf:
            buf.file_mtime = self._get_mtime(self._file_path)
            buf.last_written = text
        if self._file_path:
            self.setWindowTitle(self._title_for_path(self._file_path))

    def _save_file(self):
        if not self.board:
            return
        if not self._file_path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save File", "",
                "Grafli files (*.grafli);;All Files (*)",
            )
            if not path:
                return
            self._file_path = Path(path)
            buf = self._buffers.active
            if buf:
                buf.file_path = self._file_path
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

        # External edits (e.g. AI tools writing the file) must update box
        # positions on screen. The in-memory positions may differ from
        # disk because the user dragged boxes in-app — keep those drags
        # only when the disk position itself didn't change.
        if self.board:
            try:
                prev_disk = parse(self._last_written) if self._last_written else None
            except Exception:
                prev_disk = None
            merge_box_positions(new_board, prev_disk, self.board)

        self._view.load_board(new_board)
        self._view.mark_clean()
        self._last_written = text
        buf = self._buffers.active
        if buf:
            buf.file_mtime = self._get_mtime(self._file_path)
            buf.last_written = text

    @staticmethod
    def _get_mtime(path: Path) -> float:
        try:
            return os.stat(path).st_mtime
        except OSError:
            return 0.0

    def _confirm_discard(self) -> bool:
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        return reply == QMessageBox.StandardButton.Discard

    def closeEvent(self, event):
        # Check all buffers for unsaved changes
        self._snapshot_current()
        for i, buf in enumerate(self._buffers.buffers):
            dirty = buf.view_state.dirty
            if i == self._buffers.active_index:
                dirty = self._view.dirty
            if dirty:
                name = buf.file_path.name if buf.file_path else "untitled"
                reply = QMessageBox.question(
                    self,
                    "Unsaved Changes",
                    f"Save '{name}' before closing?",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if reply == QMessageBox.StandardButton.Save:
                    if buf.file_path:
                        text = serialize(buf.board)
                        buf.file_path.write_text(text, encoding="utf-8")
                    else:
                        # Switch to it so user can pick save location
                        self._switch_buffer(i)
                        self._save_file()
                elif reply == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
        QSettings("Grafli", "Grafli").setValue(
            "window/geometry", self.saveGeometry(),
        )
        self._stop_watching()
        super().closeEvent(event)


# ── Entry point ─────────────────────────────────────────────────

_SERVER_NAME = "grafli-instance"


def _register_bundled_fonts():
    fonts_dir = Path(__file__).parent / "fonts"
    for name in ("PatrickHand-Regular.ttf", "JetBrainsMonoNerdFont-Regular.ttf"):
        path = fonts_dir / name
        if path.exists():
            QFontDatabase.addApplicationFont(str(path))


def _try_send_to_existing(file_path: str | None) -> bool:
    """Try to send a file path to an already-running instance.

    Returns True if successful (caller should exit).
    """
    sock = QLocalSocket()
    sock.connectToServer(_SERVER_NAME)
    if not sock.waitForConnected(500):
        return False
    msg = str(Path(file_path).resolve()) if file_path else ""
    sock.write(msg.encode("utf-8"))
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


SKILL_DOCS = """\
Subcommands:
  install   Install the bundled grafli skill for one or more AI tools.
  check     Report install status per tool (and whether a newer version
            is available).
  uninstall Remove the installed grafli skill from one or more tools.

Supported targets (user-level paths follow the agentskills.io convention):

  claude    ~/.claude/skills/grafli/SKILL.md
            https://code.claude.com/docs/en/skills
  codex     ~/.agents/skills/grafli/SKILL.md
            https://developers.openai.com/codex/skills
  opencode  ~/.config/opencode/skills/grafli/SKILL.md
            https://opencode.ai/docs/skills

(OpenCode also reads from `~/.claude/skills/` and `~/.agents/skills/`, so
installing for `claude` or `codex` is automatically picked up by OpenCode.)

Without a subcommand, `grafli skill` prints the bundled SKILL.md to stdout.
"""


def _skill_path() -> Path:
    """Return the path to the bundled SKILL.md."""
    from importlib.resources import files
    return Path(str(files("grafli.skills.grafli") / "SKILL.md"))


def _grafli_version() -> str:
    from grafli._version import __version__
    return __version__


def _cmd_skill(argv: list[str]) -> int:
    # Dispatch sub-subcommands (install / check / uninstall). The bare
    # `grafli skill` form (print SKILL.md to stdout) and its existing
    # flags (`-o`, `--where`) are preserved for backwards compatibility.
    if argv and argv[0] in ("install", "check", "uninstall"):
        sub = argv[0]
        rest = argv[1:]
        if sub == "install":
            return _cmd_skill_install(rest)
        if sub == "check":
            return _cmd_skill_check(rest)
        return _cmd_skill_uninstall(rest)

    parser = argparse.ArgumentParser(
        prog="grafli skill",
        description="Print the bundled grafli AI skill (SKILL.md).",
        epilog=SKILL_DOCS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Write SKILL.md to this path instead of stdout",
    )
    parser.add_argument(
        "--where", action="store_true",
        help="Print the path of the bundled SKILL.md and exit",
    )
    args = parser.parse_args(argv)

    src = _skill_path()
    if args.where:
        print(src)
        return 0
    text = src.read_text(encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
        return 0
    sys.stdout.write(text)
    return 0


# ── grafli skill install / check / uninstall ─────────────────────


def _resolve_targets(positional: str | None) -> list[str]:
    """Map a positional ('all', 'claude', 'codex', 'opencode', or None
    when called from `check` where None means all) to a target list.
    """
    from grafli.skill_install import ALL_TARGETS
    if positional is None or positional == "all":
        return list(ALL_TARGETS)
    if positional not in ALL_TARGETS:
        raise SystemExit(
            f"unknown target: {positional!r} "
            f"(valid: all, {', '.join(ALL_TARGETS)})"
        )
    return [positional]


def _prompt_yes_no(question: str, *, default_yes: bool) -> bool:
    """Tiny y/n prompt. Default is signalled with capital letter."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        try:
            ans = input(f"{question} {suffix} ").strip().lower()
        except EOFError:
            return default_yes
        if not ans:
            return default_yes
        if ans in ("y", "yes"):
            return True
        if ans in ("n", "no"):
            return False


def _cmd_skill_install(argv: list[str]) -> int:
    from grafli.skill_install import (
        compute_status, write_skill, parent_dir_exists,
        OK, STALE, MODIFIED, UNKNOWN, MISSING,
    )

    parser = argparse.ArgumentParser(
        prog="grafli skill install",
        description="Install the bundled grafli skill for one or more AI tools.",
    )
    parser.add_argument(
        "target", nargs="?", default=None,
        help="Target tool (all | claude | codex | opencode). "
             "Omit to be prompted per target.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip all prompts; overwrite existing installs and create "
             "missing parent directories without asking.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show planned actions without writing any files.",
    )
    args = parser.parse_args(argv)

    if args.dry_run and args.force:
        # Harmless combo, but explicit so users don't expect writes.
        print("--dry-run set; --force has no effect on writes.", file=sys.stderr)

    interactive_per_target = args.target is None
    targets = _resolve_targets(args.target)

    if not args.force and not args.dry_run and not sys.stdin.isatty():
        print(
            "grafli skill install: stdin is not a TTY; pass --force to "
            "install non-interactively, or --dry-run to preview.",
            file=sys.stderr,
        )
        return 2

    packaged = _skill_path().read_text(encoding="utf-8")
    version = _grafli_version()

    any_drift = False
    any_action = False

    for t in targets:
        st = compute_status(t, packaged, version)
        # Show context line so the user always sees the destination.
        if st.status == OK:
            print(f"[ok]      {t}: already current at {st.path} (grafli {version})")
            continue
        if st.status == MISSING:
            note = f"will install to {st.path} (grafli {version})"
        elif st.status == STALE:
            note = (
                f"installed {st.installed_version} -> packaged {version}; "
                f"will update {st.path}"
            )
        elif st.status == MODIFIED:
            note = (
                f"local changes detected at {st.path}; "
                f"overwriting will discard them"
            )
        else:  # UNKNOWN
            note = (
                f"existing file at {st.path} was not installed by "
                f"`grafli skill install`; cannot determine source"
            )
        print(f"[{st.status}] {t}: {note}")

        if args.dry_run:
            any_drift = any_drift or st.status != OK
            continue

        # Decide whether to write.
        if args.force:
            do_write = True
        elif interactive_per_target or st.status != MISSING:
            default_yes = st.status in (MISSING, STALE)
            verb = "Install" if st.status == MISSING else "Overwrite"
            do_write = _prompt_yes_no(f"  {verb}?", default_yes=default_yes)
        else:
            do_write = True

        if not do_write:
            print(f"  skipped {t}")
            continue

        # Parent dir check (skip when --force).
        if not args.force and not parent_dir_exists(t):
            print(
                f"  note: parent directory {st.path.parent.parent} does "
                f"not exist (the target tool may not be installed)."
            )
            if not _prompt_yes_no("  create and install anyway?", default_yes=False):
                print(f"  skipped {t}")
                continue

        path = write_skill(t, packaged, version)
        print(f"  wrote {path}")
        any_action = True

    if args.dry_run and any_drift:
        return 1
    return 0


def _cmd_skill_check(argv: list[str]) -> int:
    import json as _json
    from grafli.skill_install import (
        compute_status, DRIFT_STATES, OK, STALE, MODIFIED, UNKNOWN, MISSING,
    )

    parser = argparse.ArgumentParser(
        prog="grafli skill check",
        description="Report install status of the grafli skill per target.",
    )
    parser.add_argument(
        "target", nargs="?", default="all",
        help="Target tool (all | claude | codex | opencode). "
             "Default: all targets.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of a human-readable table.",
    )
    args = parser.parse_args(argv)

    targets = _resolve_targets(args.target)
    packaged = _skill_path().read_text(encoding="utf-8")
    version = _grafli_version()

    statuses = [compute_status(t, packaged, version) for t in targets]

    if args.json:
        print(_json.dumps([s.to_dict() for s in statuses], indent=2))
    else:
        for s in statuses:
            tag = f"[{s.status}]"
            if s.status == OK:
                extra = f"(grafli {s.packaged_version})"
            elif s.status == STALE:
                extra = (
                    f"(installed {s.installed_version} -> "
                    f"packaged {s.packaged_version})"
                )
            elif s.status == MODIFIED:
                extra = f"(installed {s.installed_version}; locally modified)"
            elif s.status == UNKNOWN:
                extra = "(no version marker; unknown provenance)"
            else:  # MISSING
                extra = ""
            print(f"{s.target:<9} {tag:<11} {s.path} {extra}".rstrip())

    has_drift = any(s.status in DRIFT_STATES for s in statuses)
    return 1 if has_drift else 0


def _cmd_skill_uninstall(argv: list[str]) -> int:
    from grafli.skill_install import remove_skill, compute_status, MISSING

    parser = argparse.ArgumentParser(
        prog="grafli skill uninstall",
        description="Remove the installed grafli skill from one or more AI tools.",
    )
    parser.add_argument(
        "target", nargs="?", default=None,
        help="Target tool (all | claude | codex | opencode). "
             "Omit to be prompted per target.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Skip all prompts.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show planned actions without removing any files.",
    )
    args = parser.parse_args(argv)

    interactive_per_target = args.target is None
    targets = _resolve_targets(args.target)

    if not args.force and not args.dry_run and not sys.stdin.isatty():
        print(
            "grafli skill uninstall: stdin is not a TTY; pass --force to "
            "uninstall non-interactively, or --dry-run to preview.",
            file=sys.stderr,
        )
        return 2

    packaged = _skill_path().read_text(encoding="utf-8")
    version = _grafli_version()

    for t in targets:
        st = compute_status(t, packaged, version)
        if st.status == MISSING:
            print(f"[missing] {t}: nothing to remove at {st.path.parent}")
            continue
        print(f"[present] {t}: {st.path.parent} (status: {st.status})")

        if args.dry_run:
            continue

        do_remove = (
            args.force
            or _prompt_yes_no(f"  remove?", default_yes=False)
        )
        if not do_remove:
            print(f"  skipped {t}")
            continue

        removed = remove_skill(t)
        if removed:
            print(f"  removed {st.path.parent}")
        else:
            print(f"  nothing was removed (already gone)")
    return 0


def _cmd_render(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="grafli render",
        description="Render a .grafli file to PNG or SVG without opening a window.",
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument("output", type=Path, help="Output .png or .svg")
    parser.add_argument(
        "--width", type=int, default=None,
        help="Output width in pixels (PNG only; preserves aspect ratio)",
    )
    parser.add_argument(
        "--padding", type=int, default=40,
        help="Padding around the diagram bounds (default 40)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    suffix = args.output.suffix.lower()
    if suffix not in (".png", ".svg"):
        print(f"Unsupported output format: {suffix} (expected .png or .svg)",
              file=sys.stderr)
        return 2

    # Headless rendering needs an offscreen Qt platform.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()

    from grafli.view import GrafliView
    text = args.input.resolve().read_text(encoding="utf-8")
    board = parse(text)
    view = GrafliView()
    view.load_board(board)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".svg":
        svg_bytes = view._render_svg_bytes(padding=args.padding)
        with open(args.output, "wb") as f:
            f.write(bytes(svg_bytes))
    else:
        view._render_png_to_path(
            args.output, padding=args.padding, width=args.width,
        )
    print(f"Wrote {args.output}", file=sys.stderr)
    # Drop the QApplication reference to avoid lingering process state.
    del view
    del app
    return 0


def _cmd_export(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="grafli export",
        description="Export a flow as a slide-style PDF presentation.",
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument("output", type=Path, help="Output .pdf")
    parser.add_argument(
        "--flow", default=None,
        help="Flow id to export (default: the only flow; required if several)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2
    if args.output.suffix.lower() != ".pdf":
        print(f"Unsupported output format: {args.output.suffix} (expected .pdf)",
              file=sys.stderr)
        return 2

    text = args.input.resolve().read_text(encoding="utf-8")
    board = parse(text)
    if not board.flows:
        print("No flows in this file — nothing to export.", file=sys.stderr)
        return 1
    if args.flow:
        flow = board.flow_by_id(args.flow)
        if flow is None:
            ids = ", ".join(f.id for f in board.flows)
            print(f"Flow '{args.flow}' not found. Available: {ids}", file=sys.stderr)
            return 2
    elif len(board.flows) == 1:
        flow = board.flows[0]
    else:
        ids = ", ".join(f.id for f in board.flows)
        print(f"Multiple flows — pass --flow <id>. Available: {ids}",
              file=sys.stderr)
        return 2

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    from grafli.view import GrafliView
    from grafli.pdfexport import export_flow_to_pdf
    view = GrafliView()
    view.load_board(board)
    slides, overloaded = export_flow_to_pdf(view, flow, args.output)
    print(f"Wrote {args.output} ({slides} slides)", file=sys.stderr)
    if overloaded:
        where = ", ".join(f"#{i + 1} {lbl}".strip() for i, lbl in overloaded)
        print(f"Warning: {len(overloaded)} slide(s) overloaded — trim or "
              f"split: {where}", file=sys.stderr)
    del view
    del app
    return 0


def _make_note_rect_provider():
    """Return a callable that computes a note's rendered scene rect.

    Initializes a headless Qt app and registers bundled fonts so
    ``QFontMetrics`` returns accurate widths for Patrick Hand. The
    provider mirrors what ``NoteItem.boundingRect()`` would produce
    on screen, so geometric checks see the rect users actually see.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    from grafli.items import NoteItem

    def provider(note):
        item = NoteItem(note)
        br = item.boundingRect()
        return (note.x, note.y, note.x + br.width(), note.y + br.height())

    return provider


def _make_arrow_label_size_provider():
    """Return a callable that returns an arrow label's rendered size."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    from PySide6.QtGui import QFont, QFontMetricsF
    from grafli.constants import ARROW_LABEL_FONT_SIZES, FONT_FAMILY

    def provider(arrow):
        font = QFont(
            FONT_FAMILY,
            ARROW_LABEL_FONT_SIZES.get(arrow.textsize, ARROW_LABEL_FONT_SIZES[""]),
        )
        fm = QFontMetricsF(font)
        text = arrow.label or ""
        if not text:
            return (0.0, 0.0)
        longest_w = max(fm.horizontalAdvance(line) for line in text.split("\n"))
        height = fm.height() * max(1, len(text.split("\n")))
        return (longest_w, height)

    return provider


def _cmd_diagnose(argv: list[str]) -> int:
    import json as _json
    from grafli.diagnostics import run_all

    parser = argparse.ArgumentParser(
        prog="grafli diagnose",
        description=(
            "Run static layout diagnostics on a .grafli file. "
            "Surfaces children outside parents, sibling overlaps, cramped "
            "containers, likely-truncated labels, and missing linked resources."
        ),
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    text = args.input.read_text(encoding="utf-8")
    board = parse(text)
    note_rect = _make_note_rect_provider()
    arrow_label_size = _make_arrow_label_size_provider()
    diags = run_all(
        board,
        args.input.resolve().parent,
        note_rect=note_rect,
        arrow_label_size=arrow_label_size,
    )

    if args.json:
        print(_json.dumps([d.to_dict() for d in diags], indent=2))
        return 0

    if not diags:
        print("No findings.")
        return 0

    for d in diags:
        suffix = "" if d.fixable else "  (may be intentional)"
        print(f"[{d.severity}] {d.code}: {d.message}{suffix}")
    print(f"\n{len(diags)} finding(s).")
    return 0


def main():
    # Subcommand dispatch — keep the bare `grafli <file>` form unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] in ("skill", "render", "diagnose", "export"):
        sub = sys.argv[1]
        rest = sys.argv[2:]
        if sub == "skill":
            sys.exit(_cmd_skill(rest))
        if sub == "render":
            sys.exit(_cmd_render(rest))
        if sub == "export":
            sys.exit(_cmd_export(rest))
        sys.exit(_cmd_diagnose(rest))

    parser = argparse.ArgumentParser(
        prog="grafli",
        description="Grafli whiteboard. Subcommands: skill, render, diagnose, export.",
    )
    parser.add_argument("file", nargs="?", default=None, help="File to open")
    parser.add_argument("--debug", action="store_true", help="Enable debug overlay")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setApplicationName("Grafli")

    # Single-instance: try to hand off to existing instance
    if args.file and _try_send_to_existing(args.file):
        sys.exit(0)

    _register_bundled_fonts()

    # Let Ctrl+C quit the app cleanly
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    window = MainWindow(args.file, debug=args.debug)
    # Restore saved geometry if it lands on a currently-attached screen;
    # otherwise fall back to maximized on the primary screen so a sleeping
    # or disconnected external display can't swallow the window.
    restored = False
    saved_geom = QSettings("Grafli", "Grafli").value("window/geometry")
    if saved_geom is not None and window.restoreGeometry(saved_geom):
        frame = window.frameGeometry()
        if any(
            s.availableGeometry().intersects(frame) for s in app.screens()
        ):
            restored = True
    if not restored:
        primary = app.primaryScreen()
        if primary is not None:
            window.setGeometry(primary.availableGeometry())
        window.showMaximized()
    else:
        window.show()

    # Single-instance server
    server = QLocalServer()
    server.removeServer(_SERVER_NAME)
    if server.listen(_SERVER_NAME):
        def _on_new_connection():
            conn = server.nextPendingConnection()
            if conn:
                conn.waitForReadyRead(1000)
                data = bytes(conn.readAll()).decode("utf-8").strip()
                conn.disconnectFromServer()
                if data:
                    window._open_file(Path(data))
                window.raise_()
                window.activateWindow()

        server.newConnection.connect(_on_new_connection)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
