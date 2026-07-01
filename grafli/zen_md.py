"""Zen markdown editor — full-window iA Writer-inspired editing experience."""

from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QEventLoop,
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
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
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
    ZEN_MD_SUGGEST_ADD,
    ZEN_MD_CARD_H_RATIO,
    ZEN_MD_CARD_INNER_PAD_H,
    ZEN_MD_CARD_INNER_PAD_V,
    ZEN_MD_CARD_RADIUS,
    ZEN_MD_DIM_COLOR,
    ZEN_MD_FONT_SIZE,
    ZEN_MD_FONT_SIZE_MAX,
    ZEN_MD_FONT_SIZE_MIN,
    ZEN_MD_MAX_WIDTH,
    ZEN_MD_MAX_WIDTH_MAX,
    ZEN_MD_MAX_WIDTH_MIN,
    ZEN_MD_WIDTH_STEP,
    ZEN_TEXT_COLOR,
    _CTRL_MOD,
)
from grafli.zen_md_highlight import MarkdownHighlighter, compute_focus_range
from grafli.zen_md_jump import WordJumpOverlay
from grafli.zen_md_suggest import SuggestionAnimator
from grafli.zen_md_vim import VimKeyHandler, VimMode

# Custom char-format property tagging a rendered span with its comment index,
# so the reveal/navigate loop can map a highlighted span back to its source
# comment even when inline formatting splits the span into fragments.
_COMMENT_IDX_PROP = QTextFormat.Property.UserProperty + 7
# Same idea for a suggestion: both spans of a substitution carry the same index,
# so its rendered range (struck-old through handwritten-new) recovers as one unit.
_SUGGEST_IDX_PROP = QTextFormat.Property.UserProperty + 8
# Role of a suggestion fragment (0 = removed/struck, 1 = added), so the animator
# can fade the part that leaves and settle the part that stays.
_SUGGEST_ROLE_PROP = QTextFormat.Property.UserProperty + 9
_ROLE_REMOVED, _ROLE_ADDED = 0, 1

