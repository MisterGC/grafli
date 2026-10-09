"""Levels for GrafliView (mixin): sub-board miniatures and entering them (D3).

A box with `&graph:<name>` shows a raster miniature of its sub-board once its
body is large enough on screen. Entering stays an explicit key — Return or
`gd` — and plays a zoom into the box that hands over to the sub-board fitted;
`gu` plays it in reverse. Zooming alone never switches boards, and exports
render without miniatures.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QRectF, Qt, QTimeLine
from PySide6.QtGui import QPainter, QPixmap, QTransform
from PySide6.QtWidgets import QWidget

from grafli import iconset
from grafli.format import Arrow
from grafli.items import BoxItem, ImageItem, NoteItem
from grafli.lod import should_show_miniature

# Durations of the level transition, in ms: the zoom into the box (or out of
# it on `gu`), and the crossfade that hands over between the two boards.
ZOOM_MS = 320
FADE_MS = 200


class _Crossfade(QWidget):
    """A still of the board being left, faded out over the board entered."""

    def __init__(self, viewport: QWidget, still: QPixmap):
        super().__init__(viewport)
        self._still = still
        self._opacity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(viewport.rect())
        self._timeline = QTimeLine(FADE_MS, self)
        self._timeline.setUpdateInterval(16)
        self._timeline.valueChanged.connect(self._step)
        self._timeline.finished.connect(self.deleteLater)
        self.show()
        self.raise_()
        self._timeline.start()

    def _step(self, value: float):
        self._opacity = 1.0 - value
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setOpacity(self._opacity)
        p.drawPixmap(self.rect(), self._still)
        p.end()


class LevelsMixin:
    # ── Miniatures ──

    def _miniature_cache(self):
        cache = getattr(self, "_miniatures", None)
        if cache is None:
            from grafli.miniature import MiniatureCache
            cache = self._miniatures = MiniatureCache()
        return cache

    def _sub_board_path(self, el) -> Path | None:
        """The file a `&graph` element's sub-board lives in, None otherwise
        or while this board has no file of its own."""
        if getattr(el, "attach_kind", "") != "graph" or not el.url:
            return None
        here = getattr(self.window(), "_file_path", None)
        if not here:
            return None
        from grafli.format import split_board_fragment
        from grafli.resources import graph_path
        name, _ = split_board_fragment(el.url)
        return graph_path(Path(here), name)

    @staticmethod
    def _may_show_miniature(item: BoxItem) -> bool:
        """A box draws a miniature only where its body is free: not as a
        container (its children own the body) and not under a fill icon."""
        if item._is_parent:
            return False
        icon = item.box.icon
        return not (icon and iconset.has_icon(icon)
                    and item.box.icon_placement not in ("badge", "lead"))

    def _refresh_miniatures(self, scale: float, skip=frozenset()):
        """Give every `&graph` box whose body is large enough on screen its
        miniature, and take it from the rest. *skip* holds boxes the level of
        detail hides or reduces. Nothing shows while the view is not on screen
        or an export holds miniatures back."""
        shown_paths: set[str] = set()
        active = (self.isVisible() and scale > 0
                  and not getattr(self, "_miniatures_held", 0))
        for bid, item in self._box_items.items():
            pix = None
            path = self._sub_board_path(item.box) if active else None
            if (path is not None and bid not in skip
                    and self._may_show_miniature(item)):
                area = item.miniature_rect()
                body_px = min(area.width(), area.height()) * scale
                if should_show_miniature(body_px, item._miniature is not None):
                    pix = self._miniature_cache().get(path)
                    if pix is not None:
                        shown_paths.add(str(path.resolve()))
            item.set_miniature(pix)
        self._watch_miniatures(shown_paths)

    def _watch_miniatures(self, paths: set[str]):
        """Poll the files of the miniatures on screen, so one updates as soon
        as its sub-board file changes, without waiting for a zoom."""
        watcher = getattr(self, "_miniature_watcher", None)
        if watcher is not None and set(watcher._paths) == paths:
            return
        if watcher is not None:
            watcher.stop()
            watcher.deleteLater()
            self._miniature_watcher = None
        if not paths:
            return
        from grafli.filewatcher import MultiFileWatcher
        watcher = MultiFileWatcher(sorted(paths), parent=self)
        watcher.files_changed.connect(self._on_miniature_files_changed)
        watcher.start()
        self._miniature_watcher = watcher

    def _on_miniature_files_changed(self, _changed: list):
        self._refresh_miniatures(self._current_zoom(), self._lod_skip_set())

    def _lod_skip_set(self) -> set[str]:
        """Boxes the level of detail currently hides, tiles or shells."""
        skip = set(self._lod_simplified) | set(self._lod_collapsed)
        for bid, item in self._box_items.items():
            if not item.isVisible():
                skip.add(bid)
        return skip

    @contextmanager
    def miniatures_held(self):
        """Render the scene without miniatures for the duration — exports and
        thumbnails show a `&graph` box as it is drawn without one."""
        shown = {bid: item._miniature for bid, item in self._box_items.items()
                 if item._miniature is not None}
        self._miniatures_held = getattr(self, "_miniatures_held", 0) + 1
        for bid in shown:
            self._box_items[bid].set_miniature(None)
        try:
            yield
        finally:
            self._miniatures_held -= 1
            if not self._miniatures_held:
                for bid, pix in shown.items():
                    item = self._box_items.get(bid)
                    if item is not None and item.scene() is not None:
                        item.set_miniature(pix)

    # ── Entering a level ──

    def _go_down(self):
        """`gd`: enter the sub-board of the selected element."""
        el = self._selected_board_link()
        if el is None:
            self.toast("Select a box with a sub-board to go down", "info")
            return
        self._open_attachment(el)

    def _selected_board_link(self):
        """The one selected element whose attachment is a board, or None."""
        candidates = []
        if self._selected_arrow is not None:
            candidates.append(self._selected_arrow)
        for item in self._scene.selectedItems():
            if isinstance(item, BoxItem):
                candidates.append(item.box)
            elif isinstance(item, NoteItem):
                candidates.append(item.note)
            elif isinstance(item, ImageItem):
                candidates.append(item.image)
        if len(candidates) != 1:
            return None
        el = candidates[0]
        if el.attach_kind == "graph" and el.url:
            return el
        from grafli.format import split_board_fragment
        if el.url and split_board_fragment(el.url)[0].endswith(".grafli"):
            return el
        return None

    def element_by_id(self, eid: str):
        """The box, note or image with id *eid* on this board, or None."""
        if not eid:
            return None
        if eid in self._box_items:
            return self._box_items[eid].box
        if eid in self._note_items:
            return self._note_items[eid].note
        if eid in self._image_items:
            return self._image_items[eid].image
        return None

    def level_entry_rect(self, el) -> QRectF | None:
        """The scene rect entering *el*'s board zooms into: its miniature
        when it has one, else the element itself; None for an arrow or an
        element that is not on this board."""
        if el is None or isinstance(el, Arrow):
            return None
        item = (self._box_items.get(el.id) or self._note_items.get(el.id)
                or self._image_items.get(el.id))
        if item is None:
            return None
        if isinstance(item, BoxItem) and self._may_show_miniature(item):
            path = self._sub_board_path(item.box)
            pix = (self._miniature_cache().get(path)
                   if path is not None else None)
            if pix is not None:
                return item.mapRectToScene(item.miniature_pixmap_rect(pix))
        return item.sceneBoundingRect()

    def _show_entry_miniature(self, el):
        """Draw *el*'s miniature for the transition whatever its size, so the
        zoom visibly lands on the board it hands over to."""
        item = self._box_items.get(getattr(el, "id", ""))
        if item is None or not self._may_show_miniature(item):
            return
        path = self._sub_board_path(item.box)
        pix = self._miniature_cache().get(path) if path is not None else None
        if pix is not None:
            item.set_miniature(pix)

    def transitions_enabled(self) -> bool:
        """Animate level changes only on screen; offscreen they are instant."""
        return self.isVisible() and ZOOM_MS > 0

    def play_enter(self, el, rect: QRectF, switch):
        """Zoom into *rect* (where *el* sits on this board), then call
        *switch* to open the sub-board and crossfade over to it."""
        self._show_entry_miniature(el)

        def handover():
            still = self.viewport().grab()
            switch()
            _Crossfade(self.viewport(), still)

        self._animate_to_rect(rect, duration=ZOOM_MS,
                              easing=QEasingCurve.Type.InOutCubic)
        if self._zoom_timeline is None:
            handover()
        else:
            self._zoom_timeline.finished.connect(handover)

    def play_exit(self, el, rect: QRectF, still: QPixmap, vs):
        """`gu`'s reverse transition, called right after the parent board was
        restored to *vs*: start framed on *rect* (the box you came out of)
        with *still* (the board you left) over it, and zoom back out to *vs*
        while the still fades."""
        zoom = self._current_zoom()
        center = self.mapToScene(self.viewport().rect().center())
        vp = self.viewport().rect()
        z = min(vp.width() / max(rect.width(), 1.0),
                vp.height() / max(rect.height(), 1.0))
        z = max(self.MIN_ZOOM_ABS, min(z, self.MAX_ZOOM))
        self.setTransform(QTransform().scale(z, z))
        self.centerOn(rect.center())
        self._show_entry_miniature(el)
        _Crossfade(self.viewport(), still)
        self._animate_to_zoom_and_center(zoom, center, duration=ZOOM_MS,
                                         easing=QEasingCurve.Type.InOutCubic)
        # Land exactly where you left the board, rounding aside.
        if self._zoom_timeline is None:
            self.restore_view(vs)
        else:
            self._zoom_timeline.finished.connect(lambda: self.restore_view(vs))
