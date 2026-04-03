"""Zen overlay — a modular dim-and-panel editor widget."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from grafli.constants import (
    FONT_FAMILY,
    ZEN_DIM_COLOR,
    ZEN_HINT_COLOR,
    ZEN_PANEL_BG,
    ZEN_PANEL_BORDER,
    ZEN_PANEL_WIDTH,
    ZEN_TEXT_COLOR,
    ZEN_TITLE_COLOR,
)


class ZenOverlay(QWidget):
    """Full-viewport overlay with a centered panel for editing text."""

    finished = Signal(str)
    cancelled = Signal()

    def __init__(self, title: str, text: str, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(parent.size())

        # ── Panel layout (centered via margins) ──
        layout = QVBoxLayout(self)
        h_margin = max((self.width() - ZEN_PANEL_WIDTH) // 2, 40)
        v_margin = max(self.height() // 5, 60)
        layout.setContentsMargins(h_margin, v_margin, h_margin, v_margin)
        layout.setSpacing(8)

        # Title
        self._title = QLabel(title)
        self._title.setFont(QFont(FONT_FAMILY, 13, QFont.Weight.Bold))
        self._title.setStyleSheet(f"color: {ZEN_TITLE_COLOR.name()}; background: transparent;")
        layout.addWidget(self._title)

        # Text editor
        self._text = QPlainTextEdit(text)
        self._text.setFont(QFont(FONT_FAMILY, 12))
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._text.setStyleSheet(
            f"QPlainTextEdit {{ background: {ZEN_PANEL_BG.name()}; color: {ZEN_TEXT_COLOR.name()};"
            f" border: 1px solid {ZEN_PANEL_BORDER.name()}; border-radius: 6px; padding: 10px;"
            f" selection-background-color: #B8D4E8; }}"
        )
        layout.addWidget(self._text, stretch=1)

        # Hint
        hint = QLabel("Esc to save \u00b7 Shift+Esc to cancel")
        hint.setFont(QFont(FONT_FAMILY, 10))
        hint.setStyleSheet(f"color: {ZEN_HINT_COLOR.name()}; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        # Focus the text area and move cursor to start
        self._text.setFocus()
        cursor = self._text.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        self._text.setTextCursor(cursor)

        self.show()

    def paintEvent(self, event):
        p = QPainter(self)
        # Dim background
        p.fillRect(self.rect(), ZEN_DIM_COLOR)
        # Panel background
        layout = self.layout()
        m = layout.contentsMargins()
        panel = self.rect().adjusted(m.left() - 16, m.top() - 16, -m.right() + 16, -m.bottom() + 16)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(ZEN_PANEL_BORDER, 1))
        p.setBrush(QBrush(ZEN_PANEL_BG))
        p.drawRoundedRect(panel, 10, 10)
        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.cancelled.emit()
            else:
                self.finished.emit(self._text.toPlainText())
            self.close()
            return
        super().keyPressEvent(event)