# A rendered suggestion: its overall [start, end) range, the source ``Mark``, and
# the rendered sub-ranges of its removed (struck) and added (handwritten) text —
# either may be None (an insertion has no removed; a deletion no added).
RSuggestion = namedtuple("RSuggestion", "start end mark removed added")


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
        start_in_read: bool = False,
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

        # Load persisted content-column width preference (adjustable like font).
        self._content_width = settings.value(
            "zen_md/content_width", ZEN_MD_MAX_WIDTH, type=int
        )
        self._content_width = max(
            ZEN_MD_MAX_WIDTH_MIN, min(ZEN_MD_MAX_WIDTH_MAX, self._content_width)
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
        self.show()
        self._start_fade_in()
        # Open at a location / in a mode (used by textli's open-at-anchor). The
        # read-view toggle and centerCursor both need a laid-out viewport, so do
        # this after show().
        if start_in_read:
            self._toggle_rendered()
        if anchor:
            self._jump_to_anchor(anchor)

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
        self._rendered_suggestions: list = []
        # Play the accept/reject animation (tests turn this off for determinism).
        self._suggest_animate = True
        self._active_comment = -1
        self._comment_field: QPlainTextEdit | None = None
        self._rendered_pending_bracket = ""
        # Authoring: vim visual mode in the read view selects the span to comment.
        self._visual = False
        self._authoring_span: tuple | None = None
        # True while the inline field is authoring a suggestion (vs a comment).
        self._authoring_suggestion = False
        # Transient READ/WRITE flash shown when toggling the rendered view.
        self._mode_flash: QLabel | None = None
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

        # Animates accept/reject on the read view (fade what leaves, settle what
        # stays) before the source edit lands.
        self._suggest_animator = SuggestionAnimator(
            self._rendered,
            body_color=ZEN_TEXT_COLOR,
            body_family=FONT_FAMILY,
            del_color=ZEN_TEXT_COLOR,   # removals are body-ink now (just struck)
            add_color=ZEN_MD_SUGGEST_ADD,
        )

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
        """Scroll to the heading matching the given anchor slug, in whichever
        view is active. In the source editor a heading carries its `#` markers;
        in the rendered read view they're gone, so identify headings by their
        block heading-level (set by Markdown rendering) and match the bare text."""
        rendered = self._rendered_mode
        view = self._rendered if rendered else self._editor
        doc = view.document()
        block = doc.begin()
        while block.isValid():
            if rendered:
                is_heading = block.blockFormat().headingLevel() > 0
                heading = block.text() if is_heading else None
            else:
                m = re.match(r"^#{1,6}\s+(.*)", block.text())
                heading = m.group(1) if m else None
            if heading is not None and self._slugify(heading) == anchor:
                cursor = view.textCursor()
                cursor.setPosition(block.position())
                view.setTextCursor(cursor)
                if rendered:
                    # QTextBrowser has no centerCursor — scroll the heading to
                    # the top of the viewport (natural for an anchor landing).
                    y = int(doc.documentLayout().blockBoundingRect(block).y())
                    view.verticalScrollBar().setValue(y)
                else:
                    view.centerCursor()
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
            self._authoring_suggestion = False
            src = self._editor.toPlainText()
            src_caret = self._editor.textCursor().position()
            self._rendered.setFont(QFont(FONT_FAMILY, self._font_size))
            self._render_markdown(src)
            self._editor.setVisible(False)
            self._rendered.setVisible(True)
            self._rendered.setFocus()
            self._settle_rendered_layout()
            # Keep the reader's place: map the source caret to the rendered text.
            rendered = self._rendered.document().toPlainText()
            r_pos = md_comments.map_position(src, rendered, src_caret)
            cur = self._rendered.textCursor()
            cur.setPosition(min(r_pos, len(rendered)))
            self._rendered.setTextCursor(cur)
            self._rendered.ensureCursorVisible()
        else:
            # Keep the reader's place: map the rendered caret back to the source.
            rendered = self._rendered.document().toPlainText()
            r_caret = self._rendered.textCursor().position()
            src = self._editor.toPlainText()
            s_pos = md_comments.map_position(rendered, src, r_caret)
            self._hide_comment_field()
            self._rendered.setVisible(False)
            self._editor.setVisible(True)
            self._editor.setFocus()
            cur = self._editor.textCursor()
            cur.setPosition(min(s_pos, len(src)))
            self._editor.setTextCursor(cur)
            self._editor.ensureCursorVisible()
        self.update()
        # Flash last, after the view swap + repaint, so it sits clearly on top.
        self._flash_mode("READ" if self._rendered_mode else "WRITE")

    def _settle_rendered_layout(self):
        """Force the rendered document's layout to finish before we navigate it.

        ``QTextDocument`` lays out lazily and only corrects the view's scroll
        range when the deferred relayout runs in the event loop. If the reader
        jumps (``G``) before that settles, the scroll range is still estimated
        and scrolling back up stops short — until ``gg`` forces a top-down
        relayout. Draining the layout work here (excluding user input so it
        can't re-enter this handler) makes the range correct immediately."""
        QApplication.processEvents(
            QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents
        )

    def _flash_mode(self, text: str):
        """Briefly flash a big, blocky word ('READ' / 'WRITE') in the centre to
        anchor a mode change, then fade it out — so the current state needn't be
        shown permanently (it's also legible from the styling)."""
        if self._mode_flash is None:
            lbl = QLabel(self)
            # Non-interactive: never takes focus or swallows mouse/keyboard, so
            # you can read/type while it fades.
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            font = QFont(FONT_FAMILY, 96, QFont.Weight.Bold)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 10)
            lbl.setFont(font)
            lbl.setStyleSheet(
                f"color: rgba({ZEN_TEXT_COLOR.red()}, {ZEN_TEXT_COLOR.green()},"
                f" {ZEN_TEXT_COLOR.blue()}, 200); background: transparent;"
            )
            self._mode_flash = lbl
            self._mode_flash_effect = QGraphicsOpacityEffect(lbl)
            lbl.setGraphicsEffect(self._mode_flash_effect)
        lbl = self._mode_flash
        lbl.setText(text)
        lbl.setGeometry(self.rect())
        self._mode_flash_effect.setOpacity(1.0)
        lbl.show()
        lbl.raise_()
        # Appear instantly, hold at full briefly, then ease out — so it reads as
        # a calm flash rather than a blink. Linear timing keeps the hold exact;
        # the extra key points give the fade a soft tail.
        anim = QPropertyAnimation(self._mode_flash_effect, b"opacity", self)
        anim.setDuration(2000)
        anim.setKeyValueAt(0.0, 1.0)
        anim.setKeyValueAt(0.22, 1.0)    # hold at full briefly
        anim.setKeyValueAt(0.60, 0.5)    # then a long, soft fade
        anim.setKeyValueAt(1.0, 0.0)
        anim.finished.connect(lbl.hide)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._mode_flash_anim = anim   # hold a ref so it isn't GC'd mid-run

    def _render_markdown(self, source: str):
        """Render ``source`` into the read view: comment spans are highlighted
        (bodies hidden, revealed on demand), and suggestion marks are styled as
        track-changes — removed text struck in the body mono, added text written
        in the handwriting note font. The raw CriticMarkup never shows."""
        md, spans = md_comments.to_rendered(source)
        doc = self._rendered.document()
        doc.setMarkdown(md)
        self._apply_mark_formats(doc, spans)

    def _format_for_span(self, span, comment_idx: int,
                         suggest_idx: int) -> QTextCharFormat:
        """The char format for one rendered span by its role. Comments wear the
        highlight (tagged with their comment index); a removed span is simply
        struck out (calm — no colour); an added span is body text in zen blue,
        which stands out on its own and works equally for inline edits and block
        rewrites. Suggestion spans are tagged with their suggestion index."""
        fmt = QTextCharFormat()
        if span.role == "comment":
            fmt.setBackground(QBrush(ZEN_MD_COMMENT_HL))
            fmt.setProperty(_COMMENT_IDX_PROP, comment_idx)
            return fmt
        fmt.setProperty(_SUGGEST_IDX_PROP, suggest_idx)
        if span.role == "removed":
            fmt.setProperty(_SUGGEST_ROLE_PROP, _ROLE_REMOVED)
            fmt.setFontStrikeOut(True)
        elif span.role == "added":
            fmt.setProperty(_SUGGEST_ROLE_PROP, _ROLE_ADDED)
            fmt.setForeground(QBrush(ZEN_MD_SUGGEST_ADD))
        return fmt

    def _apply_mark_formats(self, doc, spans):
        """Find each sentinel-wrapped span in the rendered document, paint its
        role's format over it, tag comment spans with their comment index, and
        delete the sentinel markers. Builds ``self._rendered_comments`` (the
        rendered-range → source-``Comment`` map the reveal/navigate loop uses).

        Located via ``QTextDocument.find`` (not raw string indexing) so the
        positions stay correct even when the render inserts position-bearing
        objects (images, rules) ahead of a span.
        """
        self._rendered_comments = []
        self._rendered_suggestions = []
        if not spans:
            return
        # Collect each span's sentinel bounds, in document order.
        bounds = []
        pos = 0
        for _ in spans:
            start = doc.find(md_comments.SENTINEL_START, pos)
            if start.isNull():
                break
            end = doc.find(md_comments.SENTINEL_END, start.selectionEnd())
            if end.isNull():
                break
            bounds.append((start.selectionStart(), start.selectionEnd(),
                           end.selectionStart(), end.selectionEnd()))
            pos = end.selectionEnd()
        # Comment spans index into a comment-only list (kept as Comment objects
        # so the reveal/edit code stays typed against Comment). Suggestion spans
        # index into a suggestion-only list of source Marks; a substitution's two
        # spans share one index so they recover as a single reviewable unit.
        comments = []
        comment_idx = []
        sugg_marks = []
        sugg_ord = {}            # mark.full_start -> suggestion index
        suggest_idx = []
        for span in spans:
            if span.role == "comment":
                comment_idx.append(len(comments))
                comments.append(md_comments.as_comment(span.mark))
                suggest_idx.append(-1)
            else:
                fs = span.mark.full_start
                if fs not in sugg_ord:
                    sugg_ord[fs] = len(sugg_marks)
                    sugg_marks.append(span.mark)
                comment_idx.append(-1)
                suggest_idx.append(sugg_ord[fs])
        # Apply last-to-first so deletions don't shift not-yet-processed offsets.
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        for i in range(len(bounds) - 1, -1, -1):
            s0, s1, e0, e1 = bounds[i]
            fmt = self._format_for_span(spans[i], comment_idx[i], suggest_idx[i])
            edit.setPosition(s1)
            edit.setPosition(e0, QTextCursor.MoveMode.KeepAnchor)
            edit.mergeCharFormat(fmt)               # style the span text
            edit.setPosition(e0)
            edit.setPosition(e1, QTextCursor.MoveMode.KeepAnchor)
            edit.removeSelectedText()               # drop END sentinel
            edit.setPosition(s0)
            edit.setPosition(s1, QTextCursor.MoveMode.KeepAnchor)
            edit.removeSelectedText()               # drop START sentinel
        edit.endEditBlock()
        self._rendered_comments = self._collect_rendered_comments(doc, comments)
        self._rendered_suggestions = self._collect_rendered_suggestions(
            doc, sugg_marks)

    def _collect_rendered_suggestions(self, doc, marks):
        """Recover each suggestion as an :class:`RSuggestion` — its overall range
        plus the separate removed/added sub-ranges — from the tagged fragments. A
        substitution's struck-old and handwritten-new fragments share the same
        index (folded into one unit) but carry distinct roles (kept apart so the
        animator can fade one and settle the other)."""
        overall: dict[int, tuple[int, int]] = {}
        by_role: dict[tuple[int, int], tuple[int, int]] = {}
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                cf = frag.charFormat()
                if cf.hasProperty(_SUGGEST_IDX_PROP):
                    idx = cf.intProperty(_SUGGEST_IDX_PROP)
                    role = cf.intProperty(_SUGGEST_ROLE_PROP)
                    a = frag.position()
                    b = a + frag.length()
                    lo, hi = overall.get(idx, (a, b))
                    overall[idx] = (min(lo, a), max(hi, b))
                    rlo, rhi = by_role.get((idx, role), (a, b))
                    by_role[(idx, role)] = (min(rlo, a), max(rhi, b))
                it += 1
            block = block.next()
        return [
            RSuggestion(overall[i][0], overall[i][1], marks[i],
                        by_role.get((i, _ROLE_REMOVED)),
                        by_role.get((i, _ROLE_ADDED)))
            for i in sorted(overall)
        ]

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
        """Card width hugs the text column (the adjustable content width +
        padding); height takes most of the window. Centered. In full-width mode
        (⌘↵) the card grows to nearly fill the window.
        """
        max_w = max(self.width() - 80, 320)
        if getattr(self, "_full_width", False):
            w = max_w
            h = max(self.height() - 40, 320)
        else:
            content_w = getattr(self, "_content_width", ZEN_MD_MAX_WIDTH)
            desired_w = content_w + 2 * ZEN_MD_CARD_INNER_PAD_H
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
        # Bail if we're mid-construction or mid-teardown — pumping the event
        # loop (e.g. the read-view layout settle) can deliver events while
        # these child refs aren't established or have been cleared.
        if getattr(self, "_editor", None) is None:
            return False
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
        """Keys while the inline comment editor is open: Enter saves and returns
        to undisturbed reading; ⇧Enter inserts a line break; Esc cancels."""
        key = event.key()
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if shift:
                self._comment_field.insertPlainText("\n")   # ⇧↵ — line break
            else:
                self._commit_comment_field()                # ↵ — save & back
            return True
        if key == Qt.Key.Key_Escape:
            self._cancel_comment_field()                    # Esc — discard
            return True
        return False

    def _cancel_comment_field(self):
        """Discard the open comment editor without writing changes (abandons a
        new comment; leaves an edited one untouched)."""
        self._authoring_span = None
        self._authoring_suggestion = False
        self._hide_comment_field()

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

        # Ctrl+Shift+→/←/↓ — widen / narrow / reset the content column.
        # Arrow keys (not +/-) so the binding is layout-independent and doesn't
        # collide with the Ctrl +/-/0 font zoom below. Works in either view.
        if ((event.modifiers() & _CTRL_MOD)
                and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            if event.key() == Qt.Key.Key_Right:
                self._change_width(+1)
                return True
            if event.key() == Qt.Key.Key_Left:
                self._change_width(-1)
                return True
            if event.key() == Qt.Key.Key_Down:
                self._change_width(0)
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
        same motions extend a selection; `c` comments the selection, `s` suggests
        an alternative for it (empty = delete; no selection = insert at the caret).
        `]c`/`[c` step between comments, `]s`/`[s` between suggestions; on a
        suggestion `a`/`x` accept/reject it (⇧ = all). Enter reveals/edits a
        comment, ⇧D deletes it. Esc leaves visual mode, or — when not selecting —
        saves & closes (⇧Esc cancels)."""
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
            if key == Qt.Key.Key_S:
                self._goto_suggestion(1 if pending == "]" else -1)
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
        # s — suggest an alternative for the selection (type it; empty = delete);
        # with no selection, propose an insertion at the caret.
        if key == Qt.Key.Key_S and not ctrl and not shift:
            self._suggest_selection()
            return True

        # a / x — accept / reject the suggestion under the caret (⇧ = all).
        if key == Qt.Key.Key_A and not ctrl:
            self._review_suggestion(accept=True, every=shift)
            return True
        if key == Qt.Key.Key_X and not ctrl:
            self._review_suggestion(accept=False, every=shift)
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
            if not cur.selectedText().strip():
                self._set_visual(False)     # nothing but whitespace — ignore
                return
            r0, r1 = cur.selectionStart(), cur.selectionEnd()
            self._set_visual(False)
            self._begin_comment_for_span(r0, r1)
            return
        self._reveal_active_comment()   # no selection → reveal comment under caret

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
        """Show the inline editable field for the comment **under the caret**
        (Enter). If the caret isn't on a comment, do nothing — never open an
        unrelated comment that merely happens to be on the same screen."""
        idx = self._comment_at_position(self._rendered.textCursor().position())
        if idx < 0:
            return
        self._active_comment = idx
        _start, end, comment = self._rendered_comments[idx]
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
        raw = self._comment_field.toPlainText()
        body = raw.strip()
        if self._authoring_span is not None:
            if self._authoring_suggestion:
                self._commit_new_suggestion(raw)   # keep spaces — they're content
            else:
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
        self._apply_source_change(
            src,
            lambda: (min(idx, len(self._rendered_comments) - 1)
                     if self._rendered_comments else None),
        )

    # ── Authoring: comment the visual selection ──

    def _begin_comment_for_span(self, r0: int, r1: int):
        """Map the rendered span back to source; if it maps, open an empty field
        to type the comment. An unmappable selection (e.g. no words) is a quiet
        no-op — it never yanks you out of the reading view."""
        rendered = self._rendered.document().toPlainText()
        src = self._editor.toPlainText()
        mapped = md_comments.map_rendered_span(rendered, src, r0, r1)
        if mapped is None:
            return
        s0, s1 = mapped
        # Keep the {== / ==} markers out of code: if a boundary maps inside an
        # inline `code` span (e.g. a word that was in backticks), snap it to the
        # code edge so the comment stays parseable.
        s0, s1 = md_comments.snap_out_of_code(src, s0, s1)
        # The span still can't include CriticMarkup delimiters (e.g. it crossed a
        # code example like `{== ==}`) — wrapping would nest markers and render as
        # literal text. Refuse quietly.
        if md_comments.contains_markup(src[s0:s1]):
            return
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
        """Wrap the authored span in CriticMarkup and re-render, staying in the
        reading view with the new comment active. An empty body abandons it."""
        s0, _s1, _sel = self._authoring_span
        self._authoring_span = None
        self._hide_comment_field()
        if not body:
            return                               # abandoned — no comment created
        new_src = md_comments.wrap(self._editor.toPlainText(), s0, _s1, body)
        self._apply_source_change(
            new_src, lambda: self._rendered_index_for_source_start(s0)
        )

    def _rendered_index_for_source_start(self, full_start: int):
        """Index of the rendered comment whose source construct begins at
        ``full_start`` — i.e. the one just wrapped at that offset."""
        for i, (_s, _e, comment) in enumerate(self._rendered_comments):
            if comment.full_start == full_start:
                return i
        return None

    # ── Authoring: suggest an alternative for the selection ──

    def _suggest_selection(self):
        """s — propose a change. With a visual selection, open the inline field to
        type its replacement (an empty field commits a deletion); with no
        selection, propose an insertion at the caret."""
        cur = self._rendered.textCursor()
        if cur.hasSelection():
            if not cur.selectedText().strip():
                self._set_visual(False)     # whitespace-only — ignore
                return
            r0, r1 = cur.selectionStart(), cur.selectionEnd()
            self._set_visual(False)
            self._begin_suggestion_for_span(r0, r1)
            return
        pos = cur.position()
        self._begin_suggestion_for_span(pos, pos)   # insertion at the caret

    def _begin_suggestion_for_span(self, r0: int, r1: int):
        """Map the rendered span back to source and open an empty field for the
        replacement text. A zero-width span authors an insertion; a real span a
        substitution (or a deletion if the field is left empty). Unmappable spans,
        spans crossing existing markup, or spans overlapping another mark are quiet
        no-ops — they never yank you out of the reading view."""
        rendered = self._rendered.document().toPlainText()
        src = self._editor.toPlainText()
        if r0 == r1:
            s0 = s1 = md_comments.map_position(rendered, src, r0)
        else:
            mapped = md_comments.map_rendered_span(rendered, src, r0, r1)
            if mapped is None:
                return
            s0, s1 = md_comments.snap_out_of_code(src, *mapped)
            if md_comments.contains_markup(src[s0:s1]):
                return
        if md_comments.overlaps_mark(src, s0, s1):
            return
        self._authoring_span = (s0, s1, rendered[r0:r1])
        self._authoring_suggestion = True
        cur = self._rendered.textCursor()
        cur.setPosition(r0)
        cur.setPosition(r1, QTextCursor.MoveMode.KeepAnchor)
        self._rendered.setTextCursor(cur)        # show what will be changed
        self._show_comment_field(r1, "")

    def _commit_new_suggestion(self, body: str):
        """Wrap the authored span as a CriticMarkup suggestion and re-render,
        staying in the reading view with the new suggestion under the caret. The
        gesture branches on the span and the (unstripped) body: a caret authors an
        insertion (empty body abandons it, surrounding spaces are kept); a real
        selection substitutes — or, when the body is blank, deletes it."""
        s0, s1, _sel = self._authoring_span
        self._authoring_span = None
        self._authoring_suggestion = False
        self._hide_comment_field()
        if s0 == s1:
            if not body.strip():
                return                           # insert-nothing — abandoned
            replacement = body                   # keep leading/trailing spaces
        else:
            replacement = "" if not body.strip() else body   # blank → deletion
        new_src = md_comments.wrap_suggestion(
            self._editor.toPlainText(), s0, s1, replacement)
        self._apply_source_change_pos(
            new_src, lambda: self._rendered_suggestion_pos_for_source(s0)
        )

    def _rendered_suggestion_pos_for_source(self, full_start: int):
        """Rendered start position of the suggestion whose source mark begins at
        ``full_start`` — i.e. the one just wrapped there."""
        for s in self._rendered_suggestions:
            if s.mark.full_start == full_start:
                return s.start
        return None

    def _delete_active_comment(self):
        """⇧D — unwrap the active comment (highlight + body gone), re-render."""
        if not (0 <= self._active_comment < len(self._rendered_comments)):
            return
        _s, _e, comment = self._rendered_comments[self._active_comment]
        idx = self._active_comment
        src = md_comments.remove(self._editor.toPlainText(), comment)
        self._hide_comment_field()
        self._apply_source_change(
            src,
            lambda: (min(idx, len(self._rendered_comments) - 1)
                     if self._rendered_comments else None),
        )

    def _set_source_text(self, src: str):
        """Replace the source buffer (fires heading layout + autosave). Done
        through a cursor edit (not ``setPlainText``) so it lands on the editor's
        undo stack as a single step — accept/reject and comment edits are then
        revertible with ⌘Z in the write view."""
        cur = self._editor.textCursor()
        cur.beginEditBlock()
        cur.select(QTextCursor.SelectionType.Document)
        cur.insertText(src)
        cur.endEditBlock()

    def _apply_source_change(self, src: str, resolve_idx=None):
        """Update the source + re-render the read view **keeping the reader's
        scroll position**, then activate the comment ``resolve_idx()`` returns
        (resolved after the re-render). Adding/editing/deleting a comment barely
        changes the rendered text, so the view stays put instead of snapping to
        the top — ``ensureCursorVisible`` isn't reliable right after
        ``setMarkdown`` (layout isn't ready), so we restore the scrollbar."""
        sb = self._rendered.verticalScrollBar()
        pos = sb.value()
        self._set_source_text(src)
        self._render_markdown(src)
        sb.setValue(pos)   # restore scroll first, so visibility is computed right
        idx = resolve_idx() if resolve_idx is not None else None
        caret = self._rendered.textCursor()
        if idx is not None and 0 <= idx < len(self._rendered_comments):
            # Park the caret on the comment just touched (it's already in view, so
            # no scroll jump) — j/k then continue from there, not the page top.
            self._active_comment = idx
            caret.setPosition(self._rendered_comments[idx][0])
        else:
            # No comment to anchor to (e.g. the last one was deleted) — fall back
            # to the top of the visible area rather than the document end.
            self._active_comment = -1
            caret = self._rendered.cursorForPosition(QPoint(0, 0))
        self._rendered.setTextCursor(caret)
        sb.setValue(pos)   # setTextCursor may nudge scroll; reassert the position

    def _apply_source_change_pos(self, src: str, pos_resolver=None):
        """Like :meth:`_apply_source_change` but parks the caret at an absolute
        rendered position (``pos_resolver()``), used by suggestion review where
        the anchor is the next suggestion, not a comment."""
        sb = self._rendered.verticalScrollBar()
        pos = sb.value()
        self._set_source_text(src)
        self._render_markdown(src)
        sb.setValue(pos)
        target = pos_resolver() if pos_resolver is not None else None
        caret = self._rendered.textCursor()
        if target is not None:
            n = len(self._rendered.document().toPlainText())
            caret.setPosition(max(0, min(target, n)))
        else:
            caret = self._rendered.cursorForPosition(QPoint(0, 0))
        self._rendered.setTextCursor(caret)
        sb.setValue(pos)

    # ── Read-view suggestion review (track-changes) ──

    def _suggestion_at_position(self, pos: int) -> int:
        """Index of the rendered suggestion whose range contains ``pos``, else -1."""
        for i, s in enumerate(self._rendered_suggestions):
            if s.start <= pos <= s.end:
                return i
        return -1

    def _goto_suggestion(self, direction: int):
        """]s / [s — step to the next / previous suggestion and select it. From a
        caret that isn't on one, land on the nearest in the given direction."""
        sugg = self._rendered_suggestions
        if not sugg:
            return
        n = len(sugg)
        pos = self._rendered.textCursor().position()
        here = self._suggestion_at_position(pos)
        if here >= 0:
            idx = (here + direction) % n
        elif direction > 0:
            idx = next((i for i, s in enumerate(sugg) if s.start > pos), 0)
        else:
            idx = next((i for i in range(n - 1, -1, -1) if sugg[i].start < pos), n - 1)
        s = sugg[idx]
        cur = self._rendered.textCursor()
        cur.setPosition(s.start)
        cur.setPosition(s.end, QTextCursor.MoveMode.KeepAnchor)
        self._rendered.setTextCursor(cur)
        self._rendered.ensureCursorVisible()

    def _review_suggestion(self, accept: bool, every: bool = False):
        """a / x (and ⇧A / ⇧X). Accept or reject the suggestion under the caret —
        the accepted/rejected text is applied to the source, the view re-renders,
        and the caret advances onto the next suggestion so review is a rhythm.
        A single accept/reject plays the zen accept/reject animation first (fade
        the text that leaves, settle the text that stays); ⇧ variants resolve
        every suggestion at once, instantly."""
        # Settle any in-flight animation so we compute against a stable document.
        self._suggest_animator.finish()
        src = self._editor.toPlainText()
        if every:
            new_src = (md_comments.accept_all(src) if accept
                       else md_comments.reject_all(src))
            self._apply_source_change_pos(new_src, lambda: 0)
            return
        idx = self._suggestion_at_position(self._rendered.textCursor().position())
        if idx < 0:
            return
        s = self._rendered_suggestions[idx]
        new_src = (md_comments.accept(src, s.mark) if accept
                   else md_comments.reject(src, s.mark))

        # After re-render the resolved mark is gone, so the suggestion that was
        # next has slid into ``idx`` — park there to auto-advance.
        def apply():
            self._apply_source_change_pos(
                new_src,
                lambda: (self._rendered_suggestions[min(idx, len(
                    self._rendered_suggestions) - 1)].start
                    if self._rendered_suggestions else None),
            )

        if self._suggest_animate:
            self._suggest_animator.run(
                accept=accept, removed=s.removed, added=s.added, on_finish=apply)
        else:
            apply()

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

    def _change_width(self, delta: int):
        """Step the editor's content-column width. delta=0 resets to default;
        +1/-1 widen/narrow by one step. Stepping exits full-width mode so the
        change is visible, and the preference persists across sessions."""
        if delta == 0:
            new_w = ZEN_MD_MAX_WIDTH
        else:
            new_w = max(
                ZEN_MD_MAX_WIDTH_MIN,
                min(ZEN_MD_MAX_WIDTH_MAX,
                    self._content_width + delta * ZEN_MD_WIDTH_STEP),
            )
        if new_w == self._content_width and not self._full_width:
            return
        self._content_width = new_w
        self._full_width = False
        layout = self.layout()
        if layout:
            self._apply_card_margins(layout)
        self._apply_heading_layout()
        self.update()
        QSettings("Grafli", "Grafli").setValue(
            "zen_md/content_width", self._content_width
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
