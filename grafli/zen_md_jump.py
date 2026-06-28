"""EasyMotion-style word jump overlay for the zen markdown editor."""

from __future__ import annotations

import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from grafli.constants import FONT_FAMILY

_JUMP_KEYS = "asdfjklghqweruioptyzxcvbnm"
_RE_WORD = re.compile(r"\b\w")

_BADGE_BG = QColor("#004578")
_BADGE_FG = QColor("#FFFFFF")
_BADGE_FONT = QFont(FONT_FAMILY, 10, QFont.Weight.Bold)
_DIM_COLOR = QColor(245, 242, 237, 200)


class WordJumpOverlay(QWidget):
    """Transparent overlay that shows jump labels on visible words."""

    def __init__(self, editor: QPlainTextEdit, parent: QWidget):
        super().__init__(parent)
        self._editor = editor
        self._targets: list[tuple[str, int]] = []  # (label, absolute_pos)
        self._label_rects: list[tuple[str, QRectF]] = []
        self._typed = ""
        self._active = False
        self._on_pick = None   # if set, picking calls it instead of moving caret

        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def activate(self, on_pick=None):
        """Show overlay with jump labels on visible words. When ``on_pick`` is
        given, selecting a label calls ``on_pick(position)`` and dismisses,
        instead of moving the editor's caret — used to pick span endpoints."""
        self._on_pick = on_pick
        self._typed = ""
        self._targets = self._find_visible_words()
        if not self._targets:
            return

        # Position over the editor viewport
        vp = self._editor.viewport()
        self.setGeometry(vp.mapTo(self.parentWidget(), vp.rect().topLeft()).x(),
                         vp.mapTo(self.parentWidget(), vp.rect().topLeft()).y(),
                         vp.width(), vp.height())
        self._compute_label_rects()
        self._active = True
        self.show()
        self.setFocus()
        self.raise_()
        self.update()

    def is_active(self) -> bool:
        return self._active

    def _dismiss(self):
        self._active = False
        self.hide()

    def _find_visible_words(self) -> list[tuple[str, int]]:
        """Scan visible words for their start positions, assign labels.

        Uses per-word ``cursorRect`` visibility rather than ``firstVisibleBlock``
        so the overlay works on both the source ``QPlainTextEdit`` and the
        rendered ``QTextBrowser`` (``QTextEdit``, which has no block geometry)."""
        editor = self._editor
        doc = editor.document()
        vp_h = editor.viewport().height()
        positions: list[int] = []

        block = doc.begin()
        while block.isValid():
            text = block.text()
            block_pos = block.position()
            below = False
            for m in _RE_WORD.finditer(text):
                pos = block_pos + m.start()
                c = QTextCursor(doc)
                c.setPosition(pos)
                r = editor.cursorRect(c)
                if r.top() > vp_h:        # this and later blocks are below view
                    below = True
                    break
                if r.bottom() >= 0:       # skip words scrolled above the view
                    positions.append(pos)
            if below:
                break
            block = block.next()

        # Assign labels
        total = len(positions)
        keys = _JUMP_KEYS
        if total <= len(keys):
            labels = list(keys[:total])
        else:
            labels = []
            for i in range(total):
                a = i // len(keys)
                b = i % len(keys)
                if a < len(keys):
                    labels.append(keys[a] + keys[b])
                else:
                    break

        return [(labels[i], positions[i]) for i in range(min(total, len(labels)))]

    def _compute_label_rects(self):
        """Map each target position to a pixel rect in overlay coordinates."""
        self._label_rects = []
        editor = self._editor
        vp = editor.viewport()

        for label, pos in self._targets:
            c = QTextCursor(editor.document())
            c.setPosition(pos)
            r = editor.cursorRect(c)
            # Convert from editor viewport coords to overlay coords
            top_left = vp.mapTo(self.parentWidget(), r.topLeft())
            own_pos = self.pos()
            x = top_left.x() - own_pos.x()
            y = top_left.y() - own_pos.y()
            badge_w = max(len(label) * 10, 16)
            self._label_rects.append((label, QRectF(x, y, badge_w, r.height())))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Dim overlay
        p.fillRect(self.rect(), _DIM_COLOR)

        # Draw badges
        p.setFont(_BADGE_FONT)
        for label, rect in self._label_rects:
            if self._typed and not label.startswith(self._typed):
                continue
            display = label[len(self._typed):]
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_BADGE_BG)
            p.drawRoundedRect(rect, 3, 3)
            p.setPen(_BADGE_FG)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, display)

        p.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._dismiss()
            # Return focus to editor
            self._editor.setFocus()
            return

        ch = event.text().lower()
        if not ch or ch not in _JUMP_KEYS:
            self._dismiss()
            self._editor.setFocus()
            return

        self._typed += ch

        # Check for exact match
        matches = [
            (label, pos) for label, pos in self._targets
            if label == self._typed
        ]
        if matches:
            _, pos = matches[0]
            if self._on_pick is not None:
                cb = self._on_pick
                self._dismiss()
                cb(pos)             # caller manages focus / next step
                return
            c = self._editor.textCursor()
            c.setPosition(pos)
            self._editor.setTextCursor(c)
            self._dismiss()
            self._editor.setFocus()
            return

        # Check if any labels still start with typed prefix
        remaining = [
            label for label, _ in self._targets
            if label.startswith(self._typed)
        ]
        if not remaining:
            self._dismiss()
            self._editor.setFocus()
            return

        self.update()
