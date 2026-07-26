"""Glyph index and picker widget for inserting Unicode glyphs."""

from __future__ import annotations

import unicodedata

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from grafli import theme
from grafli.constants import (
    FONT_FAMILY,
)

# ── Categories ──────────────────────────────────────────────────

_CATEGORIES: list[tuple[str, list[tuple[int, int]]]] = [
    ("Arrows", [
        (0x2190, 0x21FF),
        (0x2900, 0x297F),
        (0x2B00, 0x2BFF),
    ]),
    ("Math", [
        (0x2200, 0x22FF),
        (0x27C0, 0x27EF),
    ]),
    ("Technical", [
        (0x2300, 0x23FF),
    ]),
    ("Box Drawing", [
        (0x2500, 0x257F),
        (0x2580, 0x259F),
    ]),
    ("Geometric", [
        (0x25A0, 0x25FF),
    ]),
    ("Symbols", [
        (0x2600, 0x26FF),
    ]),
    ("Dingbats", [
        (0x2700, 0x27BF),
    ]),
]

_ALL_RANGES = [r for _, ranges in _CATEGORIES for r in ranges]


def _build_entries(ranges: list[tuple[int, int]]) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for start, end in ranges:
        for cp in range(start, end + 1):
            ch = chr(cp)
            try:
                name = unicodedata.name(ch)
            except ValueError:
                continue
            entries.append((ch, name))
    return entries


def _in_glyph_range(cp: int) -> bool:
    return any(start <= cp <= end for start, end in _ALL_RANGES)


def ensure_text_presentation(text: str) -> str:
    """Append U+FE0E after glyph-range characters to force monochrome rendering."""
    parts: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        cp = ord(ch)
        if _in_glyph_range(cp):
            parts.append(ch)
            # skip if already followed by a variation selector
            if i + 1 < len(text) and text[i + 1] in ("\uFE0E", "\uFE0F"):
                i += 1
                parts.append(text[i])
            else:
                parts.append("\uFE0E")
        else:
            parts.append(ch)
        i += 1
    return "".join(parts)


class GlyphIndex:
    """Lazy-built searchable index of curated Unicode glyphs."""

    _instance: GlyphIndex | None = None
    _all_entries: list[tuple[str, str]] | None = None
    _category_entries: dict[str, list[tuple[str, str]]] | None = None

    @classmethod
    def get(cls) -> GlyphIndex:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _build(self) -> None:
        if self._all_entries is not None:
            return
        self._category_entries = {}
        self._all_entries = []
        for cat_name, ranges in _CATEGORIES:
            entries = _build_entries(ranges)
            self._category_entries[cat_name] = entries
            self._all_entries.extend(entries)

    def categories(self) -> list[str]:
        return [name for name, _ in _CATEGORIES]

    def get_category(self, category: str | None, limit: int = 200) -> list[tuple[str, str]]:
        self._build()
        assert self._all_entries is not None and self._category_entries is not None
        if category is None:
            return self._all_entries[:limit]
        return self._category_entries.get(category, [])[:limit]

    def search(
        self, query: str, category: str | None = None, limit: int = 60,
    ) -> list[tuple[str, str]]:
        if not query or not query.strip():
            return self.get_category(category, limit)
        self._build()
        assert self._all_entries is not None and self._category_entries is not None
        source = self._all_entries if category is None else self._category_entries.get(category, [])
        words = query.upper().split()
        results: list[tuple[str, str]] = []
        for ch, name in source:
            if all(w in name for w in words):
                results.append((ch, name))
                if len(results) >= limit:
                    break
        return results


# ── Picker widget ───────────────────────────────────────────────

_COLS = 3
_PILL_STYLE = (
    "QPushButton {{ background: {bg}; color: {fg}; border: 1px solid {border};"
    " border-radius: 9px; padding: 2px 8px; font-size: 10px; font-family: {font}; }}"
)


