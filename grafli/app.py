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
    QKeySequence,
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QWidget,
)

import textli

from grafli import theme
from grafli.buffers import BufferManager, BufferState, ViewState
from grafli.constants import Mode
from grafli.fonts import register_bundled_fonts as _register_bundled_fonts
from grafli.filewatcher import JsonSafeWatcher, MultiFileWatcher
from grafli.format import Board, parse, serialize, serialize_to_file
from grafli.sync import Conflict, atomic_write, merge_boards
from grafli.fuzzy import FuzzyItem, FuzzyOverlay
from grafli.sidepanel import PanelToggleButton, SidePanel, ThemeToggleButton
from grafli.view import GrafliView


def running_version() -> str:
    """A label identifying the *running* code. For a packaged install that's
    the version; for an editable/dev checkout the cached version goes stale, so
    show the live git HEAD (branch@sha, ``*`` if dirty) — it changes every
    commit, so a relaunch visibly reflects whether new code was picked up."""
    import os
    import subprocess
    from grafli import __version__
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _git(*a: str) -> str:
        try:
            return subprocess.run(("git", "-C", repo, *a), capture_output=True,
                                  text=True, timeout=2).stdout.strip()
        except Exception:
            return ""

    sha = _git("rev-parse", "--short", "HEAD")
    if not sha:
        return f"v{__version__}"
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "?"
    dirty = "*" if _git("status", "--porcelain") else ""
    return f"{branch}@{sha}{dirty}"


def _sync_editor_theme() -> None:
    """Put textli on the same theme as the board.

    textli owns its own palette and, from 0.6, restyles any open editor in
    place when the host calls this — so the zen and inline editors match the
    canvas they were opened from instead of flashing a bright page over a dark
    board. Its own persistence is standalone-app-only and never overrides us.
    """
    textli.set_theme(theme.name())


