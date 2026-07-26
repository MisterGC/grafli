"""Board export for GrafliView (mixin).

Rendering the current board out of the app: SVG file export and
PNG-to-clipboard, sized from the scene's content bounds and drawn through
the same painter path the canvas uses.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF
from PySide6.QtGui import QBrush, QImage, QPainter
from PySide6.QtSvg import QSvgGenerator
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsItem
from contextlib import contextmanager
from grafli import theme
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

    def _render_svg_bytes(self, padding: int = 20, region=None) -> QByteArray:
        """Render the current diagram (or selection) to SVG bytes."""
        with self._export_scene_context(padding=padding, region=region) as rect:
            buf = QByteArray()
            io = QBuffer(buf)
            io.open(QIODevice.OpenModeFlag.WriteOnly)
            gen = QSvgGenerator()
            gen.setOutputDevice(io)
            gen.setSize(rect.size().toSize())
            gen.setViewBox(rect)
            gen.setTitle("Grafli Diagram")
            painter = QPainter(gen)
            painter.fillRect(rect, QBrush(theme.SCENE_BG))
            self._scene.render(painter, QRectF(), rect)
            painter.end()
            io.close()
        return buf

    def _render_png_image(
        self, scale: int = 2, padding: int = 20, region=None,
    ) -> QImage:
        """Render the current diagram (or selection) to a QImage."""
        with self._export_scene_context(padding=padding, region=region) as rect:
            size = rect.size().toSize()
            image = QImage(
                size.width() * scale,
                size.height() * scale,
                QImage.Format.Format_ARGB32_Premultiplied,
            )
            image.fill(theme.SCENE_BG)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            # Always render against an explicit pixel target. Setting DPR
            # before render() with a null target makes Qt drop most of the
            # scene for certain aspect ratios (wide-and-short pipelines).
            self._scene.render(
                painter,
                QRectF(0, 0, image.width(), image.height()),
                rect,
            )
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

