"""Dedicated Flows editor — lives on the 'Flows' tab of the side panel.

Flows and the bookmarks list are collapsible (collapsed by default) to keep
scrolling down. Each entry shows a wide thumbnail of what it frames; clicking
an entry selects it (clear highlight) and flies the canvas there. Selecting a
step also makes a freshly captured bookmark (gb/gB) insert right after it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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

_THUMB_W, _THUMB_H = 250, 120
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
        key = (bm.id, bm.label, tuple(bm.focus), bm.pad, bm.view)
        pix = self._thumb_cache.get(key)
        if pix is None:
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

        self._layout.addWidget(self._text_button("＋  New flow", self._new_flow))

        valid_flow_ids = {f.id for f in board.flows}
        self._expanded_flows &= valid_flow_ids
        for flow in board.flows:
            expanded = flow.id in self._expanded_flows
            self._layout.addWidget(self._flow_header(flow, expanded))
            if expanded:
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
    def _text_button(self, text: str, on_click) -> QWidget:
        btn = QPushButton(text)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(QFont(FONT_FAMILY, 11))
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
                            actions=(), prominent=False) -> QWidget:
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
            lbl = QLabel(f"{arrow}  {title}")
            lbl.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {BOX_BORDER.name()}; background: transparent;")
            h.addWidget(lbl, stretch=1)
            cnt = QLabel(f"{count}")
            cnt.setFont(QFont(FONT_FAMILY, 10))
            cnt.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                              f" background: transparent;")
            h.addWidget(cnt)
        else:
            h.setContentsMargins(10, 8, 8, 4)
            lbl = QLabel(f"{arrow}  {title.upper()}  ({count})")
            lbl.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Bold))
            lbl.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                              f" background: transparent;")
            h.addWidget(lbl, stretch=1)
        h.setSpacing(4)
        for glyph, tip, fn in actions:
            h.addWidget(_icon_button(glyph, tip, fn))
        return row

    def _flow_header(self, flow, expanded) -> QWidget:
        actions = [
            ("▶", "Play flow", lambda: self._view.play_flow(flow.id)),
            ("🗑", "Delete flow", lambda: self._view.delete_flow(flow)),
        ]
        if expanded:
            # Export appears only for the open (selected) flow.
            actions.insert(0, ("󰈦", "Export flow to PDF",
                               lambda: self._view.export_flow(flow)))
        return self._collapsible_header(
            flow.label or flow.id, len(flow.steps), expanded,
            lambda: self._toggle_flow(flow.id),
            actions=tuple(actions),
            prominent=True)

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
        lbl = QLabel()
        lbl.setStyleSheet("background: transparent;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = self._thumb_pixmap(bm)
        if pix is not None:
            lbl.setPixmap(pix)
            lbl.setFixedHeight(pix.height())
        else:
            lbl.setText("(no anchor)")
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
        if selected:
            head.addWidget(_icon_button("↑", "Move up",
                                        lambda: self._move_step(flow, index, -1)))
            head.addWidget(_icon_button("↓", "Move down",
                                        lambda: self._move_step(flow, index, 1)))
            head.addWidget(_icon_button("✕", "Remove from flow",
                                        lambda: self._remove_step(flow, index)))
        col.addLayout(head)

        if bm is not None:
            col.addWidget(self._thumb_label(bm))
            col.addWidget(self._desc_edit(bm))

        if selected:
            foot = QHBoxLayout()
            foot.setSpacing(4)
            dl = QLabel("Dwell")
            dl.setFont(QFont(FONT_FAMILY, 10))
            dl.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                             f" background: transparent;")
            foot.addWidget(dl)
            dwell = QLineEdit("" if step.dwell is None else _fmt(step.dwell))
            dwell.setPlaceholderText("default")
            dwell.setToolTip("Seconds to rest on this stop during auto-play")
            dwell.setFixedWidth(56)
            dwell.editingFinished.connect(lambda: self._set_dwell(step, dwell.text()))
            foot.addWidget(dwell)
            su = QLabel("s")
            su.setStyleSheet(f"color: {SIDE_PANEL_SECTION_COLOR.name()};"
                             f" background: transparent;")
            foot.addWidget(su)
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

    def _set_flow_description(self, flow, text):
        if text.strip() != flow.description:
            flow.description = text.strip()
            self._view._commit_flow_edit()

    def _set_footer(self, text):
        board = self._board()
        if board is not None and text.strip() != board.footer:
            board.footer = text.strip()
            self._view._commit_flow_edit()


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)