# ── Main window ─────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, file_path: str | None = None, *, debug: bool = False):
        super().__init__()
        self.setWindowTitle("Grafli")
        self.resize(1200, 800)

        # Restore the theme before any widget is built — every widget reads the
        # palette as it constructs its stylesheet, so switching afterwards would
        # need a full restyle pass just to reach the state we already know.
        theme.set_theme(QSettings("Grafli", "Grafli").value(
            "theme/name", "light", type=str))
        _sync_editor_theme()

        self._view = GrafliView(self)
        if debug:
            self._view._debug_overlay = True

        # Side panel + floating toggles
        self._side_panel = SidePanel(self)
        self._panel_toggle = PanelToggleButton(self._view.viewport())
        self._theme_toggle = ThemeToggleButton(self._view.viewport())

        # A splitter lets the user drag the panel/canvas boundary. The panel
        # keeps a content-driven minimum width so nothing clips, and a single
        # shared width is remembered across tabs and restarts.
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(4)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._side_panel)
        self._splitter.addWidget(self._view)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        self.setCentralWidget(self._splitter)

        # Restore panel visibility + width from settings (hidden by default)
        settings = QSettings("Grafli", "Grafli")
        panel_visible = settings.value("sidepanel/visible", False, type=bool)
        self._side_panel.setVisible(panel_visible)
        self._panel_width = settings.value(
            "sidepanel/width", self._side_panel.preferred_width(), type=int)
        self._setup_panel()

        self._file_path: Path | None = None
        self._watcher: JsonSafeWatcher | None = None
        self._docs_watcher: MultiFileWatcher | None = None
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
        self._theme_toggle.reposition()
        self._apply_panel_width()

    def _apply_panel_width(self):
        """Size the splitter so the panel takes its remembered shared width."""
        w = max(self._panel_width, self._side_panel.minimumWidth())
        total = self._splitter.width() or (w + 800)
        self._splitter.setSizes([w, max(1, total - w)])

    def _on_splitter_moved(self, pos: int, index: int):
        if self._side_panel.isVisible():
            self._panel_width = self._splitter.sizes()[0]
            QSettings("Grafli", "Grafli").setValue(
                "sidepanel/width", self._panel_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # A pending fit waits here for the viewport to reach its real size;
        # _zoom_fit clears the flag once it actually fits (or re-arms if still
        # too small), so a window-sizing race can't leave the board off-screen.
        if self._pending_zoom_fit and self.isVisible():
            self._zoom_fit(animate=False)

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
        self._theme_toggle.clicked.connect(self._toggle_theme)
        self._theme_toggle.reposition()
        self._side_panel.tool_activated.connect(self._on_tool_activated)
        self._side_panel.update_mode(self._view.mode)
        self._side_panel.update_selection(False)
        self._view.selection_changed_for_panel.connect(
            self._side_panel.update_selection
        )
        self._side_panel.attach_view(self._view)

    def _toggle_theme(self):
        """Flip light <-> dark, remember it, and restyle in place."""
        name = theme.toggle()
        QSettings("Grafli", "Grafli").setValue("theme/name", name)
        self._apply_theme()
        self.statusBar().showMessage(f"{name.capitalize()} theme", 1500)
        self._view.setFocus()

    def _apply_theme(self):
        """Push the active palette through every widget that caches a colour.

        The canvas resolves most colours at paint time, but stylesheets are
        strings built once, so each panel rebuilds its own.
        """
        _sync_editor_theme()
        self._view.apply_theme()
        self._side_panel.apply_theme()
        self._panel_toggle.update()
        self._theme_toggle.apply_theme()
        self._restyle_status_bar()

    def _toggle_panel(self):
        visible = not self._side_panel.isVisible()
        self._side_panel.setVisible(visible)
        if visible:
            self._apply_panel_width()
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
        if action_id == "export_flow_pptx":
            self._export_flow_pptx()
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
            self._view.toast("No flow to present", "warn")
            return

        self._present_panel_visible = self._side_panel.isVisible()
        self._side_panel.hide()
        self.statusBar().hide()
        self._panel_toggle.hide()
        self._theme_toggle.hide()
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
        self._theme_toggle.show()
        self._theme_toggle.reposition()
        self._view.setFocus()

    def _on_playback_ended(self):
        # Esc during a presentation stops playback — leave fullscreen too.
        if self._presenting:
            self._exit_present()

    def _pick_flow(self, flow=None):
        """Return ``flow`` or let the user pick one (auto when there's a single
        flow). Returns None when there are no flows or the picker is cancelled."""
        from PySide6.QtWidgets import QInputDialog
        board = self._view.board
        flows = board.flows if board else []
        if not flows:
            self._view.toast("No flows to export", "warn")
            return None
        if flow is not None:
            return flow
        if len(flows) == 1:
            return flows[0]
        labels = [f"{f.label}  ({f.id})" for f in flows]
        choice, ok = QInputDialog.getItem(
            self, "Export flow", "Flow:", labels, 0, False,
        )
        if not ok:
            return None
        return flows[labels.index(choice)]

    def _export_flow_pdf(self, flow=None):
        """Export ``flow`` to a PDF; when not given, pick one (auto if single)."""
        from PySide6.QtWidgets import QFileDialog
        flow = self._pick_flow(flow)
        if flow is None:
            return
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
        try:
            slides, overloaded = export_flow_to_pdf(self._view, flow, path)
        except Exception as exc:  # surface any render/IO failure
            self._view.toast(f"PDF export failed: {exc}", "error")
            return
        msg = f"PDF exported · {slides} slides"
        if overloaded:
            msg += f" · {len(overloaded)} overloaded — trim or split"
        self._view.toast(msg, "warn" if overloaded else "info")

    def _export_flow_pptx(self, flow=None):
        """Export ``flow`` to an editable PowerPoint; pick the flow (auto if
        single), then a style: a grafli/blank preset, or an existing .pptx
        template whose master, theme and layouts the export drops onto."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        flow = self._pick_flow(flow)
        if flow is None:
            return
        themes = ["grafli  (branded)", "blank  (neutral)",
                  "Use a template…  (your .pptx master)"]
        choice, ok = QInputDialog.getItem(
            self, "Export flow to PPTX", "Style:", themes, 0, False,
        )
        if not ok:
            return
        theme, template, title_layout, content_layout = "grafli", None, None, None
        if choice == themes[1]:
            theme = "blank"
        elif choice == themes[2]:
            template, title_layout, content_layout = self._pick_pptx_template()
            if template is None:
                return
        default_name = ""
        if self._file_path:
            default_name = str(self._file_path.with_name(
                f"{self._file_path.stem}-{flow.id}.pptx"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export flow to PPTX", default_name,
            "PowerPoint files (*.pptx);;All Files (*)",
        )
        if not path:
            return
        from grafli.pptxexport import export_flow_to_pptx
        try:
            slides, overloaded = export_flow_to_pptx(
                self._view, flow, path, theme=theme, template=template,
                title_layout=title_layout, content_layout=content_layout)
        except Exception as exc:  # surface any render/IO failure
            self._view.toast(f"PPTX export failed: {exc}", "error")
            return
        msg = f"PPTX exported · {slides} slides"
        if overloaded:
            msg += f" · {len(overloaded)} overloaded — trim or split"
        self._view.toast(msg, "warn" if overloaded else "info")

    def _pick_pptx_template(self):
        """Choose a .pptx template and the layouts to use for the title and
        content slides. Returns ``(path, title_layout, content_layout)`` with the
        layout names heuristically pre-selected, or ``(None, None, None)`` if
        cancelled."""
        from PySide6.QtWidgets import QFileDialog, QInputDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a .pptx template", "",
            "PowerPoint templates (*.pptx);;All Files (*)",
        )
        if not path:
            return None, None, None
        try:
            from pptx import Presentation
            from grafli.pptxexport import _all_layouts, _resolve_layout
            prs = Presentation(path)
            names = [lo.name for lo in _all_layouts(prs)]
            title_def = _resolve_layout(prs, None, "title").name
            content_def = _resolve_layout(prs, None, "content").name
        except Exception as exc:
            self._view.toast(f"Can't read template: {exc}", "error")
            return None, None, None
        if not names:
            self._view.toast("Template has no slide layouts", "error")
            return None, None, None
        title_layout, ok = QInputDialog.getItem(
            self, "Template layout", "Title-slide layout:", names,
            names.index(title_def), False,
        )
        if not ok:
            return None, None, None
        content_layout, ok = QInputDialog.getItem(
            self, "Template layout", "Content-slide layout:", names,
            names.index(content_def), False,
        )
        if not ok:
            return None, None, None
        return path, title_layout, content_layout

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

        act_theme = QAction(self)
        act_theme.setShortcut(QKeySequence("Ctrl+Shift+D"))
        act_theme.triggered.connect(self._toggle_theme)
        self.addAction(act_theme)

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

    def _warn_parse_issues(self, board):
        """Surface lines the parser couldn't read (and demoted to comments) on
        open/reload — so an AI/hand-edit slip is visible, not silently lost."""
        warnings = getattr(board, "parse_warnings", None)
        if not warnings:
            return
        n = len(warnings)
        # Distinguish "a board with a few bad lines" from "not a board at all"
        # (e.g. a Markdown doc opened by mistake): if there's no `#!grafli`
        # header and the file failed to parse far more lines than it
        # recognized, don't cry "N broken lines" — say it isn't a grafli file.
        recognized = (len(board.boxes) + len(board.arrows) + len(board.notes)
                      + len(board.images) + len(board.bookmarks)
                      + len(board.flows))
        if not getattr(board, "had_header", False) and n >= max(5, 1.5 * recognized):
            total = n + recognized
            self._view.toast(
                f"⚠ This doesn't look like a grafli file — {n} of {total} "
                "lines aren't grafli directives. Opened as an empty board.",
                "warn")
            return
        shown = ", ".join(str(w.line) for w in warnings[:6])
        more = f" (+{len(warnings) - 6} more)" if len(warnings) > 6 else ""
        self._view.toast(
            f"⚠ {n} line{'s' if n != 1 else ''} couldn't be parsed "
            f"({'lines' if n != 1 else 'line'} {shown}{more}) — kept as comments",
            "warn")

    def _zoom_fit(self, animate: bool = True):
        if not (self.board and (self.board.boxes or self.board.notes
                                or self.board.images)):
            return
        vp = self._view.viewport()
        if vp.width() < 50 or vp.height() < 50:
            # Viewport not laid out yet — fitInView would land far off. Defer to
            # the next resize, which fires when the canvas gets its real size.
            self._pending_zoom_fit = True
            return
        rect = self._view.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if animate:
            self._view._animate_to_rect(rect)
        else:
            self._view.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._view._update_status_zoom()
        # Keep re-fitting on resize until the window reaches a real size, so a
        # transient small layout during open doesn't leave the board tiny. Once
        # the window is real-sized the fit is final (no more auto-refit).
        self._pending_zoom_fit = vp.width() < 400 or vp.height() < 300

    def _setup_status_bar(self):
        self._status_mode = QLabel("SELECT")
        self._status_breadcrumb = QLabel("")
        self._status_zoom = QLabel("100%")
        self._status_pos = QLabel("0, 0")
        self._status_sel = QLabel("")
        self._status_focus = QLabel("")
        self._status_lod = QLabel("")
        self._status_warn = QLabel("")
        self._status_buf = QLabel("")

        # Running-code identity (git branch@sha for dev checkouts) — so it's
        # obvious at a glance whether a relaunch picked up new code.
        self._status_version = QLabel(running_version())
        self._status_version.setToolTip("Running grafli build")

        self._restyle_status_bar()

        self.statusBar().addPermanentWidget(self._status_version)
        self.statusBar().addWidget(self._status_mode)
        self.statusBar().addWidget(self._status_breadcrumb)
        self.statusBar().addWidget(self._status_focus)
        self.statusBar().addPermanentWidget(self._status_warn)
        self.statusBar().addPermanentWidget(self._status_buf)
        self.statusBar().addPermanentWidget(self._status_sel)
        self.statusBar().addPermanentWidget(self._status_lod)
        self.statusBar().addPermanentWidget(self._status_pos)
        self.statusBar().addPermanentWidget(self._status_zoom)

    def _restyle_status_bar(self):
        """(Re)apply the theme to the status-bar labels.

        The LoD label is styled by the complexity mixin as its state changes,
        so it is left alone here rather than being reset to a default.
        """
        self._status_breadcrumb.setStyleSheet(
            f"color: {theme.STATUS_DIM.name()};")
        self._status_focus.setStyleSheet(
            f"color: {theme.INFO_COLOR.name()}; font-weight: bold;")
        self._status_warn.setStyleSheet(
            f"color: {theme.ERROR_BG.name()}; font-weight: bold;")
        self._status_buf.setStyleSheet(f"color: {theme.INFO_COLOR.name()};")
        self._status_version.setStyleSheet(f"color: {theme.STATUS_DIM.name()};")

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
        # Already open — focus it and re-fit, since an explicit "open this
        # file" (CLI, single-instance forward, file pick) means "show me this
        # board," not "restore my last scroll position" (that's buffer
        # switching via Ctrl+K, which keeps the saved view).
        existing = self._buffers.find_by_path(path)
        if existing >= 0:
            self._snapshot_current()
            self._switch_buffer(existing, zoom_fit=True)
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
        missing = _load_vault(path, board)
        mtime = self._get_mtime(path)
        vs = ViewState()
        buf = BufferState(
            file_path=path, last_written=text, board=board,
            view_state=vs, file_mtime=mtime,
        )

        self._snapshot_current()
        idx = self._buffers.add(buf)
        self._switch_buffer(idx, zoom_fit=True)
        self._warn_parse_issues(board)
        if missing:
            self._view.toast(
                "Missing vault doc"
                + ("s" if len(missing) > 1 else "")
                + ": " + ", ".join(f"{m}.md" for m in missing), "warn")

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
                    self._warn_parse_issues(new_board)
                buf.file_mtime = disk_mtime

        # Set the path before loading so the scene rebuild can resolve image
        # paths (relative to the file's directory) instead of falling back to
        # grey placeholders.
        self._file_path = buf.file_path
        # Re-read vault doc bodies: they may have changed on disk while this
        # buffer was inactive (the .grafli mtime check above can't see that).
        # Safe — _snapshot_current flushed any pending autosave before leaving.
        if buf.file_path is not None:
            _load_vault(buf.file_path, buf.board)
        self._view.load_board(buf.board)
        self._view.restore_state(buf.view_state)
        self._last_written = buf.last_written
        self._view.set_mode(Mode.SELECT)

        self._start_watching()
        self.setWindowTitle(
            self._title_for_path(self._file_path, dirty=self._view.dirty)
        )
        self._update_buf_status()

        # An explicit open leaves the canvas focused so its shortcuts (M, ⇧Z,
        # …) work immediately — without this the keys silently do nothing until
        # the user clicks the canvas, which reads as a frozen app.
        self._view.setFocus()

        if zoom_fit:
            # Arm a fit and try it now; if the viewport isn't laid out yet the
            # attempt no-ops and re-arms, and resizeEvent completes it once the
            # viewport has its real size (otherwise the board opens off-screen).
            self._pending_zoom_fit = True
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
                    self._warn_parse_issues(new_board)
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

    def _write_file(self) -> bool:
        if not self.board or not self._file_path:
            return False
        from grafli.resources import (classify_attachments, externalize_md_notes,
                                      res_dir, save_docs)
        # Conflict-check-on-save: if the file changed on disk since we last
        # reconciled (an external/AI write the 500 ms watcher hasn't reloaded
        # yet), merge it into the board *before* serializing — otherwise this
        # save would silently clobber that write. Closes the autosave race.
        try:
            disk_text = self._file_path.read_text(encoding="utf-8")
        except OSError:
            disk_text = None
        if disk_text is not None and disk_text != self._last_written:
            try:
                merged, conflicts = self._reconcile_external(disk_text)
            except Exception:
                # Disk holds something we can't parse yet (e.g. a mid-write
                # from a non-atomic external editor). Skip this save and let
                # the next tick retry against a complete file rather than
                # overwrite an edit we couldn't read.
                return False
            _load_vault(self._file_path, merged)
            self._view.load_board(merged)
            if conflicts:
                self._report_conflicts(conflicts)
        # Save is the migration moment (opening never mutates the working
        # tree): inline md: notes become doc-bodied, legacy &url attachments
        # take their kind, and doc bodies land in the vault.
        externalized = externalize_md_notes(self.board)
        classify_attachments(self._file_path, self.board)
        try:
            save_docs(self._file_path, self.board)
        except OSError as exc:
            self._view.toast(f"Save failed: {exc}", "error")
            return False
        text = serialize(self.board)
        try:
            atomic_write(self._file_path, text)
        except OSError as exc:
            # Autosave and manual save both land here — a sticky error toast so
            # a failing write (read-only dir, full disk) can't pass unnoticed.
            self._view.toast(f"Save failed: {exc}", "error")
            return False
        if externalized:
            self._view.toast(
                f"Externalized {externalized} note"
                + ("s" if externalized != 1 else "")
                + f" → {res_dir(self._file_path).name}/")
        # Doc files just changed under our own hand — re-baseline the docs
        # watcher (and pick up newly externalized docs) so the write doesn't
        # echo back as an external change.
        self._watch_docs()
        self._last_written = text
        self._view._dirty = False
        # Update mtime in active buffer
        buf = self._buffers.active
        if buf:
            buf.file_mtime = self._get_mtime(self._file_path)
            buf.last_written = text
        if self._file_path:
            self.setWindowTitle(self._title_for_path(self._file_path))
        return True

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

        if self._write_file():
            self._view.toast(f"Saved {self._file_path.name}")

    def _start_watching(self):
        self._stop_watching()
        if not self._file_path:
            return
        self._watcher = JsonSafeWatcher(str(self._file_path))
        self._watcher.file_changed.connect(self._on_file_changed)
        self._watcher.start()
        self._watch_docs()

    def _watch_docs(self):
        """(Re)start the consolidated poller over the board's vault docs, so
        external edits to a doc-bodied note's .md reload live — one timer for
        all docs, re-baselined after our own writes."""
        if self._docs_watcher:
            self._docs_watcher.stop()
            self._docs_watcher = None
        if not self._file_path or not self.board:
            return
        from grafli.format import doc_name
        from grafli.resources import doc_path
        paths = [str(doc_path(self._file_path, doc_name(n)))
                 for n in self.board.notes if n.attach_kind == "doc"]
        if not paths:
            return
        self._docs_watcher = MultiFileWatcher(paths)
        self._docs_watcher.files_changed.connect(self._on_docs_changed)
        self._docs_watcher.start()

    def _on_docs_changed(self, _changed: list):
        if not self.board or not self._file_path:
            return
        from grafli.resources import load_docs
        load_docs(self._file_path, self.board)
        self._view.load_board(self.board)

    def _stop_watching(self):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        if self._docs_watcher:
            self._docs_watcher.stop()
            self._docs_watcher = None

    def _reconcile_external(self, disk_text: str) -> tuple[Board, list[Conflict]]:
        """3-way merge an external on-disk edit into the in-memory board.

        ``base`` is the disk content we last reconciled against
        (``_last_written``), ``local`` the current in-memory board (the
        human's unsaved edits), ``remote`` the new disk text (e.g. an AI
        write). Returns the merged board and any conflicts. When there is
        no in-memory board yet, the disk version is taken verbatim.
        """
        remote = parse(disk_text)
        if not self.board:
            return remote, []
        try:
            base = parse(self._last_written) if self._last_written else None
        except Exception:
            base = None
        return merge_boards(base, self.board, remote)

    def _on_file_changed(self):
        if not self._file_path or not self._file_path.exists():
            return
        try:
            text = self._file_path.read_text(encoding="utf-8")
        except OSError:
            return
        if text == self._last_written:
            return

        merged, conflicts = self._reconcile_external(text)
        _load_vault(self._file_path, merged)
        self._view.load_board(merged)
        self._watch_docs()
        self._last_written = text
        # If the merge folded in local edits not yet on disk, the board is
        # dirty and the next autosave converges the file to the merged
        # result; otherwise it already matches disk and is clean.
        if serialize(merged) != text:
            self._view.mark_dirty()
        else:
            self._view.mark_clean()
        buf = self._buffers.active
        if buf:
            buf.file_mtime = self._get_mtime(self._file_path)
            buf.last_written = text
        if conflicts:
            self._report_conflicts(conflicts)

    def _report_conflicts(self, conflicts: list[Conflict]) -> None:
        """Surface merge conflicts so a concurrent edit clash is never
        silent — the merge already resolved them deterministically; this
        just tells the human which elements diverged."""
        n = len(conflicts)
        first = conflicts[0]
        head = f"{first.kind} {first.key} ({first.detail})"
        msg = (f"Merged {n} concurrent edit conflict"
               + ("s" if n != 1 else "")
               + f" — e.g. {head}" if n > 1 else f"Merged a concurrent edit: {head}")
        self._view.toast(msg, "error")

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


def _load_vault(path: Path, board: Board) -> list[str]:
    """Resolve a freshly parsed board against its vault: classify legacy
    untyped attachments and read doc-bodied note texts from <stem>-res/.
    In-memory only — never writes. Returns the names of missing docs."""
    from grafli.resources import classify_attachments, load_docs
    classify_attachments(path, board)
    return load_docs(path, board)


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

Supported targets (user-level paths follow the agentskills.io convention;
each gets the skill directory — SKILL.md plus references/):

  claude    ~/.claude/skills/grafli/
            https://code.claude.com/docs/en/skills
  codex     ~/.agents/skills/grafli/
            https://developers.openai.com/codex/skills
  opencode  ~/.config/opencode/skills/grafli/
            https://opencode.ai/docs/skills

(OpenCode also reads from `~/.claude/skills/` and `~/.agents/skills/`, so
installing for `claude` or `codex` is automatically picked up by OpenCode.)

Without a subcommand, `grafli skill` prints the full skill to stdout —
SKILL.md with every reference file inlined, for single-file consumers.
Pass --core for just the lean core SKILL.md.
"""

# Concat / inline order for the reference files; unknown names sort after.
_REFERENCE_ORDER = ("format.md", "design.md", "presenting.md", "thinking.md")


def _skill_dir() -> Path:
    """Return the path to the bundled skill directory."""
    from importlib.resources import files
    return Path(str(files("grafli.skills.grafli")))


def _skill_path() -> Path:
    """Return the path to the bundled SKILL.md."""
    return _skill_dir() / "SKILL.md"


def _skill_references() -> dict[str, str]:
    """Return the bundled reference files as ``{name: content}``, in
    the canonical inline order.
    """
    ref_dir = _skill_dir() / "references"
    if not ref_dir.is_dir():
        return {}
    def order(p: Path) -> tuple[int, str]:
        try:
            return (_REFERENCE_ORDER.index(p.name), p.name)
        except ValueError:
            return (len(_REFERENCE_ORDER), p.name)
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(ref_dir.glob("*.md"), key=order)
    }