class _GlyphCell(QWidget):
    """Single grid cell showing a glyph character and its name."""

    clicked = Signal()

    def __init__(self, char: str, name: str, badge: int = 0, parent=None):
        super().__init__(parent)
        self.char = char
        self._highlighted = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(64)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        top_row = QWidget()
        top_layout = QVBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self._char_label = QLabel(char)
        self._char_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._char_label.setFont(QFont(FONT_FAMILY, 22))
        self._char_label.setStyleSheet(
            f"color: {theme.ON_ACCENT.name()}; background: transparent;")
        top_layout.addWidget(self._char_label)

        layout.addWidget(top_row, stretch=1)

        short = name.lower()
        if len(short) > 22:
            short = short[:20] + "\u2026"
        self._name_label = QLabel(short)
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name_label.setFont(QFont(FONT_FAMILY, 7))
        self._name_label.setStyleSheet(
            f"color: {theme.GLYPH_PICKER_NAME_FG.name()}; background: transparent;")
        layout.addWidget(self._name_label)

        self._badge = badge
        self._update_style()

    def set_highlighted(self, on: bool) -> None:
        self._highlighted = on
        self._update_style()

    def _update_style(self) -> None:
        bg = theme.GLYPH_PICKER_HIGHLIGHT.name() if self._highlighted else "transparent"
        border = f"1px solid {theme.GLYPH_PICKER_HIGHLIGHT.name()}" if self._highlighted else "1px solid transparent"
        self.setStyleSheet(
            f"_GlyphCell {{ background: {bg}; border: {border}; border-radius: 6px; }}"
        )

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._badge:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(theme.GLYPH_PICKER_BADGE)
            painter.setPen(Qt.PenStyle.NoPen)
            badge_font = QFont(FONT_FAMILY, 8)
            fm = QFontMetrics(badge_font)
            txt = str(self._badge)
            tw = fm.horizontalAdvance(txt)
            bw = max(tw + 6, 16)
            bh = 16
            bx = self.width() - bw - 3
            by = 3
            painter.drawRoundedRect(bx, by, bw, bh, 4, 4)
            painter.setPen(Qt.GlobalColor.white)
            painter.setFont(badge_font)
            painter.drawText(bx, by, bw, bh, Qt.AlignmentFlag.AlignCenter, txt)
            painter.end()


