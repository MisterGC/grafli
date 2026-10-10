"""Box docs for GrafliView (mixin): the one-line doc and the peek (D2).

A box with `&doc:<name>` shows its doc's first sentence, cut to one line,
below its label — only at the detailed zoom level, and only on the canvas.
`gv` opens a view-only panel anchored to the box with the whole doc,
rendered like a Markdown note and bounded like the 12-line note cap; it
moves nothing and `Esc` closes it. Box docs are read from the vault, and
the window's docs watcher reloads the board when one changes.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPalette
from PySide6.QtWidgets import QFrame, QTextBrowser, QVBoxLayout

from grafli import iconset, theme
from grafli.format import Note, doc_name
from grafli.items import BoxItem, NoteItem
from grafli.lod import should_collapse
from grafli.md_note import doc_first_sentence

# The peek sits this far from the box it belongs to and from the viewport
# edges, in screen pixels.
PEEK_GAP = 10


class DocPeek(QFrame):
    """The view-only panel `gv` opens: a box's doc as a Markdown note."""

    def __init__(self, view, box_id: str, body: str):
        super().__init__(view.viewport())
        self.box_id = box_id
        self.setObjectName("docPeek")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._browser = QTextBrowser(self)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(
            lambda url: view._open_url_string(url.toString()))
        # Keys stay with the canvas, so Esc and gv reach the view; the
        # wheel still scrolls the panel.
        self._browser.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(NoteItem._PAD, NoteItem._PAD,
                               NoteItem._PAD, NoteItem._PAD)
        lay.addWidget(self._browser)
        self.set_body(body)
        self.show()
        self.raise_()

    def set_body(self, body: str):
        """Render *body* the way a doc-bodied note renders it, and size the
        panel: the note's wrap width, at most the note cap's 12 lines tall."""
        note = Note(id="", x=0, y=0, text=body, attach_kind="doc")
        item = NoteItem(note)
        doc = item._md_document()
        doc.setParent(self._browser)
        surface = QColor(theme.SURFACE)
        border = QColor(theme.INK)
        border.setAlphaF(0.25)
        self.setStyleSheet(
            f"#docPeek {{ background: {surface.name()};"
            f" border: 1px solid {border.name(QColor.NameFormat.HexArgb)};"
            f" border-radius: {NoteItem._BG_RADIUS}px; }}")
        pal = self._browser.palette()
        pal.setColor(QPalette.ColorRole.Base, surface)
        pal.setColor(QPalette.ColorRole.Text, theme.NOTE_CODE_TEXT_COLOR)
        pal.setColor(QPalette.ColorRole.Link, theme.NOTE_PEN_COLOR)
        self._browser.setPalette(pal)
        # The width the laid-out text uses, so a short doc stays narrow.
        width = max(doc.idealWidth(), 120.0)
        self._browser.setDocument(doc)
        line_h = QFontMetricsF(item._note_font()).height()
        cap_h = NoteItem._DISPLAY_CAP_LINES * line_h
        doc.setTextWidth(width)
        content_h = min(doc.size().height(), cap_h)
        scroll_w = self._browser.verticalScrollBar().sizeHint().width()
        pad = 2 * NoteItem._PAD
        self.resize(int(width + scroll_w + pad + 4),
                    int(content_h + pad + 4))

    def text(self) -> str:
        return self._browser.toPlainText()

    def scroll_bar(self):
        return self._browser.verticalScrollBar()


