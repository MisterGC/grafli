"""Overlay files mixin for GrafliView: ``A`` cycles through them.

``A`` goes off → Connectivity → each ``<stem>-res/<name>.overlay.json`` in
file-name order → off. A board without overlay files keeps the plain
Connectivity toggle and shows nothing new. The shown file is watched: an
edit recolours the board, a deleted or broken file turns the overlay off.
The legend card names the overlay, its producer, its categories or scale,
whether it is stale, and the selected element's reading, note and refs.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainter

from grafli.constants import MINIMAP_MARGIN
from grafli.items import BoxItem, NoteItem
from grafli.overlay_file import (
    OverlayProvider,
    load_overlay,
    overlay_named,
    overlay_paths,
)
from grafli.overlay_legend import (
    CARD_W,
    canvas_fonts,
    layout_card,
    legend_rows,
    paint_card,
)


class OverlayFilesMixin:
    """Expects the host class to have the ComplexityMixin state, plus
    _board_file(), toast(), _open_code_ref() and _clear_focus_filter()."""

    def _overlay_paths(self) -> list[Path]:
        here = self._board_file()
        return overlay_paths(Path(here)) if here else []

    def _overlay_shown(self) -> OverlayProvider | None:
        if self._complexity_active and isinstance(self._heat_provider,
                                                  OverlayProvider):
            return self._heat_provider
        return None

    def _toggle_complexity(self):
        """Off → Connectivity → each overlay file → off."""
        paths = self._overlay_paths()
        shown = self._overlay_shown()
        if not paths and shown is None:
            self._toggle_connectivity()
            return
        if not self._complexity_active:
            if self._degree_provider.analysable(self._board):
                self._show_heat(self._degree_provider)
                self.toast("Connectivity")
                return
            later = paths
        elif shown is None:
            later = paths
        else:
            current = shown.path.name
            later = [p for p in paths if p.name > current]
        broken = False
        for path in later:
            if self._show_overlay_file(path):
                return
            broken = True
        was_active = self._complexity_active
        if was_active:
            self._clear_complexity_heatmap()
        self._stop_overlay_watch()
        if was_active and not broken:
            self.toast("Overlays off")

    def _toggle_connectivity(self):
        """The plain toggle of a board without overlay files."""
        if self._complexity_active:
            self._clear_complexity_heatmap()
        else:
            if isinstance(self._heat_provider, OverlayProvider):
                self._heat_provider = self._degree_provider
            if not self._complexity_analysable():
                self.toast("No connectors to analyse", "warn")
                return
            self._show_heat(self._heat_provider)

    def _show_heat(self, provider):
        if self._complexity_active:
            self._clear_complexity_heatmap()
        if self._focus_active:
            self._clear_focus_filter()
        self._heat_provider = provider
        self._complexity_active = True
        self._apply_complexity_heatmap()

    def _read_overlay_file(self, path: Path) -> OverlayProvider | None:
        try:
            overlay = load_overlay(path)
        except ValueError as e:
            self.toast(f"{path.name}: {e}", "error")
            return None
        return OverlayProvider(overlay, path.parent.parent, path)

    def _show_overlay_file(self, path: Path) -> bool:
        provider = self._read_overlay_file(path)
        if provider is None:
            return False
        self._show_heat(provider)
        self._watch_overlay_file(path)
        self.toast(f"Overlay: {provider.overlay.title}")
        return True

    def show_overlay(self, name: str) -> None:
        """Show the board's overlay file *name* outside the ``A`` cycle, for a
        render or an export; ValueError when the board has no such file or
        it does not parse."""
        path = overlay_named(Path(self._board_file()), name)
        self._show_heat(OverlayProvider(load_overlay(path), path.parent.parent,
                                        path))

    # ── Live reload ──

    def _watch_overlay_file(self, path: Path):
        watcher = getattr(self, "_overlay_watcher", None)
        if watcher is not None and watcher._paths == [str(path)]:
            return
        self._stop_overlay_watch()
        from grafli.filewatcher import MultiFileWatcher
        watcher = MultiFileWatcher([str(path)], parent=self)
        watcher.files_changed.connect(self._on_overlay_file_changed)
        watcher.start()
        self._overlay_watcher = watcher

    def _stop_overlay_watch(self):
        watcher = getattr(self, "_overlay_watcher", None)
        if watcher is not None:
            watcher.stop()
            watcher.deleteLater()
            self._overlay_watcher = None

    def _on_overlay_file_changed(self, _changed: list = ()):
        shown = self._overlay_shown()
        if shown is None:
            self._stop_overlay_watch()
            return
        path = shown.path
        if not path.is_file():
            self._clear_complexity_heatmap()
            self._stop_overlay_watch()
            self.toast(f"Overlay file {path.name} is gone", "warn")
            return
        provider = self._read_overlay_file(path)
        if provider is None:
            self._clear_complexity_heatmap()
            self._stop_overlay_watch()
            return
        self._show_heat(provider)

    # ── Legend ──

    def _overlay_selected_id(self) -> str:
        selected = self._scene.selectedItems()
        if len(selected) == 1:
            item = selected[0]
            if isinstance(item, BoxItem):
                return item.box.id
            if isinstance(item, NoteItem):
                return item.note.id
        if not selected and len(self._selected_arrows) == 1:
            return self._selected_arrows[0].id
        return ""

    def _overlay_legend_lines(self, provider) -> list[tuple[str, str]]:
        """The legend as (role, text) rows, top to bottom."""
        return legend_rows(self._complexity_reading,
                           self._overlay_selected_id())

    def _draw_overlay_legend(self, painter: QPainter):
        """The legend card, bottom right above the minimap — or in its place
        while the minimap is hidden."""
        self._overlay_ref_rects = []
        provider = self._overlay_shown()
        if provider is None or self._complexity_reading is None:
            return
        painter.resetTransform()
        vp = self.viewport().rect()
        right = vp.width() - MINIMAP_MARGIN
        bottom = vp.height() - MINIMAP_MARGIN
        width = CARD_W
        panel = getattr(self, "_minimap_panel_rect", None)
        if self._minimap_visible and panel is not None and not panel.isNull():
            bottom = panel.top() - 8
            width = max(width, panel.width())

        # Lay out first so the card grows upward from its bottom edge.
        laid, height = layout_card(painter,
                                   self._overlay_legend_lines(provider),
                                   width, canvas_fonts())
        card = QRectF(right - width, bottom - height, width, height)
        paint_card(painter, card, laid, self._complexity_reading.legend,
                   self._overlay_ref_rects)

    def _overlay_legend_press(self, pos: QPointF) -> bool:
        """A click on a ref in the legend opens it like a code-note ``@ref``."""
        provider = self._overlay_shown()
        if provider is None:
            return False
        for rect, ref in getattr(self, "_overlay_ref_rects", []):
            if rect.contains(pos):
                self._open_code_ref(self._overlay_ref(provider, ref))
                return True
        return False

    @staticmethod
    def _overlay_ref(provider: OverlayProvider, ref: str) -> str:
        """``ref`` with a relative path taken from the overlay's source repo
        (or the board's directory when it names none)."""
        target = ref[1:] if ref.startswith("@") else ref
        m = re.match(r"^(.+?)(:\d+)?$", target)
        path = Path(m.group(1)).expanduser()
        if not path.is_absolute():
            path = provider.ref_base() / path
        return f"@{path}{m.group(2) or ''}"
