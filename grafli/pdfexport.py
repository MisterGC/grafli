"""Export a flow as a slide-style PDF presentation.

One title slide (flow name + description + agenda) followed by one slide per
stop: a title bar (label + progress), the bookmark's framed diagram region
rendered as crisp vectors via ``QGraphicsScene.render``, and a caption band
with the description. Kept separate from the view so it can run both in-app
and headless from the CLI.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QPen,
)

from grafli.constants import FONT_FAMILY, SCENE_BG
from grafli.flows import bookmark_target_rect

# Slide palette — the slide IS the canvas: paper background everywhere so the
# diagram region blends in seamlessly (boxes stay border-defined, as on-canvas,
# rather than turning into filled blocks on white).
_SLIDE_BG = SCENE_BG
_TITLE_COLOR = QColor("#2F3437")
_DESC_COLOR = QColor("#4A4A4A")
_MUTED_COLOR = QColor("#8A8A8A")
_ACCENT = QColor("#D4804E")
_FRAME = QColor("#D5D0C8")

# PowerPoint 16:9 canvas, in points (72 dpi) — 13.333" x 7.5".
_PAGE_PT = QSizeF(960, 540)
_RESOLUTION = 300


def export_flow_to_pdf(view, flow, out_path: str | Path) -> int:
    """Render ``flow`` to a PDF at ``out_path``. Returns the slide count.

    ``view`` is a GrafliView whose scene holds the rendered graph (used both
    to resolve bookmark anchors and as the render source).
    """
    board = view.board
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    writer = QPdfWriter(str(out_path))
    writer.setResolution(_RESOLUTION)
    writer.setPageSize(QPageSize(_PAGE_PT, QPageSize.Unit.Point))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Point)
    writer.setTitle(flow.label or "Grafli flow")

    pw, ph = writer.width(), writer.height()
    page = QRectF(0, 0, pw, ph)

    # Clear any live selection / badges so the render is clean, restore after.
    sel = list(view._scene.selectedItems())
    for item in sel:
        item.setSelected(False)
    # Suppress the scene's paper background while rendering so the embedded
    # diagram images are transparent outside their items — they then drop onto
    # the (same-paper) slide with no rectangular seam.
    old_bg = view._scene.backgroundBrush()
    view._scene.setBackgroundBrush(Qt.GlobalColor.transparent)

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        _draw_title_slide(painter, page, board, flow)
        for i, step in enumerate(flow.steps):
            writer.newPage()
            bm = board.bookmark_by_id(step.ref)
            _draw_content_slide(painter, page, view, flow, bm, i, len(flow.steps))
    finally:
        painter.end()
        view._scene.setBackgroundBrush(old_bg)
        for item in sel:
            item.setSelected(True)
    return len(flow.steps) + 1


# ── slides ──────────────────────────────────────────────────────

def _font(px: int, *, bold: bool = False) -> QFont:
    f = QFont(FONT_FAMILY, -1)
    f.setPixelSize(max(1, px))
    f.setBold(bold)
    return f


def _draw_title_slide(painter, page: QRectF, board, flow) -> None:
    painter.fillRect(page, _SLIDE_BG)
    ph = page.height()
    margin = ph * 0.10
    x = margin
    w = page.width() - margin * 2

    y = ph * 0.26
    painter.setFont(_font(int(ph * 0.085), bold=True))
    painter.setPen(QPen(_TITLE_COLOR))
    rect = QRectF(x, y, w, ph * 0.18)
    painter.drawText(rect, int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft
                               | Qt.AlignmentFlag.AlignTop), flow.label)

    # Accent rule under the title.
    painter.setPen(QPen(_ACCENT, max(1, ph * 0.006)))
    ry = y + ph * 0.20
    painter.drawLine(int(x), int(ry), int(x + w * 0.5), int(ry))

    if flow.description:
        painter.setFont(_font(int(ph * 0.035)))
        painter.setPen(QPen(_DESC_COLOR))
        drect = QRectF(x, ry + ph * 0.03, w, ph * 0.18)
        painter.drawText(drect, int(Qt.TextFlag.TextWordWrap
                                    | Qt.AlignmentFlag.AlignLeft
                                    | Qt.AlignmentFlag.AlignTop), flow.description)

    # Agenda — the ordered stop labels.
    labels = []
    for n, step in enumerate(flow.steps, start=1):
        bm = board.bookmark_by_id(step.ref)
        labels.append(f"{n}.  {bm.label if bm else step.ref}")
    if labels:
        painter.setFont(_font(int(ph * 0.030)))
        painter.setPen(QPen(_MUTED_COLOR))
        arect = QRectF(x, ph * 0.66, w, ph * 0.28)
        painter.drawText(arect, int(Qt.TextFlag.TextWordWrap
                                    | Qt.AlignmentFlag.AlignLeft
                                    | Qt.AlignmentFlag.AlignTop),
                         "   ".join(labels) if len(labels) <= 4 else "\n".join(labels))


def _draw_content_slide(painter, page: QRectF, view, flow, bm, index: int,
                        total: int) -> None:
    painter.fillRect(page, _SLIDE_BG)
    pw, ph = page.width(), page.height()
    margin = ph * 0.06

    label = bm.label if bm else "(missing bookmark)"
    description = bm.description if bm else ""
    # A label-less, description-less stop is a "graph-only" slide: the framed
    # diagram fills the page with no title bar or caption — what the graph
    # shows and nothing more. Chrome appears only for the parts that have text.
    has_title = bool(label)
    has_desc = bool(description)

    hero_top = margin * 0.5
    hero_bottom = ph - margin * 0.5

    if has_title:
        bar_h = ph * 0.12
        painter.setFont(_font(int(ph * 0.050), bold=True))
        painter.setPen(QPen(_TITLE_COLOR))
        painter.drawText(
            QRectF(margin, margin * 0.5, pw - margin * 2, bar_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label)
        painter.setFont(_font(int(ph * 0.034)))
        painter.setPen(QPen(_MUTED_COLOR))
        painter.drawText(
            QRectF(margin, margin * 0.5, pw - margin * 2, bar_h),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{index + 1} / {total}")
        rule_y = margin * 0.5 + bar_h
        painter.setPen(QPen(_FRAME, max(1, ph * 0.002)))
        painter.drawLine(int(margin), int(rule_y), int(pw - margin), int(rule_y))
        hero_top = rule_y + margin * 0.5

    if has_desc:
        band_h = ph * 0.22
        band = QRectF(margin, ph - margin - band_h, pw - margin * 2, band_h)
        _draw_fit_text(painter, band, description, _DESC_COLOR,
                       max_px=int(ph * 0.038), min_px=int(ph * 0.024),
                       flags=int(Qt.TextFlag.TextWordWrap
                                 | Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter))
        hero_bottom = band.top() - margin * 0.5

    # ── hero: the bookmark's framed diagram region ──
    hero = QRectF(margin, hero_top, pw - margin * 2, hero_bottom - hero_top)
    source = bookmark_target_rect(view, bm) if bm else QRectF()
    if source.isNull():
        painter.setFont(_font(int(ph * 0.03)))
        painter.setPen(QPen(_MUTED_COLOR))
        painter.drawText(hero, int(Qt.AlignmentFlag.AlignCenter),
                         "no anchor to render")
        return

    scale = min(hero.width() / source.width(), hero.height() / source.height())
    tw, th = source.width() * scale, source.height() * scale
    fitted = QRectF(hero.left() + (hero.width() - tw) / 2,
                    hero.top() + (hero.height() - th) / 2, tw, th)

    # Rasterize the diagram region and embed it. Rendering the scene straight
    # onto a QPdfWriter mis-sizes QGraphicsTextItem box labels (rich text lays
    # out against the device DPI, not the world transform); rendering to a
    # high-res QImage scales everything uniformly and stays crisp at 300 DPI.
    iw, ih = max(1, round(tw)), max(1, round(th))
    cap = 4096
    if max(iw, ih) > cap:
        k = cap / max(iw, ih)
        iw, ih = max(1, round(iw * k)), max(1, round(ih * k))
    img = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    ip = QPainter(img)
    ip.setRenderHint(QPainter.RenderHint.Antialiasing)
    ip.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    view._scene.render(ip, QRectF(0, 0, iw, ih), source)
    ip.end()
    # Slide and diagram share the paper background, so the image drops in with
    # no visible seam — no frame needed.
    painter.drawImage(fitted, img)


def _draw_fit_text(painter, rect: QRectF, text: str, color, *, max_px: int,
                   min_px: int, flags: int) -> None:
    """Draw word-wrapped text, shrinking the font until it fits (down to a
    floor), so a long description never spills out of the band."""
    size = max_px
    font = _font(size)
    while size > min_px:
        font.setPixelSize(size)
        painter.setFont(font)
        br = painter.boundingRect(rect, flags, text)
        if br.height() <= rect.height():
            break
        size -= 1
    font.setPixelSize(size)
    painter.setFont(font)
    painter.setPen(QPen(color))
    painter.drawText(rect, flags, text)
