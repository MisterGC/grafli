"""A small vim-capable text editor widget for in-place editing.

`InlineVimEditor` is a `QPlainTextEdit` with the same vim keybindings as
the full-window zen editor, minus the full-screen chrome, file I/O, and
jump overlay. It is meant to be embedded by a host (e.g. on a canvas via
a `QGraphicsProxyWidget`) for editing a single piece of text in place.

It knows nothing about what it is editing — the host passes text in and
receives the final text via `committed`, or a discard via `cancelled`.

Keys (shared with the zen editor):
* INSERT mode — type normally; `Esc` drops to NORMAL.
* NORMAL mode — vim motions/edits; `Esc` saves and closes,
  `Shift+Esc` discards and closes.

The editor opens in INSERT mode so quick edits feel like a plain text
box; vim power is one `Esc` away.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QFrame, QPlainTextEdit

from grafli.zen_md_highlight import MarkdownHighlighter
from grafli.zen_md_vim import VimKeyHandler, VimMode


class InlineVimEditor(QPlainTextEdit):
    """Vim-capable single-field editor for in-place editing.

    Signals:
        committed(str): final text, on save-close (Esc in NORMAL, or
            focus loss when ``commit_on_focus_out`` is set).
        cancelled(): discard-close (Shift+Esc in NORMAL).
    """

    committed = Signal(str)
    cancelled = Signal()

    def __init__(
        self,
        text: str = "",
        *,
        markdown: bool = False,
        font: QFont | None = None,
        commit_on_focus_out: bool = True,
        max_lines: int = 24,
        parent=None,
    ):
        super().__init__(parent)
        self._done = False
        self._commit_on_focus_out = commit_on_focus_out
        self._max_lines = max_lines

        if font is not None:
            self.setFont(font)
        self.setPlainText(text)
        self.setFrameShape(QFrame.Shape.NoFrame)  # host supplies chrome
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # No scrollbars on a small canvas editor — they're visual noise and
        # the platform overlay style never spans the box cleanly. Content
        # taller than the box still scrolls via the caret / mouse wheel.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Optional Markdown highlighting (for md: notes). Paragraph-focus
        # dimming is a full-document writing aid — off for a small field.
        self._highlighter: MarkdownHighlighter | None = None
        if markdown:
            self._highlighter = MarkdownHighlighter(self.document())
            self._highlighter.set_focus_enabled(False)
            if font is not None:
                self._highlighter.set_base_size(font.pointSize())

        # Vim — open in INSERT so the field types normally right away.
        self._vim = VimKeyHandler(
            editor=self,
            mode_changed=self._on_mode_changed,
            close_save=self._commit,
            close_cancel=self._cancel,
            initial_mode=VimMode.INSERT,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.moveCursor(QTextCursor.MoveOperation.End)

        # Grow to fit the text as the user types (the host pins the width).
        self.document().documentLayout().documentSizeChanged.connect(
            self._autosize
        )

    # Vertical chrome around the text lines: document margin (4) + the
    # host stylesheet's border (1) + padding (4), top and bottom = 18.
    _CHROME = 18

    @property
    def mode(self) -> VimMode:
        return self._vim.mode

    def minimumSizeHint(self) -> QSize:
        # QPlainTextEdit's default minimum is several lines tall, which a
        # QGraphicsProxyWidget would enforce — leaving an oversized editor
        # with empty space. The host sizes us to fit the content instead.
        return QSize(40, 24)

    def fit_to_width(self, width: int):
        """Set the editor width and grow the height to fit the content.

        The width stays fixed (text wraps to it); height tracks the
        document up to ``max_lines``, after which the editor keeps the
        caret visible by scrolling internally.
        """
        self.resize(width, self.height())
        self._autosize()

    def _autosize(self, *_):
        # QPlainTextDocumentLayout reports document height as a line count
        # (visual lines, wrapping included), not pixels — convert to pixels.
        n_lines = max(self.document().size().height(), 1)
        line_h = self.fontMetrics().lineSpacing()
        wanted = min(n_lines, self._max_lines) * line_h + self._CHROME
        wanted = max(int(wanted), int(line_h + self._CHROME))
        if wanted != self.height():
            self.resize(self.width(), wanted)

    # ── Key routing ──

    def keyPressEvent(self, event: QKeyEvent):
        if self._vim.handle_key(event):
            return
        super().keyPressEvent(event)

    def _on_mode_changed(self, mode: VimMode):
        # macOS input method interferes with normal-mode auto-repeat.
        self.setAttribute(
            Qt.WidgetAttribute.WA_InputMethodEnabled, mode == VimMode.INSERT
        )

    # ── Close paths ──

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self._commit_on_focus_out:
            self._commit()

    def _commit(self):
        if self._done:
            return
        self._done = True
        self.committed.emit(self.toPlainText())

    def _cancel(self):
        if self._done:
            return
        self._done = True
        self.cancelled.emit()
