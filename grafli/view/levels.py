"""Levels for GrafliView (mixin): sub-board miniatures (D3).

A box with `&graph:<name>` shows a raster miniature of its sub-board once its
body is large enough on screen. Zooming alone never switches boards, and
exports render without miniatures.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from grafli import iconset
from grafli.items import BoxItem
from grafli.lod import should_show_miniature


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
