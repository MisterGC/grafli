"""Zen markdown editor — full-window iA Writer-inspired editing experience."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QFileSystemWatcher,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSettings,
    Qt,
    Signal,
    QTimer,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QKeyEvent,
    QPainter,
    QTextBlockFormat,
    QTextCursor,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QPlainTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from grafli.constants import (
    FONT_FAMILY,
    ZEN_MD_BG,
    ZEN_MD_CANVAS_DIM_COLOR,
    ZEN_MD_CARD_H_RATIO,
    ZEN_MD_CARD_INNER_PAD_H,
    ZEN_MD_CARD_INNER_PAD_V,
    ZEN_MD_CARD_RADIUS,
    ZEN_MD_DIM_COLOR,
    ZEN_MD_FONT_SIZE,
    ZEN_MD_FONT_SIZE_MAX,
    ZEN_MD_FONT_SIZE_MIN,
    ZEN_MD_MAX_WIDTH,
    ZEN_TEXT_COLOR,
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
        canvas: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Translucent so the dim wash painted in paintEvent composites over
        # the parent's content (the graph) instead of obscuring it.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._file_path = file_path
        self._original_text = text
        self._read_only = file_path is not None
        self._watcher = None
        self._autosave_timer: QTimer | None = None
        # The graph canvas widget — the dim wash skips over this rect so
        # the graph itself stays fully saturated while UI chrome dims.
        self._canvas = canvas

        # Load persisted font size preference
        settings = QSettings("Grafli", "Grafli")
        self._font_size = settings.value(
            "zen_md/font_size", ZEN_MD_FONT_SIZE, type=int
        )
        self._font_size = max(
            ZEN_MD_FONT_SIZE_MIN, min(ZEN_MD_FONT_SIZE_MAX, self._font_size)
        )

        # Opacity effect for fade in/out.
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._closing = False

        self.resize(parent.size())
        self._build_ui(title, text)
        self._setup_file_watcher()
        if anchor:
            self._jump_to_anchor(anchor)
        self.show()
        self._start_fade_in()

    # ── UI construction ──

    def _build_ui(self, title: str, text: str):
        self._full_width = False      # ⌘↵ expands the card to the window
        self._rendered_mode = False   # ⌘R shows a read-only rendered view
        layout = QVBoxLayout(self)
        self._apply_card_margins(layout)
        layout.setSpacing(0)

        # Pure text — no title, no hint bar, no badges. Discoverability
        # lives in F1 help; the card is just the writing surface.
        self._editor = QPlainTextEdit(text)
        self._editor.setFont(QFont(FONT_FAMILY, self._font_size))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._editor.setReadOnly(self._read_only)
        self._editor.setStyleSheet(
            f"QPlainTextEdit {{"
            f" background: {ZEN_MD_BG.name()}; color: {ZEN_TEXT_COLOR.name()};"
            f" border: none; padding: 0px;"
            f" selection-background-color: #B8D4E8;"
            f"}}"
        )
        self._editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        layout.addWidget(self._editor, stretch=1)

        # Read-only rendered Markdown view (⌘R toggles editor <-> this).
        self._rendered = QTextBrowser()
        self._rendered.setOpenExternalLinks(True)
        self._rendered.setFont(QFont(FONT_FAMILY, self._font_size))
        self._rendered.setStyleSheet(
            f"QTextBrowser {{"
            f" background: {ZEN_MD_BG.name()}; color: {ZEN_TEXT_COLOR.name()};"
            f" border: none; padding: 0px;"
            f" selection-background-color: #B8D4E8;"
            f"}}"
        )
        self._rendered.setVisible(False)
        self._rendered.installEventFilter(self)
        layout.addWidget(self._rendered, stretch=1)

        # Markdown highlighter + paragraph focus (disabled in read-only mode)
        self._highlighter = MarkdownHighlighter(self._editor.document())
        self._highlighter.set_base_size(self._font_size)
        self._editor.cursorPositionChanged.connect(self._update_focus)
        if self._read_only:
            self._highlighter.set_focus_enabled(False)

        # Heading gutter — `#` markers hang to the left of body text.
        self._applying_layout = False
        self._apply_heading_layout()
        self._editor.textChanged.connect(self._on_text_changed_layout)

        # Vim key handler
        self._vim = VimKeyHandler(
            editor=self._editor,
            mode_changed=self._on_mode_changed,
            close_save=self._close_save,
            close_cancel=self._close_cancel,
        )
        self._editor.setOverwriteMode(True)  # block cursor in normal mode
        self._editor.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, False)
        self._editor.installEventFilter(self)  # intercept keys before editor

        # Word jump overlay
        self._jump: WordJumpOverlay | None = None

        # Focus and cursor
        self._editor.setFocus()
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self._editor.setTextCursor(cursor)
        self._update_focus()

    def _on_mode_changed(self, mode: VimMode):
        # Disable macOS input method in normal mode to prevent IMK
        # interference with auto-repeat key events.
        self._editor.setAttribute(
            Qt.WidgetAttribute.WA_InputMethodEnabled,
            mode == VimMode.INSERT,
        )

    def _start_fade_in(self):
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(320)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_in_anim = anim  # hold ref so it doesn't get GC'd mid-run

    def _close_save(self):
        if self._file_path:
            self._fade_out_and_close(self._emit_cancelled)
        else:
            captured = self._editor.toPlainText()
            self._fade_out_and_close(lambda: self._emit_finished(captured))

    def _close_cancel(self):
        self._fade_out_and_close(self._emit_cancelled)

    def _emit_cancelled(self):
        self.cancelled.emit()
        self.close()

    def _emit_finished(self, text: str):
        self.finished.emit(text)
        self.close()

    def _fade_out_and_close(self, callback):
        if self._closing:
            return
        self._closing = True
        anim = QPropertyAnimation(self._opacity, b"opacity", self)
        anim.setDuration(240)
        anim.setStartValue(self._opacity.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.InCubic)
        anim.finished.connect(callback)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_out_anim = anim

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

    # ── Heading-gutter layout ──

    _RE_HEADING_PREFIX = re.compile(r"^(#{1,3})\s+")

    def _gutter_metrics(self) -> tuple[float, float]:
        """Return (char_width, gutter_width). Gutter fits the longest
        heading marker (`### ` = 4 chars).
        """
        char_w = QFontMetricsF(self._editor.font()).horizontalAdvance(" ")
        return char_w, char_w * 4

    def _apply_block_layout(self, block) -> None:
        """Set the block's leftMargin/textIndent so heading `#`s hang in
        the gutter and heading text aligns with body text.
        """
        char_w, gutter = self._gutter_metrics()
        m = self._RE_HEADING_PREFIX.match(block.text())
        fmt = QTextBlockFormat()
        fmt.setLeftMargin(gutter)
        if m:
            level = len(m.group(1))
            fmt.setTextIndent(-char_w * (level + 1))
        else:
            fmt.setTextIndent(0)
        current = block.blockFormat()
        if (current.leftMargin() == fmt.leftMargin()
                and current.textIndent() == fmt.textIndent()):
            return
        cursor = QTextCursor(block)
        self._applying_layout = True
        try:
            cursor.setBlockFormat(fmt)
        finally:
            self._applying_layout = False

    def _apply_heading_layout(self) -> None:
        """Apply heading-gutter layout to every block in the document."""
        doc = self._editor.document()
        block = doc.firstBlock()
        while block.isValid():
            self._apply_block_layout(block)
            block = block.next()

    def _on_text_changed_layout(self) -> None:
        """Re-apply layout to the block under the cursor on every edit."""
        if self._applying_layout:
            return
        self._apply_block_layout(self._editor.textCursor().block())

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
        self._apply_heading_layout()
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

    def _toggle_full_width(self):
        """⌘↵: expand the card to fill the window (and back to the column)."""
        self._full_width = not self._full_width
        layout = self.layout()
        if layout:
            self._apply_card_margins(layout)
        self._apply_heading_layout()
        self.update()

    def _toggle_rendered(self):
        """⌘R: switch between the source editor and a read-only rendered
        Markdown view — a quick read perspective <-> edit perspective."""
        self._rendered_mode = not self._rendered_mode
        if self._rendered_mode:
            self._rendered.setFont(QFont(FONT_FAMILY, self._font_size))
            self._rendered.document().setMarkdown(self._editor.toPlainText())
            self._editor.setVisible(False)
            self._rendered.setVisible(True)
            self._rendered.setFocus()
        else:
            self._rendered.setVisible(False)
            self._editor.setVisible(True)
            self._editor.setFocus()
        self.update()

    # ── Modal card geometry ──

    def _card_rect(self) -> QRectF:
        """Card width hugs the text column (ZEN_MD_MAX_WIDTH + padding);
        height takes most of the window. Centered. In full-width mode (⌘↵) the
        card grows to nearly fill the window.
        """
        max_w = max(self.width() - 80, 320)
        if getattr(self, "_full_width", False):
            w = max_w
            h = max(self.height() - 40, 320)
        else:
            desired_w = ZEN_MD_MAX_WIDTH + 2 * ZEN_MD_CARD_INNER_PAD_H
            w = min(desired_w, max_w)
            h = min(self.height() * ZEN_MD_CARD_H_RATIO, self.height() - 60)
        x = (self.width() - w) / 2
        y = (self.height() - h) / 2
        return QRectF(x, y, w, h)

    def _apply_card_margins(self, layout):
        """Anchor layout margins inside the card with comfortable padding."""
        card = self._card_rect()
        h_outside = (self.width() - card.width()) / 2
        v_outside = (self.height() - card.height()) / 2
        layout.setContentsMargins(
            int(h_outside + ZEN_MD_CARD_INNER_PAD_H),
            int(v_outside + ZEN_MD_CARD_INNER_PAD_V),
            int(h_outside + ZEN_MD_CARD_INNER_PAD_H),
            int(v_outside + ZEN_MD_CARD_INNER_PAD_V),
        )

    def _canvas_rect_in_self(self) -> QRect | None:
        """Return the canvas widget's geometry in this widget's coord space,
        or None if no canvas was supplied / it isn't visible.
        """
        if not self._canvas or not self._canvas.isVisible():
            return None
        top_left = self.mapFromGlobal(self._canvas.mapToGlobal(QPoint(0, 0)))
        return QRect(top_left, self._canvas.size())

    # ── Paint ──

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dim wash — chrome gets the full wash; canvas gets a gentler dim
        # so the graph stays readable but visibly steps back. Both fade
        # together with the widget's opacity effect.
        canvas = self._canvas_rect_in_self()
        full = self.rect()
        if canvas is None or not full.intersects(canvas):
            p.fillRect(full, ZEN_MD_DIM_COLOR)
        else:
            clipped = canvas.intersected(full)
            # Four chrome strips — full dim.
            if clipped.top() > full.top():
                p.fillRect(
                    QRect(full.left(), full.top(),
                          full.width(), clipped.top() - full.top()),
                    ZEN_MD_DIM_COLOR,
                )
            if clipped.bottom() < full.bottom():
                p.fillRect(
                    QRect(full.left(), clipped.bottom() + 1,
                          full.width(), full.bottom() - clipped.bottom()),
                    ZEN_MD_DIM_COLOR,
                )
            if clipped.left() > full.left():
                p.fillRect(
                    QRect(full.left(), clipped.top(),
                          clipped.left() - full.left(), clipped.height()),
                    ZEN_MD_DIM_COLOR,
                )
            if clipped.right() < full.right():
                p.fillRect(
                    QRect(clipped.right() + 1, clipped.top(),
                          full.right() - clipped.right(), clipped.height()),
                    ZEN_MD_DIM_COLOR,
                )
            # Canvas — gentler dim, animates with the editor's opacity.
            p.fillRect(clipped, ZEN_MD_CANVAS_DIM_COLOR)

        # Drop shadow, then the solid writing card on top.
        card = self._card_rect()
        self._paint_card_shadow(p, card)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ZEN_MD_BG))
        p.drawRoundedRect(card, ZEN_MD_CARD_RADIUS, ZEN_MD_CARD_RADIUS)

        p.end()

    def _paint_card_shadow(self, painter: QPainter, card: QRectF):
        """Soft drop shadow around the card. Painted before the card; the
        opaque card covers the inside, so only the spillover at the edges
        shows. Layers stack outward with decreasing alpha, biased downward
        for gravity.
        """
        drop = 6  # downward bias
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(1, 14):
            alpha = 20 - i * 2
            if alpha <= 0:
                break
            painter.setBrush(QBrush(QColor(0, 0, 0, alpha)))
            shadow = QRectF(
                card.left() - i,
                card.top() - i + drop // 2,
                card.width() + 2 * i,
                card.height() + 2 * i + drop // 2,
            )
            painter.drawRoundedRect(
                shadow, ZEN_MD_CARD_RADIUS + i, ZEN_MD_CARD_RADIUS + i,
            )


    # ── Resize tracking ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        layout = self.layout()
        if layout:
            self._apply_card_margins(layout)

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
        if (obj in (self._editor, self._rendered)
                and event.type() == QEvent.Type.KeyPress):
            return self._handle_key(event)
        return False

    # ── Key handling ──

    def _handle_key(self, event: QKeyEvent) -> bool:
        """Central key router. Returns True if event is consumed."""
        # Jump overlay consumes all keys while active
        if self._jump and self._jump.is_active():
            self._jump.keyPressEvent(event)
            return True

        # Ctrl+R — toggle rendered read-only view <-> source editor
        if (event.key() == Qt.Key.Key_R
                and event.modifiers() & _CTRL_MOD):
            self._toggle_rendered()
            return True

        # Ctrl+Enter — toggle full-window width (works in either view)
        if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & _CTRL_MOD):
            self._toggle_full_width()
            return True

        # In rendered mode only Esc (save / cancel) is handled; everything else
        # falls through so the browser can scroll.
        if self._rendered_mode:
            if event.key() == Qt.Key.Key_Escape:
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    self._close_cancel()
                else:
                    self._close_save()
                return True
            return False

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

        # Ctrl +/-/0 — font size zoom
        if event.modifiers() & _CTRL_MOD:
            if event.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self._change_font_size(+1)
                return True
            if event.key() == Qt.Key.Key_Minus:
                self._change_font_size(-1)
                return True
            if event.key() == Qt.Key.Key_0:
                self._change_font_size(0)
                return True

        # Route through vim handler
        return self._vim.handle_key(event)

    def _change_font_size(self, delta: int):
        """Change font size. delta=0 resets to default."""
        if delta == 0:
            new_size = ZEN_MD_FONT_SIZE
        else:
            new_size = max(
                ZEN_MD_FONT_SIZE_MIN,
                min(ZEN_MD_FONT_SIZE_MAX, self._font_size + delta),
            )
        if new_size == self._font_size:
            return
        self._font_size = new_size
        self._editor.setFont(QFont(FONT_FAMILY, self._font_size))
        self._highlighter.set_base_size(self._font_size)
        # Gutter width is char-based; re-apply after font change.
        self._apply_heading_layout()
        QSettings("Grafli", "Grafli").setValue(
            "zen_md/font_size", self._font_size
        )

    def _activate_jump(self):
        if self._jump is None:
            self._jump = WordJumpOverlay(self._editor, self)
        self._jump.activate()

    # ── Public API ──

    def editor(self) -> QPlainTextEdit:
        return self._editor

    def set_hint(self, text: str):
        self._hint.setText(text)
