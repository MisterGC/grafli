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
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QPlainTextEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from grafli import md_comments
from grafli.constants import (
    FONT_FAMILY,
    ZEN_MD_BG,
    ZEN_MD_CANVAS_DIM_COLOR,
    ZEN_MD_COMMENT_HL,
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

# Custom char-format property tagging a rendered span with its comment index,
# so the reveal/navigate loop can map a highlighted span back to its source
# comment even when inline formatting splits the span into fragments.
_COMMENT_IDX_PROP = QTextFormat.Property.UserProperty + 7


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
        # The editor always opens editable; reading is the ⌘R rendered view.
        self._read_only = False
        # Section-focus dim (everything but the current paragraph) — off by
        # default, toggled with ⌘.
        self._focus_enabled = False
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
        self._enable_autosave()
        if anchor:
            self._jump_to_anchor(anchor)
        self.show()
        self._start_fade_in()

    # ── UI construction ──

    def _build_ui(self, title: str, text: str):
        self._full_width = False      # ⌘↵ expands the card to the window
        self._rendered_mode = False   # ⌘R shows a read-only rendered view
        # Read-view comment interaction state — initialized before any child
        # widget is built, since installing event filters can fire eventFilter
        # (which references these) during construction. _rendered_comments maps
        # each highlighted span to its source Comment; _active_comment is the
        # one ]c / [c stepped onto; _comment_field is the inline reveal editor.
        self._rendered_comments: list = []
        self._active_comment = -1
        self._comment_field: QPlainTextEdit | None = None
        self._rendered_pending_bracket = ""
        # Authoring: vim visual mode in the read view selects the span to comment.
        self._visual = False
        self._authoring_span: tuple | None = None
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
        # Keyboard-selectable so the read view has a movable caret for vim
        # motions and visual-mode span selection (it stays read-only).
        self._rendered.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self._rendered.setVisible(False)
        self._rendered.installEventFilter(self)
        layout.addWidget(self._rendered, stretch=1)

        # Markdown highlighter + paragraph focus (off by default; ⌘. toggles)
        self._highlighter = MarkdownHighlighter(self._editor.document())
        self._highlighter.set_base_size(self._font_size)
        self._editor.cursorPositionChanged.connect(self._update_focus)
        self._highlighter.set_focus_enabled(self._focus_enabled)

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
            self._autosave()   # flush any pending edit before closing
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
        if not self._focus_enabled:
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

    def _enable_autosave(self):
        """Doc-backed notes open editable, so wire up autosave from the start
        (debounced) — the editor owns the file while open."""
        if not self._file_path:
            return
        if self._watcher:
            self._watcher.removePath(str(self._file_path))
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._autosave)
        self._editor.textChanged.connect(self._schedule_autosave)

    def _toggle_focus(self):
        """⌘. — toggle the section-focus dim (everything but the current
        paragraph). Off by default."""
        self._focus_enabled = not self._focus_enabled
        self._highlighter.set_focus_enabled(self._focus_enabled)
        if self._focus_enabled:
            self._update_focus()
        self.update()

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
        self._highlighter.set_focus_enabled(self._focus_enabled)

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
            self._active_comment = -1
            self._rendered_pending_bracket = ""
            self._visual = False
            self._authoring_span = None
            self._rendered.setFont(QFont(FONT_FAMILY, self._font_size))
            self._render_markdown(self._editor.toPlainText())
            self._editor.setVisible(False)
            self._rendered.setVisible(True)
            self._rendered.setFocus()
            cur = self._rendered.textCursor()    # caret at top for vim motions
            cur.setPosition(0)
            self._rendered.setTextCursor(cur)
        else:
            self._hide_comment_field()
            self._rendered.setVisible(False)
            self._editor.setVisible(True)
            self._editor.setFocus()
        self.update()

    def _render_markdown(self, source: str):
        """Render ``source`` into the read view, with inline comments stripped
        and their spans highlighted. The comment bodies stay hidden — they are
        revealed only on demand (cursor-driven, added in a later phase)."""
        md, comments = md_comments.to_sentineled(source)
        doc = self._rendered.document()
        doc.setMarkdown(md)
        self._highlight_comment_spans(doc, comments)

    def _highlight_comment_spans(self, doc, comments):
        """Find each sentinel-wrapped span in the rendered document, paint the
        subtle comment highlight over it, tag it with its comment index, and
        delete the sentinel markers. Builds ``self._rendered_comments`` — the
        rendered-range → source-``Comment`` map the reveal/navigate loop uses.

        Located via ``QTextDocument.find`` (not raw string indexing) so the
        positions stay correct even when the render inserts position-bearing
        objects (images, rules) ahead of a span.
        """
        self._rendered_comments = []
        if not comments:
            return
        # Collect each span's sentinel bounds, in document order.
        spans = []
        pos = 0
        for _ in comments:
            start = doc.find(md_comments.SENTINEL_START, pos)
            if start.isNull():
                break
            end = doc.find(md_comments.SENTINEL_END, start.selectionEnd())
            if end.isNull():
                break
            spans.append((start.selectionStart(), start.selectionEnd(),
                          end.selectionStart(), end.selectionEnd()))
            pos = end.selectionEnd()
        # Apply last-to-first so deletions don't shift not-yet-processed offsets.
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        for i in range(len(spans) - 1, -1, -1):
            s0, s1, e0, e1 = spans[i]
            fmt = QTextCharFormat()
            fmt.setBackground(QBrush(ZEN_MD_COMMENT_HL))
            fmt.setProperty(_COMMENT_IDX_PROP, i)   # tag span -> comment index
            edit.setPosition(s1)
            edit.setPosition(e0, QTextCursor.MoveMode.KeepAnchor)
            edit.mergeCharFormat(fmt)               # highlight the span text
            edit.setPosition(e0)
            edit.setPosition(e1, QTextCursor.MoveMode.KeepAnchor)
            edit.removeSelectedText()               # drop END sentinel
            edit.setPosition(s0)
            edit.setPosition(s1, QTextCursor.MoveMode.KeepAnchor)
            edit.removeSelectedText()               # drop START sentinel
        edit.endEditBlock()
        self._rendered_comments = self._collect_rendered_comments(doc, comments)

    def _collect_rendered_comments(self, doc, comments):
        """Walk the rendered document's fragments and, for each comment index
        tagged on a span, recover its [start, end) range — robust to the span
        being split into several fragments by inline formatting."""
        bounds: dict[int, tuple[int, int]] = {}
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                cf = frag.charFormat()
                if cf.hasProperty(_COMMENT_IDX_PROP):
                    idx = cf.intProperty(_COMMENT_IDX_PROP)
                    a = frag.position()
                    b = a + frag.length()
                    lo, hi = bounds.get(idx, (a, b))
                    bounds[idx] = (min(lo, a), max(hi, b))
                it += 1
            block = block.next()
        return [(bounds[i][0], bounds[i][1], comments[i])
                for i in sorted(bounds)]

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
        if (getattr(self, "_comment_field", None) is not None
                and obj is self._comment_field
                and event.type() == QEvent.Type.KeyPress):
            return self._handle_comment_field_key(event)
        if (obj in (self._editor, self._rendered)
                and event.type() == QEvent.Type.KeyPress):
            return self._handle_key(event)
        return False

    def _handle_comment_field_key(self, event: QKeyEvent) -> bool:
        """Keys while the inline comment editor is open: Esc commits and returns
        to undisturbed reading; ⇧Esc cancels the edit; ⌃↵ also commits. Plain
        Enter inserts a newline in the comment as usual."""
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key == Qt.Key.Key_Escape:
            if shift:
                self._hide_comment_field()      # ⇧Esc — discard the edit
            else:
                self._commit_comment_field()    # Esc — save and back to reading
            return True
        if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and event.modifiers() & _CTRL_MOD):
            self._commit_comment_field()
            return True
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

        # Ctrl+. — toggle section-focus dim (works in either view)
        if (event.key() == Qt.Key.Key_Period
                and event.modifiers() & _CTRL_MOD):
            self._toggle_focus()
            return True

        # Rendered view: vim-style navigation; Esc saves & closes.
        if self._rendered_mode:
            return self._handle_rendered_key(event)

        # Ctrl+J — activate word jump
        if (event.key() == Qt.Key.Key_J
                and event.modifiers() & _CTRL_MOD):
            self._activate_jump()
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

    def _handle_rendered_key(self, event: QKeyEvent) -> bool:
        """Vim-style read view. Motions move a caret (h/l/j/k, w/b/e, 0/$, gg/G,
        Ctrl-d/u half-page, Ctrl-f/b/Space page). `v` enters visual mode so the
        same motions extend a selection; `c` comments the selection. `]c`/`[c`
        step between comments, Enter reveals/edits one, ⇧D deletes. Esc leaves
        visual mode, or — when not selecting — saves & closes (⇧Esc cancels)."""
        key = event.key()
        mods = event.modifiers()
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & _CTRL_MOD)
        MO = QTextCursor.MoveOperation

        # ]c / [c — step to the next / previous comment (two-key, vim diff-style).
        if self._rendered_pending_bracket:
            pending = self._rendered_pending_bracket
            self._rendered_pending_bracket = ""
            if key == Qt.Key.Key_C:
                self._goto_comment(1 if pending == "]" else -1)
                return True
        if key == Qt.Key.Key_BracketRight and not shift:
            self._rendered_pending_bracket = "]"
            return True
        if key == Qt.Key.Key_BracketLeft and not shift:
            self._rendered_pending_bracket = "["
            return True

        # `gg` — two-key jump to top.
        if key == Qt.Key.Key_G and not shift:
            if getattr(self, "_rendered_pending_g", False):
                self._rendered_pending_g = False
                self._caret_move(MO.Start)
            else:
                self._rendered_pending_g = True
            return True
        self._rendered_pending_g = False

        # v — toggle visual (selection) mode. c — comment the selection.
        if key == Qt.Key.Key_V and not ctrl:
            self._set_visual(not self._visual)
            return True
        if key == Qt.Key.Key_C and not ctrl and not shift:
            self._comment_selection()
            return True

        # Enter — reveal/edit the active comment inline. ⇧D — delete it.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not ctrl:
            self._reveal_active_comment()
            return True
        if key == Qt.Key.Key_D and shift:
            self._delete_active_comment()
            return True

        # Esc — leave visual mode if selecting; otherwise save & close.
        if key == Qt.Key.Key_Escape:
            if self._visual:
                self._set_visual(False)
            else:
                self._close_cancel() if shift else self._close_save()
            return True

        # Caret motions — extend the selection when in visual mode.
        if key == Qt.Key.Key_G and shift:                 # G — bottom
            self._caret_move(MO.End)
            return True
        if key in (Qt.Key.Key_H, Qt.Key.Key_Left):
            self._caret_move(MO.Left)
            return True
        if key in (Qt.Key.Key_L, Qt.Key.Key_Right):
            self._caret_move(MO.Right)
            return True
        if key in (Qt.Key.Key_J, Qt.Key.Key_Down):
            self._caret_move(MO.Down)
            return True
        if key in (Qt.Key.Key_K, Qt.Key.Key_Up):
            self._caret_move(MO.Up)
            return True
        if key == Qt.Key.Key_W and not ctrl:
            self._caret_move(MO.NextWord)
            return True
        if key == Qt.Key.Key_B and not ctrl:
            self._caret_move(MO.PreviousWord)
            return True
        if key == Qt.Key.Key_E and not ctrl:
            self._caret_move(MO.EndOfWord)
            return True
        if key == Qt.Key.Key_0 and not ctrl:
            self._caret_move(MO.StartOfLine)
            return True
        if key == Qt.Key.Key_Dollar:
            self._caret_move(MO.EndOfLine)
            return True
        if ctrl and key == Qt.Key.Key_D:
            self._caret_move(MO.Down, self._page_lines(0.5))
            return True
        if ctrl and key == Qt.Key.Key_U:
            self._caret_move(MO.Up, self._page_lines(0.5))
            return True
        if key in (Qt.Key.Key_Space, Qt.Key.Key_PageDown) or (
                ctrl and key == Qt.Key.Key_F):
            self._caret_move(MO.Down, self._page_lines(1.0))
            return True
        if key == Qt.Key.Key_PageUp or (ctrl and key == Qt.Key.Key_B):
            self._caret_move(MO.Up, self._page_lines(1.0))
            return True
        return False

    def _caret_move(self, op, count: int = 1):
        """Move the read-view caret by ``op`` × ``count``; in visual mode keep
        the anchor so the selection extends."""
        mode = (QTextCursor.MoveMode.KeepAnchor if self._visual
                else QTextCursor.MoveMode.MoveAnchor)
        cur = self._rendered.textCursor()
        cur.movePosition(op, mode, count)
        self._rendered.setTextCursor(cur)
        self._rendered.ensureCursorVisible()

    def _page_lines(self, frac: float) -> int:
        """Number of text lines in ``frac`` of the viewport (for page motions)."""
        line_h = max(1, int(QFontMetricsF(self._rendered.font()).height()))
        return max(1, int(self._rendered.viewport().height() * frac / line_h))

    def _set_visual(self, on: bool):
        """Enter/leave visual mode. Entering anchors the selection at the caret;
        leaving collapses any selection back to undisturbed reading."""
        self._visual = on
        cur = self._rendered.textCursor()
        if on:
            cur.setPosition(cur.position())   # collapse → anchor at caret
        else:
            cur.clearSelection()
        self._rendered.setTextCursor(cur)

    def _comment_selection(self):
        """c — comment the visual selection; or, with no selection, reveal/edit
        the comment the caret is sitting on (so you can jump straight to editing
        an existing comment without `]c` or visual mode)."""
        cur = self._rendered.textCursor()
        if cur.hasSelection():
            r0, r1 = cur.selectionStart(), cur.selectionEnd()
            self._set_visual(False)
            self._begin_comment_for_span(r0, r1)
            return
        idx = self._comment_at_position(cur.position())
        if idx >= 0:
            self._set_active_comment(idx)
            self._reveal_active_comment()

    def _comment_at_position(self, pos: int) -> int:
        """Index of the rendered comment whose span contains ``pos``, else -1."""
        for i, (start, end, _c) in enumerate(self._rendered_comments):
            if start <= pos <= end:
                return i
        return -1

    # ── Read-view comment interaction ──

    def _goto_comment(self, direction: int):
        """Step the active comment forward (+1) or back (-1), wrapping, and
        scroll it into view. From no active comment, land on the first / last."""
        comments = self._rendered_comments
        if not comments:
            return
        n = len(comments)
        if self._active_comment < 0:
            idx = 0 if direction > 0 else n - 1
        else:
            idx = (self._active_comment + direction) % n
        self._set_active_comment(idx)

    def _set_active_comment(self, idx: int):
        """Mark comment ``idx`` active: select its span (the native selection
        marks it atop the amber highlight) and scroll it into view."""
        self._active_comment = idx
        start, end, _comment = self._rendered_comments[idx]
        cur = self._rendered.textCursor()
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        self._rendered.setTextCursor(cur)
        self._rendered.ensureCursorVisible()

    def _reveal_active_comment(self):
        """Show the inline editable field for the active comment (Enter). With
        no active comment yet, land on the first one and reveal it."""
        if not self._rendered_comments:
            return
        if self._active_comment < 0:
            self._set_active_comment(0)
        _start, end, comment = self._rendered_comments[self._active_comment]
        self._show_comment_field(end, comment.body)

    def _show_comment_field(self, end_pos: int, body: str):
        """Place the inline comment editor just below the active span."""
        field = self._comment_field
        if field is None:
            field = QPlainTextEdit(self._rendered.viewport())
            field.setFont(QFont(
                FONT_FAMILY, max(ZEN_MD_FONT_SIZE_MIN, self._font_size - 2)))
            field.setStyleSheet(
                f"QPlainTextEdit {{"
                f" background: #FBF7EC; color: {ZEN_TEXT_COLOR.name()};"
                f" border: 1px solid #C9A227; border-radius: 6px;"
                f" padding: 6px;"
                f" selection-background-color: #B8D4E8;"
                f"}}"
            )
            field.installEventFilter(self)
            self._comment_field = field
        field.setPlainText(body)
        cur = self._rendered.textCursor()
        cur.setPosition(end_pos)
        rect = self._rendered.cursorRect(cur)
        vp = self._rendered.viewport()
        w = min(380, vp.width() - 24)
        field.setFixedWidth(w)
        field.setFixedHeight(84)
        x = max(8, min(rect.left(), vp.width() - w - 8))
        y = min(rect.bottom() + 4, vp.height() - field.height() - 8)
        field.move(x, max(8, y))
        field.show()
        field.setFocus()
        field.moveCursor(QTextCursor.MoveOperation.End)

    def _hide_comment_field(self):
        if self._comment_field is not None:
            self._comment_field.hide()
        self._rendered.setFocus()

    def _commit_comment_field(self):
        """Commit the field. For a new comment (authoring), wrap the picked span;
        for an existing one, write the edited body back. An emptied body abandons
        a new comment / deletes an edited one. Then re-render, back to reading."""
        if self._comment_field is None:
            return
        body = self._comment_field.toPlainText().strip()
        if self._authoring_span is not None:
            self._commit_new_comment(body)
            return
        if self._active_comment < 0:
            return
        _s, _e, comment = self._rendered_comments[self._active_comment]
        src = self._editor.toPlainText()
        if body:
            src = md_comments.set_body(src, comment, body)
        else:
            src = md_comments.remove(src, comment)   # emptied → delete
        idx = self._active_comment
        self._hide_comment_field()
        self._set_source_text(src)
        self._render_markdown(src)
        if self._rendered_comments:
            self._set_active_comment(min(idx, len(self._rendered_comments) - 1))
        else:
            self._active_comment = -1

    # ── Authoring: comment the visual selection ──

    def _begin_comment_for_span(self, r0: int, r1: int):
        """Map the rendered span back to source; if it maps, open an empty field
        to type the comment; if not, fall back to the source editor."""
        rendered = self._rendered.document().toPlainText()
        src = self._editor.toPlainText()
        mapped = md_comments.map_rendered_span(rendered, src, r0, r1)
        if mapped is None:
            self._fallback_to_source(None)
            return
        s0, s1 = mapped
        # Overlap-aware (no nesting): inside an existing comment → edit it;
        # straddling one → refuse quietly rather than corrupt the markup.
        overlap = md_comments.classify_overlap(src, s0, s1)
        if overlap is not None:
            kind, idx = overlap
            if kind == "inside" and idx < len(self._rendered_comments):
                self._set_active_comment(idx)
                self._reveal_active_comment()
            return
        self._authoring_span = (s0, s1, rendered[r0:r1])
        cur = self._rendered.textCursor()
        cur.setPosition(r0)
        cur.setPosition(r1, QTextCursor.MoveMode.KeepAnchor)
        self._rendered.setTextCursor(cur)        # show what will be commented
        self._show_comment_field(r1, "")

    def _commit_new_comment(self, body: str):
        """Wrap the authored span in CriticMarkup. Validate by re-rendering and
        confirming a comment now highlights the same visible text; if the mapping
        was off, revert and fall back to the source pane."""
        s0, s1, sel = self._authoring_span
        self._authoring_span = None
        self._hide_comment_field()
        if not body:
            return                               # abandoned — no comment created
        src = self._editor.toPlainText()
        new_src = md_comments.wrap(src, s0, s1, body)
        self._set_source_text(new_src)
        self._render_markdown(new_src)
        idx = self._find_rendered_comment(sel, body)
        if idx is None:                          # mapping was wrong — undo
            self._set_source_text(src)
            self._render_markdown(src)
            self._fallback_to_source((s0, s1))
            return
        self._set_active_comment(idx)

    def _find_rendered_comment(self, span_text: str, body: str):
        """Index of the rendered comment whose span renders as ``span_text`` and
        whose body is ``body`` — used to confirm a freshly authored comment."""
        for i, (start, end, comment) in enumerate(self._rendered_comments):
            if comment.body != body:
                continue
            cur = self._rendered.textCursor()
            cur.setPosition(start)
            cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            if cur.selectedText() == span_text:
                return i
        return None

    def _fallback_to_source(self, slice_):
        """Couldn't map a rendered selection — drop to the source editor so the
        span can be marked precisely there. Pre-select ``slice_`` when known."""
        self._authoring_span = None
        if self._rendered_mode:
            self._toggle_rendered()
        if slice_ is not None:
            s0, s1 = slice_
            cur = self._editor.textCursor()
            cur.setPosition(s0)
            cur.setPosition(s1, QTextCursor.MoveMode.KeepAnchor)
            self._editor.setTextCursor(cur)

    def _delete_active_comment(self):
        """⇧D — unwrap the active comment (highlight + body gone), re-render."""
        if not (0 <= self._active_comment < len(self._rendered_comments)):
            return
        _s, _e, comment = self._rendered_comments[self._active_comment]
        idx = self._active_comment
        src = md_comments.remove(self._editor.toPlainText(), comment)
        self._hide_comment_field()
        self._set_source_text(src)
        self._render_markdown(src)
        if self._rendered_comments:
            self._set_active_comment(min(idx, len(self._rendered_comments) - 1))
        else:
            self._active_comment = -1

    def _set_source_text(self, src: str):
        """Replace the source buffer (fires heading layout + autosave)."""
        self._editor.setPlainText(src)

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