def _skill_concat() -> str:
    """The single-file build: SKILL.md with every reference inlined."""
    parts = [_skill_path().read_text(encoding="utf-8")]
    for name, content in _skill_references().items():
        parts.append(
            f"\n\n---\n\n<!-- inlined from references/{name} -->\n\n{content}"
        )
    return "".join(parts)


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
        description="Print the bundled grafli AI skill (SKILL.md + references).",
        epilog=SKILL_DOCS,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Write the skill to this path instead of stdout",
    )
    parser.add_argument(
        "--core", action="store_true",
        help="Emit only the lean core SKILL.md, without inlining the "
             "reference files",
    )
    parser.add_argument(
        "--where", action="store_true",
        help="Print the path of the bundled skill directory and exit",
    )
    args = parser.parse_args(argv)

    if args.where:
        print(_skill_dir())
        return 0
    text = (
        _skill_path().read_text(encoding="utf-8") if args.core
        else _skill_concat()
    )
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
    references = _skill_references()
    version = _grafli_version()

    any_drift = False
    any_action = False

    for t in targets:
        st = compute_status(t, packaged, version, references)
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

        path = write_skill(t, packaged, version, references)
        print(f"  wrote {path}")
        if references:
            print(f"  wrote {path.parent / 'references'} ({len(references)} files)")
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
    references = _skill_references()
    version = _grafli_version()

    statuses = [compute_status(t, packaged, version, references) for t in targets]

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
    references = _skill_references()
    version = _grafli_version()

    for t in targets:
        st = compute_status(t, packaged, version, references)
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
    parser.add_argument(
        "--focus", default=None, metavar="IDS",
        help="Comma-separated element ids — render only the region around "
             "them (context stays visible, the crop is the focus)",
    )
    parser.add_argument(
        "--bookmark", default=None, metavar="ID",
        help="Render the viewpoint a bookmark frames (honours its ~pad and "
             "~iso scoping)",
    )
    parser.add_argument(
        "--lod", action="store_true",
        help="Render the zoomed-out semantic-zoom reading (containers "
             "collapse to tiles, as when the whole board is fitted on screen)",
    )
    parser.add_argument(
        "--step", default=None, metavar="FLOW:N",
        help="Render step N (1-based) of a flow exactly as playback shows it: "
             "the step's bookmark framing with its detail/focus settings "
             "resolved (step ← flow ← default)",
    )
    parser.add_argument(
        "--detail", default=None, choices=("full", "summary"),
        help="Presentation detail override: 'full' renders everything as "
             "authored, 'summary' collapses containers to tiles (with --step: "
             "overrides the step's own setting)",
    )
    parser.add_argument(
        "--focus-mode", default=None, choices=("none", "complete"),
        help="Presentation focus: 'complete' dims elements not completely "
             "inside the framed region — needs --bookmark or --step (with "
             "--step: overrides the step's own setting)",
    )
    parser.add_argument(
        "--theme", default="light", choices=("light", "dark"),
        help="Colour theme for the render (default light). Headless output "
             "does not follow the app's theme setting, so a given file and "
             "flags always render the same image",
    )
    args = parser.parse_args(argv)

    theme.set_theme(args.theme)

    exclusive = [n for n, v in (("--focus", args.focus),
                                ("--bookmark", args.bookmark),
                                ("--step", args.step)) if v]
    if len(exclusive) > 1:
        print(f"{' and '.join(exclusive)} are mutually exclusive",
              file=sys.stderr)
        return 2

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

    from contextlib import nullcontext
    from PySide6.QtCore import QRectF
    from grafli.view import GrafliView
    text = args.input.resolve().read_text(encoding="utf-8")
    board = parse(text)
    view = GrafliView()
    view.load_board(board)

    region = None
    iso_ctx = nullcontext()
    detail = args.detail
    focus_mode = args.focus_mode
    bookmark_id = args.bookmark
    if args.step:
        from grafli.flows import step_detail, step_focus
        flow_id, _, step_no = args.step.partition(":")
        flow = board.flow_by_id(flow_id)
        if flow is None:
            ids = ", ".join(f.id for f in board.flows) or "none"
            print(f"Flow '{flow_id}' not found. Available: {ids}",
                  file=sys.stderr)
            return 2
        try:
            idx = int(step_no) - 1
        except ValueError:
            idx = -1
        if not 0 <= idx < len(flow.steps):
            print(f"--step wants FLOW:N with N in 1..{len(flow.steps)} "
                  f"for flow '{flow_id}'", file=sys.stderr)
            return 2
        step = flow.steps[idx]
        bookmark_id = step.ref
        # Explicit CLI flags override the step's resolved settings.
        if detail is None:
            detail = step_detail(flow, step) or None
        if focus_mode is None:
            focus_mode = step_focus(flow, step) or None
    if bookmark_id:
        from grafli.flows import bookmark_target_rect, isolate_focus
        bm = board.bookmark_by_id(bookmark_id)
        if bm is None:
            ids = ", ".join(b.id for b in board.bookmarks) or "none"
            print(f"Bookmark '{bookmark_id}' not found. Available: {ids}",
                  file=sys.stderr)
            return 2
        region = bookmark_target_rect(view, bm)
        if region.isNull():
            print(f"Bookmark '{bookmark_id}' resolves to no region "
                  f"(dangling focus ids?)", file=sys.stderr)
            return 2
        if bm.isolate and bm.focus:
            iso_ctx = isolate_focus(view, bm.focus)
    elif args.focus:
        wanted = [i.strip() for i in args.focus.split(",") if i.strip()]
        items = {**view._box_items, **view._note_items, **view._image_items}
        missing = [i for i in wanted if i not in items]
        if missing:
            print(f"Unknown element id(s): {', '.join(missing)}",
                  file=sys.stderr)
            return 2
        region = QRectF()
        for i in wanted:
            region = region.united(items[i].sceneBoundingRect())
        region = region.adjusted(
            -args.padding, -args.padding, args.padding, args.padding,
        )

    if args.lod:
        # Reproduce the fit-whole-board-on-screen zoom so the semantic-zoom
        # state matches what a human sees when they step back.
        bounds = view._scene.itemsBoundingRect()
        if bounds.width() > 0 and bounds.height() > 0:
            fit = min(1280.0 / bounds.width(), 800.0 / bounds.height(), 0.999)
            view.resetTransform()
            view.scale(fit, fit)
        view._lod_dirty = True
        view._refresh_lod()

    if detail:
        view._set_presentation_detail(detail)
    if focus_mode == "complete":
        if region is None:
            print("--focus-mode complete needs a framed region — pass "
                  "--bookmark or --step", file=sys.stderr)
            return 2
        # The output image has the region's aspect, so "completely inside the
        # frame" and "completely in the picture" coincide.
        view._set_presentation_focus(region)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with iso_ctx:
        if suffix == ".svg":
            svg_bytes = view._render_svg_bytes(
                padding=args.padding, region=region,
            )
            with open(args.output, "wb") as f:
                f.write(bytes(svg_bytes))
        else:
            view._render_png_to_path(
                args.output, padding=args.padding, width=args.width,
                region=region,
            )
    print(f"Wrote {args.output}", file=sys.stderr)
    # Drop the QApplication reference to avoid lingering process state.
    del view
    del app
    return 0


