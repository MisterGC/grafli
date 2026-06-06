"""Dedicated Flows editor — lives on the 'Flows' tab of the side panel.

Flows and the bookmarks list are collapsible (collapsed by default) to keep
scrolling down. Each entry shows a wide thumbnail of what it frames; clicking
an entry selects it (clear highlight) and flies the canvas there. Selecting a
step also makes a freshly captured bookmark (gb/gB) insert right after it.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from grafli.constants import (
    BOX_BORDER,
    FONT_FAMILY,
    SCENE_BG,
    SIDE_PANEL_BTN_ACTIVE,
    SIDE_PANEL_SECTION_COLOR,
)
from grafli.flows import render_bookmark_pixmap, text_slide_note
from grafli.format import FlowStep

# Thumbnail render resolution — rendered larger than the display max so the
# _ThumbLabel down-scales it crisply.
_THUMB_W, _THUMB_H = 720, 405
# A slide preview always fills the available column width, clamped to these
# bounds: it shrinks with a narrow panel (down to MIN — a thin stripe) and grows
# with a wide one (up to MAX, so it doesn't balloon). MIN is deliberately small
# so the whole Flows tab can collapse to a narrow vertical stripe.
_THUMB_DISPLAY_MIN = 56
_THUMB_DISPLAY_MAX = 360
_BORDER = "#D5D0C8"
_SELECT_BG = SIDE_PANEL_BTN_ACTIVE.name()
_ACCENT = "#D4804E"


class _ClickableFrame(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _InlineTitle(QLineEdit):
    """A label that becomes editable on click — commits on Enter / focus-out."""

    committed = Signal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFrame(False)
        self.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.Bold))
        # A QLineEdit otherwise reserves width for several characters and pins the
        # panel wide. Ignored width contributes nothing to the minimum: it just
        # fills whatever the row gives it, so the header tracks the column and the
        # panel can collapse to a narrow stripe.
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f"QLineEdit {{ color: {BOX_BORDER.name()}; background: transparent;"
            f" border: none; padding: 0; }}"
            f" QLineEdit:focus {{ background: #FFFFFF;"
            f" border: 1px solid {_BORDER}; border-radius: 3px; }}")
        self.setPlaceholderText("Untitled")
        self._initial = text
        self.editingFinished.connect(self._maybe_commit)

    def _maybe_commit(self):
        if self.text() != self._initial:
            self._initial = self.text()
            self.committed.emit(self.text())


class _InlineDesc(QPlainTextEdit):
    """Inline, wrapping description editor — commits on focus-out."""

    committed = Signal(str)

    _MAX_H = 130

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont(FONT_FAMILY, 10))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumWidth(0)  # don't pin the panel width; wraps to whatever
        # Ignored width: never contribute to the panel minimum, just fill the col.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setPlaceholderText("Add description…")
        self.setStyleSheet(
            f"QPlainTextEdit {{ color: #4A4A4A; background: transparent;"
            f" border: none; }}"
            f" QPlainTextEdit:focus {{ background: #FFFFFF;"
            f" border: 1px solid {_BORDER}; border-radius: 3px; }}")
        self._initial = text
        self.textChanged.connect(self._fit_height)

    def _fit_height(self):
        # Grow with content (clamped) so a 1-line description doesn't reserve
        # three lines of empty space. Note: a plain-text document reports its
        # height as a LINE COUNT, so convert to pixels via line spacing.
        lines = max(1, self.document().size().height())
        h = int(lines * self.fontMetrics().lineSpacing()) + 12
        self.setFixedHeight(max(22, min(h, self._MAX_H)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_height()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.toPlainText() != self._initial:
            self._initial = self.toPlainText()
            self.committed.emit(self.toPlainText())


def _icon_button(glyph: str, tooltip: str, on_click) -> QPushButton:
    btn = QPushButton(glyph)
    btn.setToolTip(tooltip)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(24, 24)
    btn.setFlat(True)
    btn.clicked.connect(on_click)
    return btn


class _ThumbLabel(QLabel):
    """A slide preview that scales with the column between sensible bounds.

    It tracks panel resizes, growing/shrinking the thumbnail with the column
    width but clamped to ``[_THUMB_DISPLAY_MIN, _THUMB_DISPLAY_MAX]`` — so it
    neither balloons to fill a wide panel nor stays uselessly tiny. The MIN is
    reported as the widget minimum so the panel can shrink down to it (a default
    QLabel would instead pin the panel to the pixmap's full native width). The
    source pixmap is rendered larger than MAX so down-scaling stays crisp."""

    def __init__(self, source):
        super().__init__()
        self._source = source
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent;")
        self.setMinimumWidth(_THUMB_DISPLAY_MIN)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if source is not None and not source.isNull():
            self._rescale(self.width())

    def _rescale(self, w: int) -> None:
        if self._source is None or self._source.isNull() or w <= 0:
            return
        w = max(_THUMB_DISPLAY_MIN,
                min(int(w), self._source.width(), _THUMB_DISPLAY_MAX))
        pix = self._source.scaledToWidth(
            max(1, w), Qt.TransformationMode.SmoothTransformation)
        super().setPixmap(pix)
        self.setFixedHeight(pix.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(_THUMB_DISPLAY_MIN, round(_THUMB_DISPLAY_MIN * 9 / 16))

    def resizeEvent(self, event):
        self._rescale(event.size().width())
        super().resizeEvent(event)


class FlowsPanel(QWidget):
    """The Flows-tab editor. Call attach(view) once the view exists."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Force readable dark text on native controls (the macOS dark palette
        # otherwise renders combo/line-edit/button text near-white on paper).
        self.setStyleSheet(
            f"QLabel {{ color: {BOX_BORDER.name()}; background: transparent; }}"
            f" QPushButton {{ color: {BOX_BORDER.name()}; background: transparent;"
            f" border: none; }}"
            f" QLineEdit {{ color: {BOX_BORDER.name()}; background: #FFFFFF;"
            f" border: 1px solid {_BORDER}; border-radius: 3px; }}"
            f" QComboBox {{ color: {BOX_BORDER.name()}; background: #FFFFFF;"
            f" border: 1px solid {_BORDER}; border-radius: 3px; padding: 1px 4px; }}"
        )
        self._view = None
        # Selection: None | ("step", flow_id, index) | ("bm", bm_id)
        self._selected = None
        self._expanded_flows: set[str] = set()
        self._bookmarks_expanded = False
        self._thumb_cache: dict[tuple, object] = {}
        self._cache_board = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._content = QWidget()
        self._content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(6)
        scroll.setWidget(self._content)
        root.addWidget(scroll)

    # ── wiring ──────────────────────────────────────────────────
    def attach(self, view):
        self._view = view
        view.flows_changed.connect(self.refresh)
        self.refresh()

    def _board(self):
        return self._view.board if self._view else None

    # ── thumbnails (cached) ─────────────────────────────────────
    def _thumb_pixmap(self, bm):
        board = self._board()
        if self._cache_board is not board:
            self._thumb_cache.clear()
            self._cache_board = board
        # A single-note step exports as a text slide whose text grows to fill the
        # page, so preview it the same way (text filling a 16:9 frame) instead of
        # framing the note at its small on-canvas scale, which letterboxed badly.
        note = text_slide_note(self._view, bm)
        key = (bm.id, bm.label, tuple(bm.focus), bm.pad, bm.view,
               note.text if note else None, note.textsize if note else None)
        pix = self._thumb_cache.get(key)
        if pix is None:
            # Render larger than any card width so _ThumbLabel can down-scale it
            # to fill the card crisply (no horizontal letterboxing).
            if note is not None:
                from grafli.pdfexport import render_text_slide_pixmap
                pix = render_text_slide_pixmap(note, _THUMB_W,
                                               round(_THUMB_W * 9 / 16))
            else:
                pix = render_bookmark_pixmap(self._view, bm, _THUMB_W, _THUMB_H)
            self._thumb_cache[key] = pix
        return pix

    # ── rebuild ─────────────────────────────────────────────────
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def refresh(self):
        self._clear()
        board = self._board()
        if board is None:
            return

        self._layout.addWidget(
            self._text_button("＋  New flow", self._new_flow, fill=True))
        self._layout.addWidget(self._text_button(
            "＋  Auto-flow from selection", self._new_auto_flow, fill=True))

        valid_flow_ids = {f.id for f in board.flows}
        self._expanded_flows &= valid_flow_ids
        for flow in board.flows:
            expanded = flow.id in self._expanded_flows
            self._layout.addWidget(self._flow_header(flow, expanded))
            if expanded:
                self._layout.addWidget(self._flow_tools(flow))
                self._layout.addWidget(self._captioned(
                    "Description (markdown — shown on the title slide)",
                    self._flow_desc_edit(flow)))
                if not flow.steps:
                    self._layout.addWidget(self._hint(
                        "No stops. Add a bookmark below, or select a step and "
                        "press gb while navigating."))
                for i, step in enumerate(flow.steps):
                    self._layout.addWidget(self._step_row(flow, i, step))
                self._layout.addWidget(self._add_row(flow))
                self._layout.addWidget(self._captioned(
                    "Title background (all flows)", self._title_bg_edit()))
                self._layout.addWidget(self._captioned(
                    "Footer (markdown — branding on every exported slide)",
                    self._footer_edit()))

        self._layout.addWidget(self._collapsible_header(
            "Bookmarks", len(board.bookmarks), self._bookmarks_expanded,
            self._toggle_bookmarks))
        if self._bookmarks_expanded:
            if not board.bookmarks:
                self._layout.addWidget(self._hint("No bookmarks yet (gb / gB)."))
            for bm in board.bookmarks:
                self._layout.addWidget(self._bookmark_row(bm))

        self._layout.addStretch(1)

    # ── pieces ──────────────────────────────────────────────────
    def _text_button(self, text: str, on_click, fill: bool = False) -> QWidget:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont(FONT_FAMILY, 11))
        # Don't let the label's text width pin the panel's minimum width. ``fill``
        # buttons span their row, so an Ignored width lets them shrink with the
        # column (text clips gracefully); non-fill buttons keep their preferred
        # size but with a zero minimum so they never force the panel wider.
        btn.setMinimumWidth(0)
        if fill:
            btn.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(
            f"QPushButton {{ color: {BOX_BORDER.name()}; background: transparent;"
            f" border: 1px solid {_BORDER}; border-radius: 4px; padding: 5px;"
            f" margin: 2px 10px; text-align: center; }}"
            f" QPushButton:hover {{ background: {_SELECT_BG}; }}")
        btn.clicked.connect(on_click)
        return btn

    def _hint(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setFont(QFont(FONT_FAMILY, 10))
        lbl.setStyleSheet("color: #8A8A8A; background: transparent;"
                          " padding: 4px 14px;")
        return lbl

    def _collapsible_header(self, title, count, expanded, on_toggle,
                            actions=(), prominent=False, on_rename=None) -> QWidget:
        row = _ClickableFrame()
        row.clicked.connect(on_toggle)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(row)
        arrow = "▾" if expanded else "▸"
        if prominent:
            # Flow headers stand out as a filled band so it's obvious where
            # each flow begins and ends.
            row.setStyleSheet(
                f"_ClickableFrame {{ background: {_SELECT_BG};"
                f" border-left: 3px solid {_ACCENT}; }}")
            h.setContentsMargins(8, 7, 8, 7)
            arrow_lbl = QLabel(arrow)
            arrow_lbl.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
            arrow_lbl.setStyleSheet(
                f"color: {BOX_BORDER.name()}; background: transparent;")
            h.addWidget(arrow_lbl)
            if on_rename is not None:
                # Click-to-edit title: the line edit consumes the click (so it
                # focuses for editing), while clicks elsewhere on the band still
                # toggle the flow open/closed.
                title_w = _InlineTitle(title)
                title_w.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
                title_w.setPlaceholderText("Flow name")
                title_w.committed.connect(on_rename)
                h.addWidget(title_w, stretch=1)
            else:
                lbl = QLabel(title)
                lbl.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
                lbl.setStyleSheet(
                    f"color: {BOX_BORDER.name()}; background: transparent;")
                h.addWidget(lbl, stretch=1)
            cnt = QLabel(f"{count}")
            cnt.setFont(QFont(FONT_FAMILY, 10))
            cnt.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                              f" background: transparent;")
            h.addWidget(cnt)
        else:
            h.setContentsMargins(8, 8, 6, 4)
            lbl = QLabel(f"{arrow}  {title.upper()}  ({count})")
            # Wrap rather than pin the panel wide: a non-wrapping section title
            # ("BOOKMARKS (9)") otherwise sets a ~146px floor for the whole tab.
            lbl.setWordWrap(True)
            lbl.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                              f" background: transparent;")
            h.addWidget(lbl, stretch=1)
        h.setSpacing(4)
        for glyph, tip, fn in actions:
            h.addWidget(_icon_button(glyph, tip, fn))
        return row

    def _flow_header(self, flow, expanded) -> QWidget:
        # Keep the header row lean — play + delete only — so it never overflows
        # the (non-horizontally-scrolling) panel. Export and re-generate live in
        # a dedicated row below the header when the flow is open (see _flow_tools).
        actions = [
            ("▶", "Play flow", lambda: self._view.play_flow(flow.id)),
            ("🗑", "Delete flow", lambda: self._view.delete_flow(flow)),
        ]
        return self._collapsible_header(
            flow.label, len(flow.steps), expanded,
            lambda: self._toggle_flow(flow.id),
            actions=tuple(actions),
            prominent=True,
            on_rename=lambda t, f=flow: self._set_flow_label(f, t))

    def _flow_tools(self, flow) -> QWidget:
        """A compact tools row for the open flow: export buttons (PDF / PPTX) and,
        for auto-flows, re-generate. Its own row so the controls are always
        visible regardless of panel width (the header row stays lean)."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 0, 8, 2)
        h.setSpacing(6)
        if flow.auto_start:
            h.addWidget(self._text_button(
                "↻", lambda: self._view.regenerate_auto_flow(flow)))
        h.addWidget(self._text_button(
            "󰈦 PDF", lambda: self._view.export_flow(flow), fill=True))
        h.addWidget(self._text_button(
            "󰈦 PPTX", lambda: self._view.export_flow(flow, "pptx"), fill=True))
        return row

    def _slide_card(self, selected: bool, on_select) -> _ClickableFrame:
        """A framed slide-style card (matches the PDF look): paper background,
        accent border when selected. Click empty area / diagram to select."""
        card = _ClickableFrame()
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        card.clicked.connect(on_select)
        border = f"2px solid {_ACCENT}" if selected else f"1px solid {_BORDER}"
        card.setStyleSheet(
            f"_ClickableFrame {{ background: {SCENE_BG.name()};"
            f" border: {border}; border-radius: 6px; }}")
        return card

    def _thumb_label(self, bm) -> QLabel:
        pix = self._thumb_pixmap(bm)
        if pix is not None and not pix.isNull():
            return _ThumbLabel(pix)
        lbl = QLabel("(no anchor)")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: #8A8A8A; background: transparent;")
        return lbl

    def _title_edit(self, bm) -> _InlineTitle:
        title = _InlineTitle(bm.label)
        title.committed.connect(lambda t, b=bm: self._set_label(b, t))
        return title

    def _desc_edit(self, bm) -> _InlineDesc:
        desc = _InlineDesc(bm.description)
        desc.committed.connect(lambda t, b=bm: self._set_description(b, t))
        return desc

    def _captioned(self, caption: str, widget: QWidget) -> QWidget:
        """A small muted caption stacked above an editor field."""
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        col = QVBoxLayout(box)
        col.setContentsMargins(14, 4, 8, 2)
        col.setSpacing(1)
        lbl = QLabel(caption)
        lbl.setWordWrap(True)
        lbl.setFont(QFont(FONT_FAMILY, 9))
        lbl.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                          f" background: transparent;")
        col.addWidget(lbl)
        col.addWidget(widget)
        return box

    def _flow_desc_edit(self, flow) -> _InlineDesc:
        desc = _InlineDesc(flow.description)
        desc.committed.connect(lambda t, f=flow: self._set_flow_description(f, t))
        return desc

    def _footer_edit(self) -> _InlineDesc:
        board = self._board()
        edit = _InlineDesc(board.footer if board else "")
        edit.committed.connect(self._set_footer)
        return edit

    _TITLE_BG_OPTIONS = (("Empty", ""), ("Thumbnail art", "thumbnail-art"))

    def _title_bg_edit(self) -> QComboBox:
        board = self._board()
        current = board.title_bg if board else ""
        combo = QComboBox()
        combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for label, value in self._TITLE_BG_OPTIONS:
            combo.addItem(label, value)
        idx = combo.findData(current)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, c=combo: self._set_title_bg(c.currentData()))
        return combo

    def _step_row(self, flow, index, step) -> QWidget:
        board = self._board()
        bm = board.bookmark_by_id(step.ref)
        selected = self._selected == ("step", flow.id, index)
        card = self._slide_card(selected, lambda: self._select_step(flow, index))
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        num = QLabel(str(index + 1))
        num.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
        num.setStyleSheet(f"color: {_ACCENT}; background: transparent;")
        num.setFixedWidth(16)
        num.setAlignment(Qt.AlignmentFlag.AlignTop)
        head.addWidget(num)
        if bm is not None:
            head.addWidget(self._title_edit(bm), stretch=1)
            if self._view is not None and text_slide_note(self._view, bm) is not None:
                tag = QLabel("text")
                tag.setFont(QFont(FONT_FAMILY, 9))
                tag.setToolTip(
                    "Text slide — the note renders as clickable text in the PDF")
                tag.setStyleSheet(f"color: {_ACCENT}; background: transparent;")
                tag.setAlignment(Qt.AlignmentFlag.AlignTop)
                head.addWidget(tag)
        else:
            warn = QLabel(f"⚠ {step.ref}")
            warn.setStyleSheet("color: #C53030; background: transparent;")
            head.addWidget(warn, stretch=1)
        col.addLayout(head)

        if bm is not None:
            col.addWidget(self._thumb_label(bm))
            col.addWidget(self._desc_edit(bm))

        if selected:
            # Reorder/remove on their own row (not inline with the title) so the
            # fixed-width buttons never overflow a narrow panel and clip.
            tools = QHBoxLayout()
            tools.setSpacing(4)
            tools.addWidget(_icon_button("↑", "Move up",
                                         lambda: self._move_step(flow, index, -1)))
            tools.addWidget(_icon_button("↓", "Move down",
                                         lambda: self._move_step(flow, index, 1)))
            tools.addWidget(_icon_button("✕", "Remove from flow",
                                         lambda: self._remove_step(flow, index)))
            tools.addStretch(1)
            col.addLayout(tools)

            # Compact dwell field — label folded into the placeholder/tooltip so
            # the row stays narrow.
            dwell = QLineEdit("" if step.dwell is None else _fmt(step.dwell))
            dwell.setPlaceholderText("dwell s")
            dwell.setToolTip("Seconds to rest on this stop during auto-play")
            dwell.setFixedWidth(64)
            dwell.editingFinished.connect(
                lambda: self._set_dwell(step, dwell.text()))
            foot = QHBoxLayout()
            foot.setSpacing(4)
            foot.addWidget(dwell)
            foot.addStretch(1)
            col.addLayout(foot)
        return card

    def _bookmark_row(self, bm) -> QWidget:
        selected = self._selected == ("bm", bm.id)
        card = self._slide_card(selected, lambda: self._select_bookmark(bm))
        col = QVBoxLayout(card)
        col.setContentsMargins(8, 6, 8, 8)
        col.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(self._title_edit(bm), stretch=1)
        if selected:
            head.addWidget(_icon_button("✕", "Delete bookmark",
                                        lambda: self._view.delete_bookmark(bm)))
        col.addLayout(head)
        col.addWidget(self._thumb_label(bm))
        col.addWidget(self._desc_edit(bm))
        return card

    def _add_row(self, flow) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 2, 8, 6)
        h.setSpacing(4)
        combo = QComboBox()
        combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        for bm in self._board().bookmarks:
            combo.addItem(bm.label or bm.id, bm.id)
        h.addWidget(combo, stretch=1)
        btn = _icon_button("＋", "Add bookmark to flow (after selection)",
                           lambda: self._add_to_flow(flow, combo.currentData()))
        btn.setEnabled(combo.count() > 0)
        h.addWidget(btn)
        return row

    # ── actions ─────────────────────────────────────────────────
    def _toggle_flow(self, flow_id):
        if flow_id in self._expanded_flows:
            self._expanded_flows.discard(flow_id)
            if self._view._active_flow and self._view._active_flow.id == flow_id:
                self._view.set_flow_edit_target(None, -1)
        else:
            self._expanded_flows.add(flow_id)
            # Make the expanded flow the capture target: gb appends to it
            # (and selecting a step inserts right after that step).
            self._selected = None
            self._view.set_flow_edit_target(self._board().flow_by_id(flow_id), -1)
        self.refresh()
        self._view.setFocus()

    def _toggle_bookmarks(self):
        self._bookmarks_expanded = not self._bookmarks_expanded
        self.refresh()

    def _select_step(self, flow, index):
        self._selected = ("step", flow.id, index)
        self._view.set_flow_edit_target(flow, index)
        self.refresh()
        self._view.goto_bookmark(flow.steps[index].ref)
        self._view.setFocus()

    def _select_bookmark(self, bm):
        self._selected = ("bm", bm.id)
        self.refresh()
        self._view.goto_bookmark(bm.id)
        self._view.setFocus()

    def _new_flow(self):
        label, ok = QInputDialog.getText(self, "New flow", "Flow name:")
        if not ok or not label.strip():
            return
        flow = self._view.create_flow(label.strip())
        if flow is not None:
            self._expanded_flows.add(flow.id)
        self.refresh()
        self._view.setFocus()

    def _new_auto_flow(self):
        # Walks forward arrows from the single selected node; named after it
        # (rename inline afterwards). No-op with a hint if selection isn't one.
        flow = self._view.new_auto_flow_from_selection()
        if flow is not None:
            self._expanded_flows.add(flow.id)
        self.refresh()
        self._view.setFocus()

    def _move_step(self, flow, index, delta):
        j = index + delta
        if 0 <= j < len(flow.steps):
            flow.steps[index], flow.steps[j] = flow.steps[j], flow.steps[index]
            self._selected = ("step", flow.id, j)
            self._view.set_flow_edit_target(flow, j)
            self._view._commit_flow_edit()

    def _remove_step(self, flow, index):
        if 0 <= index < len(flow.steps):
            del flow.steps[index]
            new_idx = min(index, len(flow.steps) - 1)
            self._selected = (("step", flow.id, new_idx) if flow.steps else None)
            self._view.set_flow_edit_target(flow, new_idx if flow.steps else -1)
            self._view._commit_flow_edit()

    def _set_dwell(self, step, text):
        text = text.strip()
        new = None
        if text:
            try:
                new = float(text.rstrip("s"))
            except ValueError:
                new = step.dwell
        if new != step.dwell:
            step.dwell = new
            self._view._commit_flow_edit()

    def _add_to_flow(self, flow, bookmark_id):
        if not bookmark_id:
            return
        steps = flow.steps
        idx = self._view._active_step_index
        if self._view._active_flow is flow and 0 <= idx < len(steps):
            steps.insert(idx + 1, FlowStep(ref=bookmark_id))
            pos = idx + 1
        else:
            steps.append(FlowStep(ref=bookmark_id))
            pos = len(steps) - 1
        self._selected = ("step", flow.id, pos)
        self._view.set_flow_edit_target(flow, pos)
        self._view._commit_flow_edit()

    def _set_label(self, bm, text):
        # Empty is allowed: a label-less bookmark is a graph-only slide.
        text = text.strip()
        if text != bm.label:
            bm.label = text
            self._view._commit_flow_edit()

    def _set_description(self, bm, text):
        if text.strip() != bm.description:
            bm.description = text.strip()
            self._view._commit_flow_edit()

    def _set_flow_label(self, flow, text):
        text = text.strip()
        if text != flow.label:
            flow.label = text
            self._view._commit_flow_edit()

    def _set_flow_description(self, flow, text):
        if text.strip() != flow.description:
            flow.description = text.strip()
            self._view._commit_flow_edit()

    def _set_footer(self, text):
        board = self._board()
        if board is not None and text.strip() != board.footer:
            board.footer = text.strip()
            self._view._commit_flow_edit()

    def _set_title_bg(self, value):
        board = self._board()
        if board is not None and value != board.title_bg:
            board.title_bg = value
            self._view._commit_flow_edit()


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)
