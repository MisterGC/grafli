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

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen

from grafli import theme
from grafli.constants import FONT_FAMILY, MINIMAP_MARGIN
from grafli.items import BoxItem, NoteItem
from grafli.overlay_file import (
    OverlayProvider,
    load_overlay,
    overlay_paths,
)

_LEGEND_W = 260
_LEGEND_PAD = 10
_SWATCH = 10
_NOTE_LINES = 3


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
        reading = self._complexity_reading
        legend = reading.legend
        rows = [("title", legend.title)]
        if legend.producer:
            rows.append(("dim", legend.producer))
        if legend.stale:
            rows.append(("stale", "⚠ " + legend.stale))
        if legend.categories:
            rows += [("swatch", label) for label, _ in legend.categories]
        else:
            rows.append(("scale", ""))
        rows.append(("no_data", "no data"))
        elem_id = self._overlay_selected_id()
        if elem_id:
            detail = reading.details.get(elem_id)
            rows.append(("rule", ""))
            if detail is None:
                rows.append(("text", f"{elem_id}: no data"))
            else:
                rows.append(("text", f"{elem_id}: {detail.reading}"))
                if detail.note:
                    rows.append(("note", detail.note))
                rows += [("ref", ref) for ref in detail.refs]
        return rows

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
        width = _LEGEND_W
        panel = getattr(self, "_minimap_panel_rect", None)
        if self._minimap_visible and panel is not None and not panel.isNull():
            bottom = panel.top() - 8
            width = max(width, panel.width())
        inner = width - 2 * _LEGEND_PAD

        title_font = QFont(FONT_FAMILY, 12, QFont.Weight.Bold)
        body_font = QFont(FONT_FAMILY, 10)
        ref_font = QFont(FONT_FAMILY, 10)
        ref_font.setUnderline(True)

        # Lay out first so the card grows upward from its bottom edge.
        laid: list[tuple[str, str, list[str], QFont, float]] = []
        for role, text in self._overlay_legend_lines(provider):
            font = (title_font if role == "title"
                    else ref_font if role == "ref" else body_font)
            painter.setFont(font)
            fm = painter.fontMetrics()
            if role in ("note", "stale"):
                lines = self._wrap(fm, text, inner)
            elif role in ("swatch", "no_data"):
                lines = [fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                       inner - _SWATCH - 6)]
            else:
                lines = [fm.elidedText(text, Qt.TextElideMode.ElideRight,
                                       inner)]
            h = (_SWATCH + 10 if role == "scale"
                 else 9 if role == "rule"
                 else fm.height() * len(lines) + 2)
            if role == "scale":
                h += fm.height()
            laid.append((role, text, lines, font, h))
        height = sum(h for *_, h in laid) + 2 * _LEGEND_PAD
        card = QRectF(right - width, bottom - height, width, height)

        painter.setPen(QPen(theme.MINIMAP_BORDER_COLOR, 1))
        painter.setBrush(QBrush(theme.OVERLAY_BG))
        painter.drawRoundedRect(card, 6, 6)

        legend = self._complexity_reading.legend
        swatches = iter(legend.categories)
        x = card.left() + _LEGEND_PAD
        y = card.top() + _LEGEND_PAD
        for role, text, lines, font, h in laid:
            painter.setFont(font)
            fm = painter.fontMetrics()
            ink = theme.overlay_ink(0.6 if role in ("dim", "no_data") else 1.0)
            painter.setPen(QPen(ink))
            if role == "swatch":
                _label, color = next(swatches)
                self._draw_swatch(painter, x, y + (fm.height() - _SWATCH) / 2,
                                  QBrush(QColor(theme.resolve_color(color)
                                                or theme.HEATMAP_TEXT_COLOR)))
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(x + _SWATCH + 6, y + fm.ascent()),
                                 lines[0])
            elif role == "no_data":
                self._draw_swatch(painter, x, y + (fm.height() - _SWATCH) / 2,
                                  QBrush(theme.overlay_ink(0.6),
                                         Qt.BrushStyle.BDiagPattern))
                painter.setPen(QPen(ink))
                painter.drawText(QPointF(x + _SWATCH + 6, y + fm.ascent()),
                                 lines[0])
            elif role == "scale":
                bar = QRectF(x, y + 4, inner, _SWATCH)
                grad = QLinearGradient(bar.left(), 0, bar.right(), 0)
                for pos, color in theme.HEATMAP_STOPS:
                    grad.setColorAt(pos, color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(grad))
                painter.drawRoundedRect(bar, 2, 2)
                painter.setPen(QPen(theme.overlay_ink(0.6)))
                label_y = bar.bottom() + 4 + fm.ascent()
                painter.drawText(QPointF(x, label_y), legend.low)
                painter.drawText(
                    QPointF(x + inner - fm.horizontalAdvance(legend.high),
                            label_y), legend.high)
            elif role == "rule":
                painter.setPen(QPen(theme.overlay_ink(0.25), 1))
                painter.drawLine(QPointF(x, y + 4), QPointF(x + inner, y + 4))
            else:
                if role == "ref":
                    painter.setPen(QPen(theme.FLOWS_ACCENT))
                    self._overlay_ref_rects.append(
                        (QRectF(x, y, fm.horizontalAdvance(lines[0]),
                                fm.height()), text))
                for i, line in enumerate(lines):
                    painter.drawText(
                        QPointF(x, y + fm.height() * i + fm.ascent()), line)
            y += h

    @staticmethod
    def _draw_swatch(painter: QPainter, x: float, y: float, brush: QBrush):
        painter.setPen(QPen(theme.overlay_ink(0.4), 1))
        painter.setBrush(brush)
        painter.drawRoundedRect(QRectF(x, y, _SWATCH, _SWATCH), 2, 2)

    @staticmethod
    def _wrap(fm, text: str, width: float) -> list[str]:
        """Word-wrap ``text`` into at most a few lines, the last elided."""
        lines: list[str] = []
        current = ""
        for word in text.split():
            trial = f"{current} {word}".strip()
            if fm.horizontalAdvance(trial) <= width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) > _NOTE_LINES:
            rest = " ".join(lines[_NOTE_LINES - 1:])
            lines = lines[:_NOTE_LINES - 1] + [rest]
        return [fm.elidedText(line, Qt.TextElideMode.ElideRight, int(width))
                for line in lines] or [""]

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
