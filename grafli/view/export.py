"""Board export for GrafliView (mixin).

Rendering the current board out of the app: SVG file export and
PNG-to-clipboard, sized from the scene's content bounds and drawn through
the same painter path the canvas uses.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QImage, QPainter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsItem
from contextlib import contextmanager, nullcontext
from grafli import theme
from grafli.legend import draw_legend, legend_height
from grafli.overlay_legend import CARD_W, draw_export_card, measure_card
from grafli.items import (
    BoxItem,
    BoxLabelItem,
    ImageItem,
    NoteItem,
    ResizeHandle,
)


class ExportMixin:
    # ── Export (SVG file / PNG clipboard) ──

    @contextmanager
    def _export_scene_context(self, padding: int = 20, region=None):
        """Prepare the scene for clean export, yield the padded bounding rect.

        Hides unselected items when there is a selection, clears selection
        decorations, and hides the mode badge.  Restores everything on exit.
        A non-null *region* (QRectF, already padded by the caller) overrides
        the default whole-scene bounding rect — used for targeted renders.
        """
        selected = [
            i for i in self._scene.selectedItems()
            if isinstance(i, (BoxItem, NoteItem, ImageItem))
        ]
        selected_ids: set[str] = set()
        for item in selected:
            if isinstance(item, BoxItem):
                selected_ids.add(item.box.id)
            elif isinstance(item, NoteItem):
                selected_ids.add(item.note.id)
            elif isinstance(item, ImageItem):
                selected_ids.add(item.image.id)

        hidden: list[QGraphicsItem] = []
        was_selected: list[QGraphicsItem] = []
        badge_items: list[QGraphicsItem] = []

        if selected_ids:
            for item in self._scene.items():
                keep = False
                if isinstance(item, (BoxItem, NoteItem, ImageItem)):
                    eid = ""
                    if isinstance(item, BoxItem):
                        eid = item.box.id
                    elif isinstance(item, NoteItem):
                        eid = item.note.id
                    elif isinstance(item, ImageItem):
                        eid = item.image.id
                    keep = eid in selected_ids
                elif isinstance(item, BoxLabelItem):
                    keep = (isinstance(item._box_item, BoxItem)
                            and item._box_item.box.id in selected_ids)
                elif isinstance(item, ResizeHandle):
                    keep = False
                else:
                    arrow = item.data(0)
                    if hasattr(arrow, "from_id") and hasattr(arrow, "to_id"):
                        keep = (arrow.from_id in selected_ids
                                and arrow.to_id in selected_ids)
                if not keep and item.isVisible():
                    item.setVisible(False)
                    hidden.append(item)

        for item in self._scene.selectedItems():
            item.setSelected(False)
            was_selected.append(item)

        if self._mode_badge:
            badge_items.append(self._mode_badge)
            self._mode_badge.setVisible(False)
        if self._mode_badge_bg:
            badge_items.append(self._mode_badge_bg)
            self._mode_badge_bg.setVisible(False)

        if region is not None and not region.isNull():
            rect = QRectF(region)
        else:
            rect = self._scene.itemsBoundingRect()
            if rect.isNull():
                rect = QRectF(0, 0, 100, 100)
            rect = rect.adjusted(-padding, -padding, padding, padding)

        try:
            yield rect
        finally:
            for item in hidden:
                item.setVisible(True)
            for item in was_selected:
                item.setSelected(True)
            for item in badge_items:
                item.setVisible(True)

    def _export_extras_held(self):
        """Hold miniatures back for an export; a headless render keeps them,
        as the canvas shows them. Doc lines stay as the canvas shows them."""
        if self._headless_board is not None:
            return nullcontext()
        return self.miniatures_held()

    def _legend_band(self, rect: QRectF, padding: int):
        """Where the map palette's legend goes below the exported *rect*,
        in board units, with its entries and text size; None while the
        legend is off or the board uses no palette entry."""
        if not self._legend_visible:
            return None
        entries = self.legend_entries()
        if not entries:
            return None
        px = max(14.0, rect.width() / 90)
        inset = max(float(padding), px)
        width = max(px * 4, rect.width() - 2 * inset)
        height = legend_height(entries, px, width)
        band = QRectF(rect.left(), rect.bottom(), rect.width(),
                      height + px * 0.8)
        return band, QRectF(rect.left() + inset, rect.bottom(), width,
                            height), entries, px

    def _overlay_band(self, top: float, rect: QRectF, padding: int):
        """Where the shown overlay's legend card goes below the exported
        *rect*, from *top* down, in board units, with the card's scale,
        reading and measured rows; None while no overlay file is shown."""
        reading = self._complexity_reading
        if self._overlay_shown() is None or reading is None:
            return None
        px = max(14.0, rect.width() / 90)
        scale = px / 10
        inset = max(float(padding), px)
        laid, height = measure_card(reading)
        width = CARD_W * scale
        band = QRectF(rect.left(), top, max(rect.width(), width + 2 * inset),
                      height * scale + px * 0.8)
        at = QPointF(band.right() - inset - width, top)
        return band, at, scale, reading, laid, height

    def _export_bands(self, rect: QRectF, padding: int):
        """The exported page around *rect* with the palette's legend and the
        shown overlay's card below it: the page and both bands (None when
        off)."""
        legend = self._legend_band(rect, padding)
        top = legend[0].bottom() if legend else rect.bottom()
        overlay = self._overlay_band(top, rect, padding)
        page = QRectF(rect)
        for band in (legend, overlay):
            if band:
                page = page.united(band[0])
        return page, legend, overlay

    def _draw_export_bands(self, painter: QPainter, legend, overlay):
        if legend:
            # On an overlay's darkened canvas the board ink would not read.
            ink = theme.HEATMAP_TEXT_COLOR if overlay else None
            draw_legend(painter, legend[1], legend[2], legend[3], ink)
        if overlay:
            _band, at, scale, reading, laid, height = overlay
            draw_export_card(painter, at, scale, reading, laid, height)

    def _page_background(self):
        """The colour an exported page sits on: the darkened canvas of a
        shown overlay file, the paper otherwise."""
        brush = self._scene.backgroundBrush()
        if (self._overlay_shown() is None
                or brush.style() == Qt.BrushStyle.NoBrush):
            return theme.SCENE_BG
        return brush.color()

    def _render_svg_bytes(self, padding: int = 20, region=None) -> QByteArray:
        """Render the current diagram (or selection) to SVG bytes, the
        palette's legend below it while the legend is on and the shown
        overlay's card below that."""
        with self._export_extras_held(), \
                self._export_scene_context(padding=padding,
                                           region=region) as rect:
            page, legend, overlay = self._export_bands(rect, padding)
            buf = QByteArray()
            io = QBuffer(buf)
            io.open(QIODevice.OpenModeFlag.WriteOnly)
            gen = QSvgGenerator()
            gen.setOutputDevice(io)
            gen.setSize(page.size().toSize())
            gen.setViewBox(page)
            gen.setTitle("Grafli Diagram")
            painter = QPainter(gen)
            painter.fillRect(page, QBrush(self._page_background()))
            # Paint onto the viewBox itself, so SVG coordinates are board
            # coordinates; a null target would paint from (0, 0) and shift
            # the board off a viewBox that does not start there.
            self._scene.render(painter, rect, rect)
            self._draw_export_bands(painter, legend, overlay)
            painter.end()
            io.close()
        return buf

    def _render_png_image(
        self, scale: int = 2, padding: int = 20, region=None,
    ) -> QImage:
        """Render the current diagram (or selection) to a QImage, the
        palette's legend below it while the legend is on and the shown
        overlay's card below that."""
        with self._export_extras_held(), \
                self._export_scene_context(padding=padding,
                                           region=region) as rect:
            page, legend, overlay = self._export_bands(rect, padding)
            size = page.size().toSize()
            image = QImage(
                size.width() * scale,
                size.height() * scale,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(self._page_background())
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Always render against an explicit pixel target. Setting DPR
            # before render() with a null target makes Qt drop most of the
            # scene for certain aspect ratios (wide-and-short pipelines).
            banded = legend is not None or overlay is not None
            board_w = (rect.width() * scale if page.width() > rect.width()
                       else float(image.width()))
            board_h = (rect.height() * scale if banded
                       else float(image.height()))
            self._scene.render(
                painter,
                QRectF(0, 0, board_w, board_h),
                rect,
            )
            if banded:
                painter.scale(scale, scale)
                painter.translate(-rect.left(), -rect.top())
                self._draw_export_bands(painter, legend, overlay)
            painter.end()
            image.setDevicePixelRatio(scale)
        return image

    def _render_png_to_path(
        self, path, padding: int = 20, width: int | None = None,
        region=None,
    ) -> None:
        """Render the current diagram to a PNG file at *path*.

        If *width* is given, the output is scaled to that width while
        preserving aspect ratio. Otherwise the natural 2× scale is used.
        """
        from PySide6.QtCore import Qt as _Qt
        image = self._render_png_image(padding=padding, region=region)
        if width is not None and width > 0:
            image = image.scaledToWidth(
                width, _Qt.TransformationMode.SmoothTransformation,
            )
            image.setDevicePixelRatio(1.0)
        image.save(str(path), "PNG")

    def _yank_png_to_clipboard(self):
        """Copy the diagram as PNG to the system clipboard."""
        try:
            image = self._render_png_image()
            QApplication.clipboard().setImage(image)
        except Exception as exc:
            self.toast(f"PNG copy failed: {exc}", "error")
            return
        self.toast("PNG copied to clipboard")

    def _export_svg_file(self):
        """Export the diagram as an SVG file."""
        default_name = ""
        window = self.window()
        if hasattr(window, "_file_path") and window._file_path:
            from pathlib import Path
            default_name = str(Path(window._file_path).with_suffix(".svg"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", default_name,
            "SVG files (*.svg);;All Files (*)",
        )
        if not path:
            return
        try:
            svg_bytes = self._render_svg_bytes()
            with open(path, "wb") as f:
                f.write(svg_bytes.data())
        except Exception as exc:
            self.toast(f"SVG export failed: {exc}", "error")
            return
        self.toast(f"SVG exported · {Path(path).name}")

