"""Zen markdown editor — full-window iA Writer-inspired editing experience."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, Qt, Signal, QTimer
from PySide6.QtGui import QFont, QKeyEvent, QPainter
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from grafli.constants import (
    FONT_FAMILY,
    ZEN_HINT_COLOR,
    ZEN_MD_BG,
    ZEN_MD_FONT_SIZE,
    ZEN_MD_MAX_WIDTH,
    ZEN_TEXT_COLOR,
    ZEN_TITLE_COLOR,
    _CTRL_MOD,
)
from grafli.zen_md_highlight import MarkdownHighlighter, compute_focus_range
from grafli.zen_md_jump import WordJumpOverlay
from grafli.zen_md_vim import VimKeyHandler, VimMode


class ZenMarkdownEditor(QWidget):
    """Full-window zen editor for annotations and markdown files."""

    finished = Signal(str)
    cancelled = Signal()
    file_saved = Signal(Path)

    def __init__(
        self,
        parent: QWidget,
        text: str,
        title: str = "",
        file_path: Path | None = None,
        anchor: str = "",
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._file_path = file_path
        self._original_text = text
        self._read_only = file_path is not None
        self._watcher = None
        self._autosave_timer: QTimer | None = None

        self.resize(parent.size())
        self._build_ui(title, text)
        self._setup_file_watcher()
        if anchor:
            self._jump_to_anchor(anchor)
        self.show()

    # ── UI construction ──

    def _build_ui(self, title: str, text: str):
        layout = QVBoxLayout(self)
        h_margin = max((self.width() - ZEN_MD_MAX_WIDTH) // 2, 60)
        v_margin = max(self.height() // 8, 40)
        layout.setContentsMargins(h_margin, v_margin, h_margin, v_margin)
        layout.setSpacing(8)

        # Title
        if title:
            self._title = QLabel(title)
            self._title.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
            self._title.setStyleSheet(
                f"color: {ZEN_TITLE_COLOR.name()}; background: transparent;"
            )
            layout.addWidget(self._title)
        else:
            self._title = None

        # Text editor
        self._editor = QPlainTextEdit(text)
        self._editor.setFont(QFont(FONT_FAMILY, ZEN_MD_FONT_SIZE))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.setReadOnly(self._read_only)
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background: {ZEN_MD_BG.name()}; color: {ZEN_TEXT_COLOR.name()};"
            f" border: none; padding: 16px;"
            f" selection-background-color: #B8D4E8;"
            f"}}"
        )
        self._editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(self._editor, stretch=1)

        # Hint bar
        self._hint = QLabel(self._build_hint_text())
        self._hint.setFont(QFont(FONT_FAMILY, 10))
        self._hint.setStyleSheet(
            f"color: {ZEN_HINT_COLOR.name()}; background: transparent;"
        )
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint)

        # Markdown highlighter + paragraph focus (disabled in read-only mode)
        self._highlighter = MarkdownHighlighter(self._editor.document())
        self._editor.cursorPositionChanged.connect(self._update_focus)
        if self._read_only:
            self._highlighter.set_focus_enabled(False)

        # Vim key handler
        self._vim = VimKeyHandler(
            editor=self._editor,
            mode_changed=self._on_mode_changed,
            close_save=self._close_save,
            close_cancel=self._close_cancel,
        )
        self._editor.setOverwriteMode(True)  # block cursor in normal mode
        self._editor.installEventFilter(self)  # intercept keys before editor

        # Word jump overlay
        self._jump: WordJumpOverlay | None = None

        # Focus and cursor
        self._editor.setFocus()
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self._editor.setTextCursor(cursor)
        self._update_focus()

    def _build_hint_text(self) -> str:
        parts = []
        if self._file_path:
            if self._read_only:
                parts.append("[READ-ONLY]")
            else:
                parts.append("[EDITING]")
        mode_name = self._vim.mode.value if hasattr(self, "_vim") else "NORMAL"
        parts.append(f"-- {mode_name} --")
        parts.append("Esc to save \u00b7 Shift+Esc to cancel")
        return "  ".join(parts)

    def _on_mode_changed(self, mode: VimMode):
        self._hint.setText(self._build_hint_text())

    def _close_save(self):
        if self._file_path:
            # File mode: just close (autosave handles writes)
            self.cancelled.emit()
        else:
            # Annotation mode: emit finished with text
            self.finished.emit(self._editor.toPlainText())
        self.close()

    def _close_cancel(self):
        self.cancelled.emit()
        self.close()

    def _update_focus(self):
        if self._read_only:
            return
        start, end = compute_focus_range(self._editor)
        self._highlighter.set_focus_range(start, end)

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert heading text to a markdown anchor slug."""
        s = text.lower().strip()
        s = re.sub(r"[^\w\s-]", "", s)
        return re.sub(r"[\s]+", "-", s).strip("-")

    def _jump_to_anchor(self, anchor: str):
        """Scroll to the heading matching the given anchor slug."""
        doc = self._editor.document()
        block = doc.begin()
        while block.isValid():
            text = block.text()
            m = re.match(r"^#{1,6}\s+(.*)", text)
            if m and self._slugify(m.group(1)) == anchor:
                cursor = self._editor.textCursor()
                cursor.setPosition(block.position())
                self._editor.setTextCursor(cursor)
                self._editor.centerCursor()
                return
            block = block.next()

    # ── File watching & autosave ──

    def _setup_file_watcher(self):
        if not self._file_path or not self._file_path.exists():
            return
        self._watcher = QFileSystemWatcher([str(self._file_path)], self)
        self._watcher.fileChanged.connect(self._on_file_changed)

    def _on_file_changed(self, path: str):
        """Reload file content when it changes externally (read-only mode)."""
        if not self._read_only:
            return
        p = Path(path)
        if not p.exists():
            return
        # Preserve cursor position
        cursor_pos = self._editor.textCursor().position()
        text = p.read_text(encoding="utf-8")
        self._editor.setPlainText(text)
        cursor = self._editor.textCursor()
        cursor.setPosition(min(cursor_pos, len(text)))
        self._editor.setTextCursor(cursor)
        # Re-add path to watcher (some systems remove it after change)
        if self._watcher and path not in self._watcher.files():
            self._watcher.addPath(path)

    def _toggle_write_mode(self):
        """Toggle between read-only and auto-save write mode for files."""
        if not self._file_path:
            return
        self._read_only = not self._read_only
        self._editor.setReadOnly(self._read_only)
        self._highlighter.set_focus_enabled(not self._read_only)
        if not self._read_only:
            self._update_focus()
        if self._read_only:
            # Entering read-only: stop autosave, re-enable watcher
            if self._autosave_timer:
                self._autosave_timer.stop()
                self._autosave_timer = None
            if self._watcher and str(self._file_path) not in self._watcher.files():
                self._watcher.addPath(str(self._file_path))
        else:
            # Entering write mode: setup autosave, pause watcher
            if self._watcher:
                self._watcher.removePath(str(self._file_path))
            self._autosave_timer = QTimer(self)
            self._autosave_timer.setSingleShot(True)
            self._autosave_timer.setInterval(500)
            self._autosave_timer.timeout.connect(self._autosave)
            self._editor.textChanged.connect(self._schedule_autosave)
        self._vim._set_mode(VimMode.NORMAL)
        self._hint.setText(self._build_hint_text())

    def _schedule_autosave(self):
        if self._autosave_timer:
            self._autosave_timer.start()

    def _autosave(self):
        if not self._file_path or self._read_only:
            return
        self._file_path.write_text(
            self._editor.toPlainText(), encoding="utf-8",
        )
        self.file_saved.emit(self._file_path)

    def _print(self):
        """Open native print dialog."""
        self._highlighter.set_focus_enabled(False)
        printer = QPrinter()
        dialog = QPrintDialog(printer, self)
        if dialog.exec() == QPrintDialog.DialogCode.Accepted:
            self._editor.print_(printer)
        self._highlighter.set_focus_enabled(True)

    # ── Paint ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), ZEN_MD_BG)
        p.end()

    # ── Resize tracking ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        layout = self.layout()
        if layout:
            h_margin = max((self.width() - ZEN_MD_MAX_WIDTH) // 2, 60)
            v_margin = max(self.height() // 8, 40)
            layout.setContentsMargins(h_margin, v_margin, h_margin, v_margin)

    def _parent_resized(self):
        parent = self.parentWidget()
        if parent:
            self.resize(parent.size())

    def showEvent(self, event):
        super().showEvent(event)
        parent = self.parentWidget()
        if parent:
            parent.installEventFilter(self)
            self.resize(parent.size())

    def hideEvent(self, event):
        parent = self.parentWidget()
        if parent:
            parent.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if obj == self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.resize(obj.size())
            return False
        if obj == self._editor and event.type() == QEvent.Type.KeyPress:
            return self._handle_key(event)
        return False

    # ── Key handling ──

    def _handle_key(self, event: QKeyEvent) -> bool:
        """Central key router. Returns True if event is consumed."""
        # Jump overlay consumes all keys while active
        if self._jump and self._jump.is_active():
            self._jump.keyPressEvent(event)
            return True

        # Ctrl+J — activate word jump
        if (event.key() == Qt.Key.Key_J
                and event.modifiers() & _CTRL_MOD):
            self._activate_jump()
            return True

        # Ctrl+W — toggle read-only / write mode (file mode only)
        if (event.key() == Qt.Key.Key_W
                and event.modifiers() & _CTRL_MOD
                and self._file_path):
            self._toggle_write_mode()
            return True

        # Ctrl+P — print
        if (event.key() == Qt.Key.Key_P
                and event.modifiers() & _CTRL_MOD):
            self._print()
            return True

        # Route through vim handler
        return self._vim.handle_key(event)

    def _activate_jump(self):
        if self._jump is None:
            self._jump = WordJumpOverlay(self._editor, self)
        self._jump.activate()

    # ── Public API ──

    def editor(self) -> QPlainTextEdit:
        return self._editor

    def set_hint(self, text: str):
        self._hint.setText(text)