class BoxDocsMixin:
    # ── Reading box docs ──

    def _reset_box_docs(self):
        """Forget the box docs read so far; the next look reads the files."""
        self._box_doc_cache = {}

    def _box_doc_file(self, box) -> Path | None:
        """The vault file of a `&doc` box, None otherwise or while this
        board has no file of its own."""
        if getattr(box, "attach_kind", "") != "doc":
            return None
        here = self._board_file()
        if not here:
            return None
        from grafli.resources import doc_path
        return doc_path(Path(here), doc_name(box))

    def box_doc_body(self, box) -> str | None:
        """The text of *box*'s doc, None when it has none or the file is
        missing. Read once per board load."""
        path = self._box_doc_file(box)
        if path is None:
            return None
        cache = getattr(self, "_box_doc_cache", None)
        if cache is None:
            cache = self._box_doc_cache = {}
        key = str(path)
        if key not in cache:
            try:
                cache[key] = path.read_text(encoding="utf-8")
            except OSError:
                cache[key] = None
        return cache[key]

    # ── The doc line ──

    @staticmethod
    def _may_show_doc_line(item: BoxItem) -> bool:
        """A box draws its doc line only where its body is free: not as a
        container, and not with a fill icon (its label is a caption)."""
        if item._is_parent:
            return False
        icon = item.box.icon
        return not (icon and iconset.has_icon(icon)
                    and item.box.icon_placement == "")

    def _refresh_doc_lines(self, scale: float | None = None, skip=None,
                           lod_on: bool | None = None):
        """Give every `&doc` box at the detailed level its doc line, and take
        it from the rest. *skip* holds boxes the level of detail hides or
        reduces; with the level of detail on, the line itself must be
        legible on screen. Nothing shows while exports hold it back."""
        if scale is None:
            scale = self._current_zoom()
        if skip is None:
            skip = self._lod_skip_set()
        if lod_on is None:
            lod_on = (self._lod_enabled if self._present_detail is None
                      else self._present_detail == "summary")
        held = getattr(self, "_miniatures_held", 0)
        for bid, item in self._box_items.items():
            line = ""
            if (not held and bid not in skip
                    and self._may_show_doc_line(item)):
                body = self.box_doc_body(item.box)
                if body:
                    line = doc_first_sentence(body)
                if line and not item.doc_line_fits():
                    line = ""
                if line and lod_on and should_collapse(
                        item.doc_line_px() * scale, not item._doc_line):
                    line = ""
            item.set_doc_line(line)
        self._place_doc_peek()

    # ── The peek ──

    def _selected_box_item(self) -> BoxItem | None:
        items = self._scene.selectedItems()
        if len(items) == 1 and isinstance(items[0], BoxItem):
            return items[0]
        return None

    def _peek_doc(self):
        """`gv`: open the selected box's doc in a view-only panel beside it,
        or close it when it is already open for that box."""
        item = self._selected_box_item()
        if item is None:
            self.toast("Select a box with a doc to peek at it", "info")
            return
        peek = getattr(self, "_doc_peek", None)
        if peek is not None and peek.box_id == item.box.id:
            self._close_doc_peek()
            return
        label = " ".join(item.box.label.split()) or item.box.id
        if item.box.attach_kind != "doc":
            self.toast(f"'{label}' has no doc to peek at", "info")
            return
        body = self.box_doc_body(item.box)
        if body is None:
            self.toast(f"The doc '{doc_name(item.box)}' of '{label}' is "
                       "missing", "warn")
            return
        self._close_doc_peek()
        self._doc_peek = DocPeek(self, item.box.id, body)
        self._doc_peek_board = self._board_file()
        self._place_doc_peek()

    def doc_peek(self) -> DocPeek | None:
        return getattr(self, "_doc_peek", None)

    def _close_doc_peek(self) -> bool:
        """Close the peek; True when one was open."""
        peek = getattr(self, "_doc_peek", None)
        if peek is None:
            return False
        self._doc_peek = None
        peek.hide()
        peek.deleteLater()
        return True

    def _refresh_doc_peek(self):
        """After a board load: show the reloaded doc in an open peek, or
        close it when its box, its doc or its board is gone."""
        peek = getattr(self, "_doc_peek", None)
        if peek is None:
            return
        item = self._box_items.get(peek.box_id)
        body = (self.box_doc_body(item.box) if item is not None else None)
        if (body is None
                or self._board_file() != getattr(self, "_doc_peek_board", None)):
            self._close_doc_peek()
            return
        peek.set_body(body)
        self._place_doc_peek()

    def _place_doc_peek(self):
        """Keep the peek beside its box as the view pans and zooms: right of
        it when there is room, else left, else below, inside the viewport."""
        peek = getattr(self, "_doc_peek", None)
        if peek is None:
            return
        item = self._box_items.get(peek.box_id)
        if item is None or item.scene() is None:
            self._close_doc_peek()
            return
        box = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
        vp = self.viewport().rect()
        w, h = peek.width(), peek.height()
        if box.right() + PEEK_GAP + w <= vp.right() - PEEK_GAP:
            x, y = box.right() + PEEK_GAP, box.top()
        elif box.left() - PEEK_GAP - w >= vp.left() + PEEK_GAP:
            x, y = box.left() - PEEK_GAP - w, box.top()
        else:
            x, y = box.left(), box.bottom() + PEEK_GAP
        x = max(vp.left() + PEEK_GAP, min(x, vp.right() - PEEK_GAP - w))
        y = max(vp.top() + PEEK_GAP, min(y, vp.bottom() - PEEK_GAP - h))
        peek.move(x, y)
        peek.raise_()   # above any other widget on the viewport

    def doc_peek_rect(self) -> QRect | None:
        """The peek's place in viewport coordinates, None while closed."""
        peek = getattr(self, "_doc_peek", None)
        return peek.geometry() if peek is not None else None

    def scrollContentsBy(self, dx: int, dy: int):
        super().scrollContentsBy(dx, dy)
        self._place_doc_peek()

