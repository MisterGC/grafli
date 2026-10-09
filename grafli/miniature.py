"""Sub-board miniatures — the raster a `&graph` box shows of its level (D3).

A miniature is the sub-board rendered whole, framed the way opening it fits
the view (its content bounds plus the fit margin), through the bookmark
thumbnail renderer. It is made lazily on first need and kept until the
sub-board file changes: every lookup compares the file's mtime and size with
the ones the raster was made from, so an edit made anywhere — another app,
an agent, this app on the sub-board itself — shows on the next paint. A
theme switch re-renders it too.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPixmap

# Same margin `_zoom_fit` adds around the content: the miniature is what the
# sub-board looks like right after entering it.
FIT_MARGIN = 40.0
# Longest side of the raster in pixels — sharp at the sizes a box reaches on
# screen, cheap enough to keep one per sub-board.
MAX_PX = 900


def fit_rect(scene) -> QRectF:
    """The scene rect a fitted view of *scene* shows, null when empty."""
    rect = scene.itemsBoundingRect()
    if rect.isNull():
        return rect
    m = FIT_MARGIN
    return rect.adjusted(-m, -m, m, m)


def _stamp(path: Path) -> tuple[int, int, str] | None:
    from grafli import theme
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size, theme.name()


class MiniatureCache:
    """Rasters of sub-boards by path, each valid until its file changes."""

    def __init__(self):
        self._entries: dict[Path, tuple[tuple[int, int, str], QPixmap | None]] = {}
        self._renderer = None
        self.renders = 0   # how many rasters were made (tests read this)

    def get(self, path: Path) -> QPixmap | None:
        """The miniature of the board at *path*; None when the file is
        missing, unreadable or empty."""
        key = path.resolve()
        stamp = _stamp(key)
        if stamp is None:
            self._entries.pop(key, None)
            return None
        hit = self._entries.get(key)
        if hit is not None and hit[0] == stamp:
            return hit[1]
        pix = self._render(key)
        self._entries[key] = (stamp, pix)
        return pix

    def is_fresh(self, path: Path) -> bool:
        """True when *path* has a raster that still matches the file."""
        key = path.resolve()
        hit = self._entries.get(key)
        return hit is not None and hit[0] == _stamp(key)

    def clear(self):
        self._entries.clear()

    def _render(self, path: Path) -> QPixmap | None:
        from grafli.flows import render_bookmark_pixmap
        from grafli.format import Bookmark, parse
        from grafli.resources import classify_attachments, load_docs
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        board = parse(text)
        classify_attachments(path, board)
        load_docs(path, board)
        view = self._renderer_view()
        view.base_dir = str(path.parent)
        view.load_board(board)
        rect = fit_rect(view._scene)
        if rect.isNull():
            return None
        self.renders += 1
        bm = Bookmark(id="_miniature", label="",
                      view=(rect.x(), rect.y(), rect.width(), rect.height()))
        return render_bookmark_pixmap(view, bm, MAX_PX, MAX_PX)

    def _renderer_view(self):
        # One hidden view renders every sub-board in turn. It is never shown,
        # so it never draws miniatures of its own (no recursion).
        if self._renderer is None:
            from grafli.view import GrafliView
            self._renderer = GrafliView()
        return self._renderer
