"""Vim-style key handler for the zen markdown editor."""

from __future__ import annotations

import enum
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class VimMode(enum.Enum):
    NORMAL = "NORMAL"
    INSERT = "INSERT"


_MoveOp = QTextCursor.MoveOperation
_MoveMode = QTextCursor.MoveMode


class VimKeyHandler:
    """Stateful vim key handler that operates on a QPlainTextEdit."""

    def __init__(
        self,
        editor: QPlainTextEdit,
        mode_changed: Callable[[VimMode], None],
        close_save: Callable[[], None],
        close_cancel: Callable[[], None],
        initial_mode: VimMode = VimMode.NORMAL,
    ):
        self._editor = editor
        self._mode_changed = mode_changed
        self._close_save = close_save
        self._close_cancel = close_cancel
        self._mode = initial_mode
        self._pending = ""
        # Block cursor in normal mode, caret in insert. Callers that want a
        # different start (e.g. inline editing opens in INSERT) pass
        # ``initial_mode``; the zen editor keeps the NORMAL default.
        self._editor.setOverwriteMode(initial_mode == VimMode.NORMAL)

    @property
    def mode(self) -> VimMode:
        return self._mode

    def _set_mode(self, mode: VimMode):
        if mode == self._mode:
            return
        self._mode = mode
        self._editor.setOverwriteMode(mode == VimMode.NORMAL)
        self._mode_changed(mode)

    def handle_key(self, event: QKeyEvent) -> bool:
        """Process a key event. Returns True if consumed."""
        if self._mode == VimMode.INSERT:
            return self._handle_insert(event)
        return self._handle_normal(event)

    # ── Insert mode ──

    def _handle_insert(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key.Key_Escape:
            self._set_mode(VimMode.NORMAL)
            self._move(QTextCursor.MoveOperation.Left)
            return True
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Insert the newline ourselves rather than passing through. On
            # macOS the input method (enabled in insert mode) swallows a
            # bare Return so the default handler never inserts a line break
            # — only Shift+Return got through. Handling it here makes Enter
            # work everywhere and keeps behaviour identical across platforms.
            self._editor.textCursor().insertText("\n")
            return True
        return False  # pass through to editor

    # ── Normal mode ──

    def _handle_normal(self, event: QKeyEvent) -> bool:
        key = event.key()
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Handle pending multi-key sequences
        if self._pending:
            return self._handle_pending(event)

        # Esc in normal mode — save and close
        if key == Qt.Key.Key_Escape:
            if shift:
                self._close_cancel()
            else:
                self._close_save()
            return True

        # ── Motion ──
        if key == Qt.Key.Key_H and not shift:
            self._move(_MoveOp.Left)
            return True
        if key == Qt.Key.Key_L and not shift:
            self._move(_MoveOp.Right)
            return True
        if key == Qt.Key.Key_J and not shift:
            self._move(_MoveOp.Down)
            return True
        if key == Qt.Key.Key_K and not shift:
            self._move(_MoveOp.Up)
            return True

        # w — next word start
        if key == Qt.Key.Key_W and not shift:
            self._move(_MoveOp.NextWord)
            return True
        # b — previous word start
        if key == Qt.Key.Key_B and not shift:
            self._move(_MoveOp.PreviousWord)
            return True
        # e — end of word
        if key == Qt.Key.Key_E and not shift:
            self._move(_MoveOp.EndOfWord)
            return True

        # 0 — start of line
        if key == Qt.Key.Key_0:
            self._move(_MoveOp.StartOfBlock)
            return True
        # $ — end of line
        if event.text() == "$":
            self._move(_MoveOp.EndOfBlock)
            return True

        # G — end of document
        if key == Qt.Key.Key_G and shift:
            self._move(_MoveOp.End)
            return True
        # g — start pending for gg
        if key == Qt.Key.Key_G and not shift:
            self._pending = "g"
            return True

        # d — start pending for dd, dw
        if key == Qt.Key.Key_D and not shift:
            self._pending = "d"
            return True

        # x — delete char under cursor
        if key == Qt.Key.Key_X and not shift:
            self._delete_chars()
            return True

        # ── Enter insert mode ──
        if key == Qt.Key.Key_I and not shift:
            self._set_mode(VimMode.INSERT)
            return True
        if key == Qt.Key.Key_A and not shift:
            self._move(_MoveOp.Right)
            self._set_mode(VimMode.INSERT)
            return True
        if key == Qt.Key.Key_A and shift:
            self._move(_MoveOp.EndOfBlock)
            self._set_mode(VimMode.INSERT)
            return True
        if key == Qt.Key.Key_I and shift:
            self._move(_MoveOp.StartOfBlock)
            self._set_mode(VimMode.INSERT)
            return True
        if key == Qt.Key.Key_O and not shift:
            self._move(_MoveOp.EndOfBlock)
            c = self._editor.textCursor()
            c.insertText("\n")
            self._editor.setTextCursor(c)
            self._set_mode(VimMode.INSERT)
            return True
        if key == Qt.Key.Key_O and shift:
            self._move(_MoveOp.StartOfBlock)
            c = self._editor.textCursor()
            c.insertText("\n")
            c.movePosition(_MoveOp.Up)
            self._editor.setTextCursor(c)
            self._set_mode(VimMode.INSERT)
            return True

        return True  # consume unknown keys in normal mode

    def _handle_pending(self, event: QKeyEvent) -> bool:
        key = event.key()
        pending = self._pending
        self._pending = ""

        if pending == "g":
            if key == Qt.Key.Key_G:
                self._move(_MoveOp.Start)
                return True
            return True  # unknown g-sequence, consume

        if pending == "d":
            if key == Qt.Key.Key_D:
                self._delete_line()
                return True
            if key == Qt.Key.Key_W:
                c = self._editor.textCursor()
                c.movePosition(_MoveOp.NextWord, _MoveMode.KeepAnchor)
                c.removeSelectedText()
                self._editor.setTextCursor(c)
                return True
            return True  # unknown d-sequence, consume

        return True

    # ── Helpers ──

    def _move(self, op: QTextCursor.MoveOperation, count: int = 1):
        c = self._editor.textCursor()
        for _ in range(count):
            c.movePosition(op)
        self._editor.setTextCursor(c)

    def _delete_chars(self, count: int = 1):
        c = self._editor.textCursor()
        for _ in range(count):
            c.deleteChar()
        self._editor.setTextCursor(c)

    def _delete_line(self):
        c = self._editor.textCursor()
        c.movePosition(_MoveOp.StartOfBlock)
        c.movePosition(_MoveOp.EndOfBlock, _MoveMode.KeepAnchor)
        # Also grab the newline if it exists
        if not c.atEnd():
            c.movePosition(_MoveOp.Right, _MoveMode.KeepAnchor)
        c.removeSelectedText()
        self._editor.setTextCursor(c)