def _cmd_export(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="grafli export",
        description="Export a flow as a slide-style presentation (PDF or PPTX).",
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument(
        "output", type=Path, nargs="?", default=None,
        help="Output .pdf or .pptx (optional with --check)",
    )
    parser.add_argument(
        "--flow", default=None,
        help="Flow id to export (default: the only flow; required if several)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Dry-run: report slide count, overloaded slides, dangling "
             "bookmark/step refs and missing vault docs — without writing "
             "the deck. Exit 1 when anything needs fixing.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="With --check: emit the report as JSON",
    )
    parser.add_argument(
        "--theme", default="grafli", choices=("grafli", "blank"),
        help="PPTX theme: 'grafli' (default, branded) or 'blank' (neutral, "
             "best base for applying a corporate template). Ignored for PDF and "
             "when --template is given.",
    )
    parser.add_argument(
        "--template", type=Path, default=None,
        help="Export onto an existing .pptx template, keeping its master, theme "
             "and slide size. PPTX only.",
    )
    parser.add_argument(
        "--title-layout", default=None,
        help="Name of the template layout for the title slide "
             "(default: auto-detected). Only with --template.",
    )
    parser.add_argument(
        "--content-layout", default=None,
        help="Name of the template layout for content slides "
             "(default: auto-detected). Only with --template.",
    )
    args = parser.parse_args(argv)
    if args.template is not None and not args.template.exists():
        print(f"Template not found: {args.template}", file=sys.stderr)
        return 2

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2
    if args.output is None and not args.check:
        print("output is required (or pass --check for a dry-run)",
              file=sys.stderr)
        return 2
    suffix = args.output.suffix.lower() if args.output else ".pdf"
    if suffix not in (".pdf", ".pptx"):
        print(f"Unsupported output format: {args.output.suffix} "
              f"(expected .pdf or .pptx)", file=sys.stderr)
        return 2

    text = args.input.resolve().read_text(encoding="utf-8")
    board = parse(text)
    missing = _load_vault(args.input.resolve(), board)
    if not args.check:
        for name in missing:
            print(f"Warning: missing vault doc {name}.md", file=sys.stderr)
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

    # Flow-integrity findings (cheap, no Qt needed): steps referencing a
    # missing bookmark, bookmark focus ids that resolve to no element.
    element_ids = (
        {b.id for b in board.boxes}
        | {n.id for n in board.notes}
        | {im.id for im in board.images}
    )
    dangling: list[str] = []
    for step in flow.steps:
        if board.bookmark_by_id(step.ref) is None:
            dangling.append(
                f"flow '{flow.id}' step references missing bookmark "
                f"'{step.ref}'"
            )
    for bm in board.bookmarks:
        for fid in bm.focus:
            if fid not in element_ids:
                dangling.append(
                    f"bookmark '{bm.id}' anchors missing element '{fid}'"
                )

    # Over-long captions: playback and slides show the full description
    # wrapped, so a caption past the budget stops being a caption.
    from grafli.format import MAX_DESCRIPTION_CHARS
    overlong: list[dict] = []
    for bm_id in dict.fromkeys(step.ref for step in flow.steps):
        bm = board.bookmark_by_id(bm_id)
        if bm is not None and len(bm.description) > MAX_DESCRIPTION_CHARS:
            overlong.append({"bookmark": bm.id,
                             "chars": len(bm.description),
                             "max": MAX_DESCRIPTION_CHARS})

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    _register_bundled_fonts()
    from grafli.view import GrafliView
    view = GrafliView()
    view.load_board(board)

    if args.check:
        # Dry-run through the real exporter (text sizing needs the real
        # layout), written to a scratch file that is removed afterwards.
        import json as _json
        import tempfile
        with tempfile.NamedTemporaryFile(
            suffix=suffix, delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)
        try:
            if suffix == ".pptx":
                from grafli.pptxexport import export_flow_to_pptx
                slides, overloaded = export_flow_to_pptx(
                    view, flow, tmp_path, theme=args.theme,
                    template=args.template,
                    title_layout=args.title_layout,
                    content_layout=args.content_layout)
            else:
                from grafli.pdfexport import export_flow_to_pdf
                slides, overloaded = export_flow_to_pdf(view, flow, tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
        report = {
            "flow": flow.id,
            "slides": slides,
            "overloaded": [
                {"slide": i + 1, "label": lbl} for i, lbl in overloaded
            ],
            "overlong": overlong,
            "dangling": dangling,
            "missing_docs": list(missing),
        }
        clean = not (overloaded or overlong or dangling or missing)
        if args.json:
            print(_json.dumps(report, indent=2))
        else:
            print(f"flow '{flow.id}': {slides} slides")
            for entry in report["overloaded"]:
                print(f"[overloaded] slide #{entry['slide']} "
                      f"{entry['label']}".rstrip()
                      + " — trim the text or split the slide")
            for entry in overlong:
                print(f"[overlong-caption] bookmark '{entry['bookmark']}' — "
                      f"{entry['chars']} chars (max {entry['max']}); "
                      f"shorten it or split the stop")
            for msg in dangling:
                print(f"[dangling] {msg}")
            for name in missing:
                print(f"[missing-doc] vault doc {name}.md")
            if clean:
                print("No findings.")
        del view
        del app
        return 0 if clean else 1

    for msg in dangling:
        print(f"Warning: {msg}", file=sys.stderr)
    for entry in overlong:
        print(f"Warning: bookmark '{entry['bookmark']}' caption is "
              f"{entry['chars']} chars (max {entry['max']}) — shorten it or "
              f"split the stop", file=sys.stderr)
    if suffix == ".pptx":
        from grafli.pptxexport import export_flow_to_pptx
        slides, overloaded = export_flow_to_pptx(
            view, flow, args.output, theme=args.theme,
            template=args.template,
            title_layout=args.title_layout,
            content_layout=args.content_layout)
    else:
        from grafli.pdfexport import export_flow_to_pdf
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
        epilog=(
            "Exit codes: 0 no gated findings, 1 errors present "
            "(--strict: errors or warnings), 2 usage/IO problem."
        ),
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero on warnings too, not just errors",
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Apply the mechanical fixes (findings that carry a fix plan) "
             "and rewrite the file, then report what remains",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="With --fix: print the fix plan without writing the file",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    text = args.input.read_text(encoding="utf-8")
    board = parse(text)
    from grafli.diagnostics import Diagnostic, apply_fixes
    note_rect = _make_note_rect_provider()
    arrow_label_size = _make_arrow_label_size_provider()
    from grafli.resources import classify_attachments, vault_docs

    def _collect(b) -> list:
        diags = run_all(
            b,
            args.input.resolve().parent,
            note_rect=note_rect,
            arrow_label_size=arrow_label_size,
        )
        # Vault integrity: referenced docs whose file is gone (error — a
        # doc-bodied note would render blank) and unreferenced docs (info —
        # legitimate state).
        classify_attachments(args.input.resolve(), b)
        inv = vault_docs(args.input.resolve(), b)
        for name in inv["missing"]:
            diags.append(Diagnostic(
                code="missing-doc", severity="error",
                message=f"vault doc {name}.md is referenced but missing",
                item_ids=[name], fixable=False,
            ))
        for name in inv["unreferenced"]:
            diags.append(Diagnostic(
                code="unreferenced-doc", severity="info",
                message=f"vault doc {name}.md is not referenced by any "
                        f"element (grafli vault --clean removes it)",
                item_ids=[name], fixable=False,
            ))
        return diags

    diags = _collect(board)

    applied: list = []
    if args.fix and not args.dry_run:
        # Fixes can cascade (widening a box may push it back outside its
        # parent), so iterate to a fixpoint — bounded, and each pass must
        # make progress. One write at the end.
        for _ in range(10):
            newly = apply_fixes(board, diags)
            if not newly:
                break
            applied.extend(newly)
            diags = _collect(board)
        if applied:
            serialize_to_file(board, str(args.input))

    # Gateable exit: 1 on errors (with --strict also on warnings), 0 otherwise.
    # 2 stays reserved for usage/IO problems (missing input above). With --fix
    # the gate judges what remains after the rewrite.
    gate = ("error", "warning") if args.strict else ("error",)
    exit_code = 1 if any(d.severity in gate for d in diags) else 0

    if args.json:
        if args.fix and not args.dry_run:
            print(_json.dumps({
                "applied": [d.to_dict() for d in applied],
                "findings": [d.to_dict() for d in diags],
            }, indent=2))
        else:
            print(_json.dumps([d.to_dict() for d in diags], indent=2))
        return exit_code

    for d in applied:
        print(f"[fixed] {d.code}: {_describe_fix(d.fix)}")
    if args.fix and args.dry_run:
        planned = [d for d in diags if d.fix]
        for d in planned:
            print(f"[plan] {d.code}: {_describe_fix(d.fix)}")
        if planned:
            print(f"{len(planned)} fix(es) planned — re-run without "
                  f"--dry-run to apply.\n")

    if not diags:
        print("No findings." if not applied
              else f"No findings remain ({len(applied)} fixed).")
        return 0

    for d in diags:
        suffix = "" if d.fixable else "  (may be intentional)"
        print(f"[{d.severity}] {d.code}: {d.message}{suffix}")
    print(f"\n{len(diags)} finding(s).")
    return exit_code


def _describe_fix(fix: dict) -> str:
    """One human line for a fix plan: what moves/changes, old -> new."""
    action, iid = fix["action"], fix["id"]
    old, new = fix["old"], fix["new"]
    if action == "move":
        return (f"{iid!r} move {old['x']:.0f},{old['y']:.0f} -> "
                f"{new['x']:.0f},{new['y']:.0f}")
    if action == "resize":
        return (f"{iid!r} resize {old['w']:.0f}x{old['h']:.0f} -> "
                f"{new['w']:.0f}x{new['h']:.0f}")
    if action == "set-rect":
        return (f"{iid!r} rect {old['x']:.0f},{old['y']:.0f} "
                f"{old['w']:.0f}x{old['h']:.0f} -> {new['x']:.0f},"
                f"{new['y']:.0f} {new['w']:.0f}x{new['h']:.0f}")
    return f"{iid!r} {action.removeprefix('set-')} {old} -> {new}"


def _cmd_inspect(argv: list[str]) -> int:
    """Resolved-geometry report (JSON) for agents: element bounds,
    container inner rects, sibling gaps, next free slot per container."""
    import json as _json
    from grafli.board_info import board_info

    parser = argparse.ArgumentParser(
        prog="grafli inspect",
        description=(
            "Report a board's resolved geometry as JSON: element bounds, "
            "container inner rects after the margin model, sibling gaps, "
            "and the next free slot per container. Query-only — it never "
            "moves anything."
        ),
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument(
        "--ids", default=None,
        help="Comma-separated element ids — restrict the elements/"
             "containers sections to these (arrows touching them included)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    board = parse(args.input.read_text(encoding="utf-8"))
    info = board_info(board, note_rect=_make_note_rect_provider())

    if args.ids:
        wanted = {i.strip() for i in args.ids.split(",") if i.strip()}
        info["elements"] = [e for e in info["elements"] if e["id"] in wanted]
        info["containers"] = [
            c for c in info["containers"]
            if c["id"] in wanted or wanted.intersection(c["children"])
        ]
        info["arrows"] = [
            a for a in info["arrows"]
            if a["from"] in wanted or a["to"] in wanted
        ]

    print(_json.dumps(info, indent=2))
    return 0


def _cmd_vault(argv: list[str]) -> int:
    """Inspect / clean a board's vault (<stem>-res/ markdown docs)."""
    from grafli.resources import classify_attachments, doc_path, vault_docs

    parser = argparse.ArgumentParser(
        prog="grafli vault",
        description=(
            "List a board's vault docs (referenced / missing / unreferenced). "
            "Unreferenced docs are a legitimate state; removing them is this "
            "explicit command, never automatic."
        ),
    )
    parser.add_argument("input", type=Path, help="Input .grafli file")
    parser.add_argument(
        "--clean", action="store_true",
        help="Delete unreferenced vault docs (lists what it removes)",
    )
    parser.add_argument(
        "--delete", metavar="NAME", default=None,
        help="Delete one doc by name (refuses while still referenced)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2

    path = args.input.resolve()
    board = parse(path.read_text(encoding="utf-8"))
    classify_attachments(path, board)
    inv = vault_docs(path, board)

    if args.delete is not None:
        name = args.delete.removesuffix(".md")
        if name in inv["referenced"] or name in inv["missing"]:
            print(f"Refusing: {name}.md is still referenced.", file=sys.stderr)
            return 1
        p = doc_path(path, name)
        if not p.exists():
            print(f"No such doc: {name}.md", file=sys.stderr)
            return 2
        p.unlink()
        print(f"Deleted {p}")
        return 0

    if args.clean:
        for name in inv["unreferenced"]:
            p = doc_path(path, name)
            try:
                p.unlink()
                print(f"Deleted {p}")
            except OSError as exc:
                print(f"Could not delete {p}: {exc}", file=sys.stderr)
        if not inv["unreferenced"]:
            print("Nothing to clean.")
        return 0

    for key, label in (("referenced", "referenced"), ("missing", "MISSING"),
                       ("unreferenced", "unreferenced")):
        for name in inv[key]:
            print(f"{label:>12}  {name}.md")
    if not any(inv.values()):
        print("No vault docs.")
    return 0


SCRATCH_FILENAME = "grafli-scratch.grafli"


def _resolve_launch_file(file_arg: str | None) -> Path:
    """Resolve the board to open at startup.

    With no file argument — a bare ``grafli`` or a Dock/Spotlight click,
    which passes none — fall back to a persistent scratch board in the home
    dir. ``_open_file`` creates it on first open and autosaves it thereafter,
    so a no-argument launch lands on a canvas that survives instead of the
    in-memory untitled buffer that was lost when the window closed.
    """
    if file_arg:
        return Path(file_arg)
    return Path.home() / SCRATCH_FILENAME


def main():
    # Subcommand dispatch — keep the bare `grafli <file>` form unchanged.
    if len(sys.argv) >= 2 and sys.argv[1] in ("skill", "render", "diagnose",
                                              "export", "vault", "inspect"):
        sub = sys.argv[1]
        rest = sys.argv[2:]
        if sub == "skill":
            sys.exit(_cmd_skill(rest))
        if sub == "render":
            sys.exit(_cmd_render(rest))
        if sub == "export":
            sys.exit(_cmd_export(rest))
        if sub == "vault":
            sys.exit(_cmd_vault(rest))
        if sub == "inspect":
            sys.exit(_cmd_inspect(rest))
        sys.exit(_cmd_diagnose(rest))

    parser = argparse.ArgumentParser(
        prog="grafli",
        description="Grafli whiteboard. Subcommands: skill, render, diagnose, "
                    "inspect, export, vault.",
    )
    parser.add_argument("file", nargs="?", default=None, help="File to open")
    parser.add_argument("--debug", action="store_true", help="Enable debug overlay")
    args = parser.parse_args()
    launch_file = str(_resolve_launch_file(args.file))

    app = QApplication(sys.argv)
    app.setApplicationName("Grafli")

    # Single-instance: hand off to an already-running instance. With no file
    # the scratch board is the target, so a re-launch focuses it in place.
    if _try_send_to_existing(launch_file):
        sys.exit(0)

    _register_bundled_fonts()

    # Let Ctrl+C quit the app cleanly
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    window = MainWindow(launch_file, debug=args.debug)
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