class GlyphPicker(QWidget):
    """Popup widget for searching and selecting Unicode glyphs."""

    glyph_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(420)
        self.setMinimumHeight(120)
        self.setMaximumHeight(460)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        bg = theme.GLYPH_PICKER_BG
        self.setStyleSheet(
            f"GlyphPicker {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});"
            f" border: 1px solid {theme.GLYPH_PICKER_BORDER.name()};"
            f" border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Search input
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter glyphs\u2026")
        self._search.setFont(QFont(FONT_FAMILY, 12))
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {theme.GLYPH_PICKER_FIELD_BG.name()};"
            f" color: {theme.ON_ACCENT.name()};"
            f" border: 1px solid {theme.GLYPH_PICKER_BORDER.name()};"
            " border-radius: 4px; padding: 6px 8px; }"
            f"QLineEdit:focus {{ border-color: {theme.GLYPH_PICKER_BADGE.name()}; }}"
        )
        self._search.textChanged.connect(self._on_filter)
        layout.addWidget(self._search)

        # Category pills
        self._cat_row = QWidget()
        self._cat_row.setStyleSheet("background: transparent;")
        cat_layout = QHBoxLayout(self._cat_row)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.setSpacing(4)

        self._index = GlyphIndex.get()
        self._active_category: str | None = None
        self._cat_buttons: list[QPushButton] = []
        self._cat_names: list[str | None] = []

        fm = QFontMetrics(QFont(FONT_FAMILY, 13))
        all_entries = self._index.get_category(None, limit=2000)
        self._font_glyphs = {ch for ch, _ in all_entries if fm.inFontUcs4(ord(ch))}

        for cat_name in [None] + self._index.categories():
            if cat_name is not None:
                cat_entries = self._index.get_category(cat_name)
                if not any(ch in self._font_glyphs for ch, _ in cat_entries):
                    continue
            label = "All" if cat_name is None else cat_name
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda checked=False, c=cat_name: self._select_category(c))
            cat_layout.addWidget(btn)
            self._cat_buttons.append(btn)
            self._cat_names.append(cat_name)

        cat_layout.addStretch()
        layout.addWidget(self._cat_row)
        self._update_pill_styles()

        # Scrollable grid
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QWidget#grid_container { background: transparent; }"
            f"QScrollBar:vertical {{ background: {theme.GLYPH_PICKER_FIELD_BG.name()};"
            " width: 8px; }"
            f"QScrollBar::handle:vertical {{ background: {theme.GLYPH_PICKER_BORDER.name()};"
            " border-radius: 4px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        layout.addWidget(self._scroll)

        self._grid_widget = QWidget()
        self._grid_widget.setObjectName("grid_container")
        self._grid_layout = QGridLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(4)
        self._scroll.setWidget(self._grid_widget)

        self._cells: list[_GlyphCell] = []
        self._highlight_idx = -1

        self._search.installEventFilter(self)

        # Show initial glyphs
        self._refresh()
        self._search.setFocus()

    def _update_pill_styles(self) -> None:
        for btn, cat in zip(self._cat_buttons, self._cat_names):
            active = cat == self._active_category
            btn.setStyleSheet(_PILL_STYLE.format(
                bg=theme.GLYPH_PICKER_HIGHLIGHT.name() if active else "transparent",
                fg=(theme.ON_ACCENT.name() if active
                    else theme.GLYPH_PICKER_INACTIVE_FG.name()),
                border=(theme.GLYPH_PICKER_HIGHLIGHT.name() if active
                        else theme.GLYPH_PICKER_BORDER.name()),
                font=FONT_FAMILY,
            ))

    def _select_category(self, category: str | None) -> None:
        self._active_category = category
        self._update_pill_styles()
        self._refresh()

    def _on_filter(self, text: str) -> None:
        self._refresh()

    def _refresh(self) -> None:
        query = self._search.text().strip()
        results = self._index.search(query, category=self._active_category, limit=300)
        results = [(ch, name) for ch, name in results if ch in self._font_glyphs][:120]
        self._populate(results)

    def _populate(self, results: list[tuple[str, str]]) -> None:
        for cell in self._cells:
            cell.setParent(None)
            cell.deleteLater()
        self._cells.clear()
        self._highlight_idx = -1

        for i, (ch, name) in enumerate(results):
            badge = i + 1 if i < 9 else 0
            cell = _GlyphCell(ch, name, badge=badge, parent=self._grid_widget)
            cell.clicked.connect(lambda c=ch: self._emit_and_close(c))
            row = i // _COLS
            col = i % _COLS
            self._grid_layout.addWidget(cell, row, col)
            self._cells.append(cell)

        if self._cells:
            self._set_highlight(0)

    def _set_highlight(self, idx: int) -> None:
        if 0 <= self._highlight_idx < len(self._cells):
            self._cells[self._highlight_idx].set_highlighted(False)
        self._highlight_idx = idx
        if 0 <= idx < len(self._cells):
            self._cells[idx].set_highlighted(True)
            self._scroll.ensureWidgetVisible(self._cells[idx])

    def _emit_and_close(self, char: str) -> None:
        self.glyph_selected.emit(char)
        self.close()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
                idx = key - Qt.Key.Key_1
                if idx < len(self._cells):
                    self._emit_and_close(self._cells[idx].char)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if 0 <= self._highlight_idx < len(self._cells):
                    self._emit_and_close(self._cells[self._highlight_idx].char)
                return True
            if key == Qt.Key.Key_Escape:
                self.close()
                return True
            if key == Qt.Key.Key_Down:
                new = self._highlight_idx + _COLS
                if new < len(self._cells):
                    self._set_highlight(new)
                return True
            if key == Qt.Key.Key_Up:
                new = self._highlight_idx - _COLS
                if new >= 0:
                    self._set_highlight(new)
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()

        # Digit 1-9 quick-select
        if Qt.Key.Key_1 <= key <= Qt.Key.Key_9:
            idx = key - Qt.Key.Key_1
            if idx < len(self._cells):
                self._emit_and_close(self._cells[idx].char)
                return

        if key == Qt.Key.Key_Escape:
            self.close()
            return

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if 0 <= self._highlight_idx < len(self._cells):
                self._emit_and_close(self._cells[self._highlight_idx].char)
            return

        if key == Qt.Key.Key_Down:
            new = self._highlight_idx + _COLS
            if new < len(self._cells):
                self._set_highlight(new)
            return

        if key == Qt.Key.Key_Up:
            new = self._highlight_idx - _COLS
            if new >= 0:
                self._set_highlight(new)
            return

        if key == Qt.Key.Key_Right:
            new = self._highlight_idx + 1
            if new < len(self._cells):
                self._set_highlight(new)
            return

        if key == Qt.Key.Key_Left:
            new = self._highlight_idx - 1
            if new >= 0:
                self._set_highlight(new)
            return

        # Forward to search input
        super().keyPressEvent(event)
