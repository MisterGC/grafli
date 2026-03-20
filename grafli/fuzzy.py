"""Fuzzy finder overlay for file and buffer picking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from grafli.constants import (
    FONT_FAMILY,
    _CTRL_MOD,
    ZEN_DIM_COLOR,
    ZEN_HINT_COLOR,
    ZEN_PANEL_BG,
    ZEN_PANEL_BORDER,
    ZEN_PANEL_WIDTH,
    ZEN_TEXT_COLOR,
    ZEN_TITLE_COLOR,
)


@dataclass
class FuzzyItem:
    """One entry in the fuzzy finder list."""

    display: str
    detail: str
    data: Any


class FuzzyOverlay(QWidget):
    """Full-viewport overlay with a centered fuzzy-filter panel."""

    selected = Signal(object)
    cancelled = Signal()

    def __init__(self, title: str, items: list[FuzzyItem], parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(parent.size())

        self._items = items
        self._filtered = list(items)

        layout = QVBoxLayout(self)
        h_margin = max((self.width() - ZEN_PANEL_WIDTH) // 2, 40)
        v_margin = max(self.height() // 5, 60)
        layout.setContentsMargins(h_margin, v_margin, h_margin, v_margin)
        layout.setSpacing(6)

        # Title
        self._title = QLabel(title)
        self._title.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        self._title.setStyleSheet(
            f"color: {ZEN_TITLE_COLOR.name()}; background: transparent;"
        )
        layout.addWidget(self._title)

        # Search input
        self._input = QLineEdit()
        self._input.setFont(QFont(FONT_FAMILY, 12))
        self._input.setPlaceholderText("Type to filter\u2026")
        self._input.setStyleSheet(
            f"QLineEdit {{ background: {ZEN_PANEL_BG.name()};"
            f" color: {ZEN_TEXT_COLOR.name()};"
            f" border: 1px solid {ZEN_PANEL_BORDER.name()};"
            f" border-radius: 6px; padding: 8px; }}"
        )
        self._input.textChanged.connect(self._on_filter)
        layout.addWidget(self._input)

        # Results list
        self._list = QListWidget()
        self._list.setFont(QFont(FONT_FAMILY, 11))
        self._list.setStyleSheet(
            f"QListWidget {{ background: {ZEN_PANEL_BG.name()};"
            f" color: {ZEN_TEXT_COLOR.name()};"
            f" border: 1px solid {ZEN_PANEL_BORDER.name()};"
            f" border-radius: 6px; padding: 4px;"
            f" outline: none; }}"
            f" QListWidget::item {{ padding: 4px 8px; border-radius: 4px; }}"
            f" QListWidget::item:selected {{"
            f" background: #B8D4E8; color: {ZEN_TEXT_COLOR.name()}; }}"
        )
        self._list.itemActivated.connect(self._on_activate)
        layout.addWidget(self._list, stretch=1)

        # Hint
        hint = QLabel("↑↓/Ctrl+jk navigate · Enter select · Esc cancel")
        hint.setFont(QFont(FONT_FAMILY, 10))
        hint.setStyleSheet(
            f"color: {ZEN_HINT_COLOR.name()}; background: transparent;"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self._populate()
        self._input.installEventFilter(self)
        self._input.setFocus()
        self.show()

    def _populate(self):
        self._list.clear()
        for item in self._filtered:
            label = item.display
            if item.detail:
                label = f"{item.display}  {item.detail}"
            wi = QListWidgetItem(label)
            wi.setData(Qt.ItemDataRole.UserRole, item)
            self._list.addItem(wi)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _on_filter(self, text: str):
        query = text.lower()
        if not query:
            self._filtered = list(self._items)
        else:
            self._filtered = [
                it for it in self._items
                if self._fuzzy_match(query, it.display.lower())
            ]
        self._populate()

    @staticmethod
    def _fuzzy_match(query: str, target: str) -> bool:
        """Simple subsequence fuzzy match."""
        qi = 0
        for ch in target:
            if qi < len(query) and ch == query[qi]:
                qi += 1
        return qi == len(query)

    def _on_activate(self, item: QListWidgetItem):
        fuzzy_item = item.data(Qt.ItemDataRole.UserRole)
        if fuzzy_item:
            self.selected.emit(fuzzy_item)
            self.close()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), ZEN_DIM_COLOR)
        layout = self.layout()
        m = layout.contentsMargins()
        panel = self.rect().adjusted(
            m.left() - 16, m.top() - 16, -m.right() + 16, -m.bottom() + 16
        )
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(ZEN_PANEL_BORDER, 1))
        p.setBrush(QBrush(ZEN_PANEL_BG))
        p.drawRoundedRect(panel, 10, 10)
        p.end()

    def _move_selection(self, delta: int):
        row = self._list.currentRow() + delta
        if 0 <= row < self._list.count():
            self._list.setCurrentRow(row)

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == event.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._move_selection(1 if key == Qt.Key.Key_Down else -1)
                return True
            if event.modifiers() & _CTRL_MOD and key in (
                Qt.Key.Key_J, Qt.Key.Key_K,
            ):
                self._move_selection(1 if key == Qt.Key.Key_J else -1)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            current = self._list.currentItem()
            if current:
                self._on_activate(current)
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            self._move_selection(1 if key == Qt.Key.Key_Down else -1)
            return
        super().keyPressEvent(event)
