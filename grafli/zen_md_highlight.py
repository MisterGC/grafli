"""Markdown syntax highlighter with paragraph focus for the zen editor."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from grafli.constants import (
    FONT_FAMILY,
    ZEN_HINT_COLOR,
    ZEN_MD_CODE_BG,
    ZEN_MD_FONT_SIZE,
    ZEN_MD_HEADING_SIZES,
    ZEN_MD_LINK_COLOR,
    ZEN_MD_MUTED_ALPHA,
    ZEN_MD_SYNTAX_COLOR,
    ZEN_TEXT_COLOR,
    ZEN_TITLE_COLOR,
)

# ── Regex patterns ──

_RE_HEADING = re.compile(r"^(#{1,3})\s+(.*)")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_RE_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_RE_CODE = re.compile(r"`([^`]+)`")
_RE_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_RE_LIST = re.compile(r"^(\s*[-*])\s")


def _fmt(**kwargs) -> QTextCharFormat:
    """Build a QTextCharFormat from keyword args."""
    f = QTextCharFormat()
    if "color" in kwargs:
        f.setForeground(kwargs["color"])
    if "bold" in kwargs and kwargs["bold"]:
        f.setFontWeight(QFont.Weight.Bold)
    if "italic" in kwargs and kwargs["italic"]:
        f.setFontItalic(True)
    if "underline" in kwargs and kwargs["underline"]:
        f.setFontUnderline(True)
    if "size" in kwargs:
        f.setFontPointSize(kwargs["size"])
    if "bg" in kwargs:
        f.setBackground(kwargs["bg"])
    if "family" in kwargs:
        f.setFontFamily(kwargs["family"])
    return f


class MarkdownHighlighter(QSyntaxHighlighter):
    """Applies markdown visual formatting and paragraph focus."""

    def __init__(self, parent):
        super().__init__(parent)
        self._focus_range: tuple[int, int] = (-1, -1)
        self._focus_enabled = True
        self._base_size = ZEN_MD_FONT_SIZE

    def set_base_size(self, size: int):
        """Set the base font size; heading sizes scale proportionally."""
        if size == self._base_size:
            return
        self._base_size = size
        self.rehighlight()

    def set_focus_range(self, start: int, end: int):
        """Update which block range is focused, rehighlight changed blocks."""
        old_start, old_end = self._focus_range
        if (start, end) == (old_start, old_end):
            return
        self._focus_range = (start, end)
        # Rehighlight blocks that entered or left the focus range
        doc = self.document()
        if not doc:
            return
        all_changed = set()
        if old_start >= 0:
            all_changed.update(range(old_start, old_end + 1))
        if start >= 0:
            all_changed.update(range(start, end + 1))
        # Only rehighlight blocks that actually changed focus state
        for bn in all_changed:
            block = doc.findBlockByNumber(bn)
            if block.isValid():
                was_in = old_start <= bn <= old_end if old_start >= 0 else False
                now_in = start <= bn <= end if start >= 0 else False
                if was_in != now_in:
                    self.rehighlightBlock(block)

    def set_focus_enabled(self, enabled: bool):
        if self._focus_enabled == enabled:
            return
        self._focus_enabled = enabled
        self.rehighlight()

    def highlightBlock(self, text: str):
        block_num = self.currentBlock().blockNumber()
        focused = not self._focus_enabled or self._is_focused(block_num)

        # Heading
        m = _RE_HEADING.match(text)
        if m:
            level = len(m.group(1))
            base_size = ZEN_MD_HEADING_SIZES.get(level, ZEN_MD_FONT_SIZE)
            # Scale proportionally to the current base font size
            size = int(round(base_size * self._base_size / ZEN_MD_FONT_SIZE))
            # Hash chars — muted
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused), size=size),
            )
            # Heading text — same color as body, bold + larger size only.
            self.setFormat(
                m.start(2), len(m.group(2)),
                _fmt(color=self._alpha(ZEN_TEXT_COLOR, focused), size=size, bold=True),
            )
            return

        # Apply base text format for the whole line first
        base = _fmt(color=self._alpha(ZEN_TEXT_COLOR, focused))
        self.setFormat(0, len(text), base)

        # Bold
        for m in _RE_BOLD.finditer(text):
            # Asterisks muted
            self.setFormat(m.start(), 2, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(m.end() - 2, 2, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            # Content bold
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(color=self._alpha(ZEN_TEXT_COLOR, focused), bold=True),
            )

        # Italic
        for m in _RE_ITALIC.finditer(text):
            self.setFormat(m.start(), 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(m.end() - 1, 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(color=self._alpha(ZEN_TEXT_COLOR, focused), italic=True),
            )

        # Inline code
        for m in _RE_CODE.finditer(text):
            self.setFormat(m.start(), 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(m.end() - 1, 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(
                    color=self._alpha(ZEN_TEXT_COLOR, focused),
                    bg=ZEN_MD_CODE_BG,
                    family=FONT_FAMILY,
                ),
            )

        # Links
        for m in _RE_LINK.finditer(text):
            # Brackets and parens muted
            self.setFormat(m.start(), 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(m.start() + 1 + len(m.group(1)), 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            url_start = m.start() + len(m.group(1)) + 2
            self.setFormat(url_start, 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            self.setFormat(m.end() - 1, 1, _fmt(color=self._alpha(ZEN_MD_SYNTAX_COLOR, focused)))
            # Link text
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(color=self._alpha(ZEN_MD_LINK_COLOR, focused), underline=True),
            )
            # URL
            self.setFormat(
                m.start(2), len(m.group(2)),
                _fmt(color=self._alpha(ZEN_HINT_COLOR, focused)),
            )

        # List markers
        m = _RE_LIST.match(text)
        if m:
            self.setFormat(
                m.start(1), len(m.group(1)),
                _fmt(color=self._alpha(ZEN_MD_LINK_COLOR, focused)),
            )

    def _is_focused(self, block_num: int) -> bool:
        start, end = self._focus_range
        if start < 0:
            return True
        return start <= block_num <= end

    def _alpha(self, color: QColor, focused: bool) -> QColor:
        if focused:
            return color
        c = QColor(color)
        c.setAlpha(ZEN_MD_MUTED_ALPHA)
        return c


def compute_focus_range(editor) -> tuple[int, int]:
    """Compute the paragraph range (start_block, end_block) around the cursor.

    A paragraph is a group of blocks separated by blank lines.
    """
    cursor = editor.textCursor()
    block = cursor.block()
    if not block.isValid():
        return (-1, -1)

    # Walk backward to paragraph start
    start = block.blockNumber()
    b = block.previous()
    while b.isValid() and b.text().strip():
        start = b.blockNumber()
        b = b.previous()

    # Walk forward to paragraph end
    end = block.blockNumber()
    b = block.next()
    while b.isValid() and b.text().strip():
        end = b.blockNumber()
        b = b.next()

    return (start, end)
