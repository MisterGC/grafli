"""Export a flow as a slide-style PDF presentation.

One title slide (flow name + optional markdown description, over an optional
faint thumbnail-collage background; no footer — it's a clean cover) followed by
one slide per stop: a title bar (label + progress), the bookmark's framed
diagram region rendered as crisp vectors via ``QGraphicsScene.render``, a
caption band with the description, and the board-global branding footer. Kept
separate from the view so it can run both in-app and headless from the CLI.
"""

from __future__ import annotations

import random
import zlib
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPalette,
    QPdfWriter,
    QPen,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextListFormat,
)

from grafli.constants import FONT_FAMILY, NOTE_PEN_COLOR, SCENE_BG
from grafli.flows import (
    bookmark_target_rect,
    isolate_focus,
    render_bookmark_pixmap,
    text_slide_note,
)
from grafli.md_note import is_md_note, md_body

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

# Branding footer band (board-global). Reserve a slice at the bottom of every
# slide so content never overlaps it; empty footer reserves nothing.
_FOOTER_RESERVE_RATIO = 0.10

# Slide text size bands, in points on the fixed 960x540pt page. The fit picks
# the ideal presentation size, shrinks toward ``min`` only when the text would
# overflow its rect, and grows toward ``max`` (never past) only when the text is
# too sparse to fill the slide comfortably — so short notes read calmly at a
# capped size instead of blowing up, and dense notes never shrink to illegible.
_TITLE_BAND = (28.0, 34.0, 40.0)
_DESC_BAND = (14.0, 18.0, 22.0)
_BODY_BAND = (18.0, 24.0, 30.0)
_CODE_BAND = (13.0, 16.0, 20.0)
_FOOTER_BAND = (10.0, 13.0, 14.0)

# Vertical fill target (fraction of the text rect): below this the slide looks
# too empty, so the fit grows the font toward ``max``. A single-line footer
# passes ``fill_floor=0`` so it sits at its ideal size and never inflates.
_FILL_FLOOR = 0.45


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

    footer = board.footer or ""

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    try:
        # Title slide is the clean cover — no footer band there.
        _draw_title_slide(painter, page, view, board, flow)
        for i, step in enumerate(flow.steps):
            writer.newPage()
            bm = board.bookmark_by_id(step.ref)
            _draw_content_slide(painter, page, view, flow, bm, i,
                                len(flow.steps), footer)
            _draw_footer(painter, page, footer)
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


def _px_per_pt(page: QRectF) -> float:
    """Device-pixels per point on the rendered page (the writer rasterizes the
    fixed 960x540pt page at 300 DPI, so point-based bands convert through this)."""
    return page.height() / _PAGE_PT.height()


def _apply_list_gutters(doc, cursor, markers, size_px: float) -> float:
    """Give each detached list item a font-proportional hanging indent so the
    marker we paint by hand sits in a clear gutter. Returns the gutter width."""
    gutter = size_px * 1.4
    for pos, _marker in markers:
        b = doc.findBlock(pos)
        bf = b.blockFormat()
        bf.setLeftMargin(gutter)
        bf.setTextIndent(0)
        cursor.setPosition(b.position())
        cursor.setBlockFormat(bf)
    return gutter


def _fit_font(doc, font, cursor, markers, rect: QRectF, *, min_px: int,
              ideal_px: int, max_px: int, fill_floor: float) -> tuple[int, bool]:
    """Choose the base font size by the clamp(min, ideal, max) + fill-band rule.

    Start at ``ideal``; if the laid-out text overflows ``rect`` height, shrink
    one px at a time toward ``min``; if instead it fills less than ``fill_floor``
    of the height, grow toward ``max`` but never past the point where it would
    overflow. Returns ``(size_px, overflow)`` where ``overflow`` is True when the
    text still doesn't fit at ``min`` — the caller treats that as an overloaded
    slide.
    """
    def height_at(px: int) -> float:
        font.setPixelSize(px)
        doc.setDefaultFont(font)
        _apply_list_gutters(doc, cursor, markers, px)
        doc.setTextWidth(rect.width())
        return doc.size().height()

    size = max(1, ideal_px)
    h = height_at(size)
    if h > rect.height():
        while size > min_px:
            size -= 1
            if height_at(size) <= rect.height():
                break
    elif fill_floor > 0 and h < fill_floor * rect.height():
        while size < max_px:
            if height_at(size + 1) > rect.height():
                break
            size += 1
            if height_at(size) >= fill_floor * rect.height():
                break
    final_h = height_at(size)
    return size, final_h > rect.height() + 1.0


def _footer_reserve(page: QRectF, footer: str) -> float:
    """Vertical slice reserved at the bottom for the branding footer (0 if none)."""
    return page.height() * _FOOTER_RESERVE_RATIO if footer else 0.0


def _draw_footer(painter, page: QRectF, footer: str) -> None:
    """Draw the board-global branding footer as a muted, left-aligned markdown
    line at the bottom of the slide, with a thin rule above it."""
    if not footer:
        return
    pw, ph = page.width(), page.height()
    margin = ph * 0.06
    band_h = ph * 0.05
    band_rect = QRectF(margin, ph - margin * 0.35 - band_h, pw - margin * 2, band_h)
    ry = band_rect.top() - ph * 0.012
    painter.setPen(QPen(_FRAME, max(1, ph * 0.0015)))
    painter.drawLine(int(margin), int(ry), int(pw - margin), int(ry))
    _draw_markdown(painter, band_rect, footer, markdown=True, band=_FOOTER_BAND,
                   px_per_pt=_px_per_pt(page), color=_MUTED_COLOR, vcenter=True,
                   fill_floor=0.0)


def _draw_title_slide(painter, page: QRectF, view, board, flow) -> None:
    painter.fillRect(page, _SLIDE_BG)
    if board is not None and board.title_bg == "thumbnail-art":
        _draw_thumbnail_art(painter, page, view, board, flow)
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
        # Markdown, just below the headline — so the description can carry
        # links, emphasis and lists, matching how notes render on text slides.
        # This replaces the old auto-agenda of stop titles.
        drect = QRectF(x, ry + ph * 0.03, w, ph * 0.60)
        _draw_markdown(painter, drect, flow.description, markdown=True,
                       band=_DESC_BAND, px_per_pt=_px_per_pt(page),
                       color=_DESC_COLOR, vcenter=False)


def _draw_thumbnail_art(painter, page: QRectF, view, board, flow) -> None:
    """Scatter the flow's step thumbnails as a faint, deterministic collage
    behind the title.

    Tiles are placed at seeded pseudo-random positions, rotations and (low)
    opacities — the seed comes from the flow, so re-exporting the same flow
    always yields the same artwork. A paper-coloured radial wash then fades the
    collage back to the page colour around the title block (left of centre) so
    the headline and description stay crisp on top.
    """
    thumbs = []
    for step in flow.steps:
        bm = board.bookmark_by_id(step.ref)
        if bm is None:
            continue
        pix = render_bookmark_pixmap(view, bm, 480, 270)
        if pix is not None and not pix.isNull():
            thumbs.append(pix)
    if not thumbs:
        return

    seed = zlib.crc32(("|".join(s.ref for s in flow.steps) + flow.id).encode())
    rng = random.Random(seed)

    # Compose the collage on an offscreen image, then drop it onto the page as
    # a single raster. The PDF paint engine ignores per-stop alpha in gradients
    # (the vignette would fill opaque and wipe the tiles) and is unreliable with
    # semi-transparent rotated pixmaps; rendering to a QImage avoids both.
    aw, ah = 1600, int(1600 * page.height() / page.width())
    art = QImage(aw, ah, QImage.Format.Format_ARGB32_Premultiplied)
    art.fill(Qt.GlobalColor.transparent)
    ap = QPainter(art)
    ap.setRenderHint(QPainter.RenderHint.Antialiasing)
    ap.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Even coverage via a jittered grid: one rotated tile per cell, nudged
    # within the cell. This keeps the scattered look but avoids the random
    # clumps/holes that made a sparse "gap" appear mid-page. Tiles are mostly
    # paper (box fill == slide paper) so only their thin linework shows —
    # opacity runs higher than a photo collage would need.
    cols, rows = 6, 4
    cw, chh = aw / cols, ah / rows
    tile_w = cw * 1.35   # overlap neighbours so the field reads as continuous
    k = 0
    for r in range(rows):
        for c in range(cols):
            pix = thumbs[k % len(thumbs)]
            k += 1
            scale = tile_w / pix.width()
            tw, th = tile_w, pix.height() * scale
            cx = (c + 0.5) * cw + rng.uniform(-0.45, 0.45) * cw
            cy = (r + 0.5) * chh + rng.uniform(-0.45, 0.45) * chh
            angle = rng.uniform(-15, 15)
            op = rng.uniform(0.16, 0.30)
            ap.save()
            ap.translate(cx, cy)
            ap.rotate(angle)
            ap.setOpacity(op)
            target = QRectF(-tw / 2, -th / 2, tw, th)
            ap.drawPixmap(target, pix, QRectF(pix.rect()))
            ap.setPen(QPen(_FRAME, 1))
            ap.setBrush(Qt.BrushStyle.NoBrush)
            ap.drawRect(target)
            ap.restore()

    # Left-weighted wash: the left column (title + description) fades to paper
    # so the text stays crisp, while the right keeps the collage — an
    # intentional text-panel look rather than a hole in the middle.
    grad = QLinearGradient(QPointF(0, 0), QPointF(aw, 0))
    near = QColor(_SLIDE_BG); near.setAlpha(232)
    mid = QColor(_SLIDE_BG); mid.setAlpha(140)
    far = QColor(_SLIDE_BG); far.setAlpha(0)
    grad.setColorAt(0.0, near)
    grad.setColorAt(0.40, mid)
    grad.setColorAt(0.72, far)
    ap.fillRect(QRectF(0, 0, aw, ah), QBrush(grad))
    ap.end()

    painter.drawImage(page, art)


def _draw_content_slide(painter, page: QRectF, view, flow, bm, index: int,
                        total: int, footer: str = "") -> None:
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
    hero_bottom = ph - margin * 0.5 - _footer_reserve(page, footer)

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
        band = QRectF(margin, ph - margin - band_h - _footer_reserve(page, footer),
                      pw - margin * 2, band_h)
        _draw_fit_text(painter, band, description, _DESC_COLOR,
                       max_px=int(ph * 0.038), min_px=int(ph * 0.024),
                       flags=int(Qt.TextFlag.TextWordWrap
                                 | Qt.AlignmentFlag.AlignLeft
                                 | Qt.AlignmentFlag.AlignVCenter))
        hero_bottom = band.top() - margin * 0.5

    # ── hero: the bookmark's framed diagram region (or a text slide) ──
    hero = QRectF(margin, hero_top, pw - margin * 2, hero_bottom - hero_top)

    # A single-note step with no description renders its note as native,
    # selectable, clickable text instead of a rasterized diagram.
    note = text_slide_note(view, bm) if bm else None
    if note is not None:
        _draw_text_hero(painter, hero, note, _px_per_pt(page))
        return

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
    if bm.isolate and bm.focus:
        with isolate_focus(view, bm.focus):
            view._scene.render(ip, QRectF(0, 0, iw, ih), source)
    else:
        view._scene.render(ip, QRectF(0, 0, iw, ih), source)
    ip.end()
    # Slide and diagram share the paper background, so the image drops in with
    # no visible seam — no frame needed.
    painter.drawImage(fitted, img)


_UNORDERED = (
    QTextListFormat.Style.ListDisc,
    QTextListFormat.Style.ListCircle,
    QTextListFormat.Style.ListSquare,
)

_ORDERED = (
    QTextListFormat.Style.ListDecimal,
    QTextListFormat.Style.ListLowerAlpha,
    QTextListFormat.Style.ListUpperAlpha,
    QTextListFormat.Style.ListLowerRoman,
    QTextListFormat.Style.ListUpperRoman,
)


def _draw_text_hero(painter, hero: QRectF, note, px_per_pt: float) -> bool:
    """Render a note as native, selectable, clickable PDF text in ``hero``.

    Fills the hero via the shared body band: a short note grows (capped at the
    band max) so it uses the slide rather than floating tiny in the middle, a
    dense note shrinks no further than the band min, and the text is vertically
    centred. Returns ``True`` when the note overflows even at the band minimum.
    Thin wrapper over :func:`_draw_markdown`.
    """
    # Notes opt into markdown via a ``md:`` prefix; otherwise render verbatim.
    is_md = is_md_note(note.text)
    body = md_body(note.text) if is_md else note.text
    return _draw_markdown(painter, hero, body, markdown=is_md, band=_BODY_BAND,
                          px_per_pt=px_per_pt, color=_TITLE_COLOR, vcenter=True)


def _draw_markdown(painter, rect: QRectF, body: str, *, markdown: bool,
                   band, px_per_pt: float, color, vcenter: bool,
                   fill_floor: float = _FILL_FLOOR) -> bool:
    """Render ``body`` as native, selectable, clickable PDF text in ``rect``.

    When ``markdown`` the body is parsed as GitHub-flavoured Markdown, else it
    is laid out verbatim. Text reflows to ``rect`` width — line length adapts to
    the slide, not the source's on-canvas wrap — and the base font is chosen by
    the clamp(min, ideal, max) + fill-band rule from ``band`` (a point triple,
    converted to device pixels via ``px_per_pt``): the ideal presentation size,
    shrunk toward min on overflow, grown toward max only when too sparse. Links
    survive as real PDF link annotations; body text uses ``color`` and links the
    canvas blue. When ``vcenter`` the text is vertically centred in ``rect``,
    otherwise top-aligned. Returns ``True`` when the text overflows even at the
    band minimum (an overloaded slide).

    Unordered-list bullets are drawn by us as vector discs and Qt's own list
    markers suppressed: Qt's auto markers don't render reliably through the PDF
    backend with some fonts (they vanish), but vector discs always do.
    """
    is_md = markdown
    min_px = max(1, round(band[0] * px_per_pt))
    ideal_px = max(1, round(band[1] * px_per_pt))
    max_px = max(1, round(band[2] * px_per_pt))
    ideal_px = min(max(ideal_px, min_px), max_px)

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    font = QFont(FONT_FAMILY)
    font.setPixelSize(max_px)
    doc.setDefaultFont(font)
    if is_md:
        doc.setMarkdown(body, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    else:
        doc.setPlainText(body)

    # Inline code spans bake the import-time default size into an *explicit*
    # font size, so the fit loop below (which only changes the default font)
    # would shrink the prose but leave code rendered at the huge import size.
    # Clear that explicit size so code inherits the default like everything
    # else, keeping only its fixed-pitch family.
    norm = QTextCursor(doc)
    code_ranges = []
    blk = doc.begin()
    while blk.isValid():
        it = blk.begin()
        while not it.atEnd():
            frag = it.fragment()
            cf = frag.charFormat()
            if (frag.isValid() and cf.fontFixedPitch()
                    and cf.hasProperty(QTextFormat.Property.FontPixelSize)):
                code_ranges.append((frag.position(), frag.length(), cf))
            it += 1
        blk = blk.next()
    for pos, length, cf in code_ranges:
        m = QTextCharFormat(cf)
        m.clearProperty(QTextFormat.Property.FontPixelSize)
        m.clearProperty(QTextFormat.Property.FontPointSize)
        norm.setPosition(pos)
        norm.setPosition(pos + length, QTextCursor.MoveMode.KeepAnchor)
        norm.setCharFormat(m)

    # Detach list blocks from Qt's lists and draw the markers ourselves: Qt's
    # auto markers don't render reliably through the PDF backend with some
    # fonts (unordered discs vanish; ordered numbers sit in a fixed 40px
    # hanging indent that falls outside our clip and gets cut off). We give
    # each item a font-proportional hanging indent and paint the marker — a
    # vector disc for bullets, the captured number/letter for ordered items.
    # ``markers`` holds (block_position, marker_text|None); None means a disc.
    markers = []
    blk = doc.begin()
    while blk.isValid():
        tl = blk.textList()
        if tl is not None:
            style = tl.format().style()
            if style in _UNORDERED:
                markers.append((blk.position(), None))
            elif style in _ORDERED:
                # Capture the formatted marker ("1.", "a.", …) before removal,
                # which would renumber the remaining items.
                markers.append((blk.position(), tl.itemText(blk)))
        blk = blk.next()
    cursor = QTextCursor(doc)
    for pos, _marker in markers:
        b = doc.findBlock(pos)
        if b.textList() is not None:
            b.textList().remove(b)

    # Pick the base font by the clamp(min, ideal, max) + fill-band model (the
    # list hanging-indent and markdown headings scale with it, re-applied each
    # trial inside ``_fit_font``). ``overflow`` is True when even ``min`` can't
    # fit, so the caller can flag the slide as overloaded.
    size, overflow = _fit_font(doc, font, cursor, markers, rect,
                               min_px=min_px, ideal_px=ideal_px, max_px=max_px,
                               fill_floor=fill_floor)

    # Colour links the same blue as the canvas. Set it on the anchor char
    # formats explicitly — the PDF backend ignores the paint-context Link
    # palette role, so the markdown default (bright blue) would leak through.
    link_fmt = QTextCharFormat()
    link_fmt.setForeground(NOTE_PEN_COLOR)
    b = doc.begin()
    while b.isValid():
        it = b.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.charFormat().isAnchor():
                cursor.setPosition(frag.position())
                cursor.setPosition(frag.position() + frag.length(),
                                   QTextCursor.MoveMode.KeepAnchor)
                cursor.mergeCharFormat(link_fmt)
            it += 1
        b = b.next()

    lay = doc.documentLayout()
    gutter = size * 1.4
    # Resolve each detached list item's first-line geometry so we can paint its
    # marker (disc or number) in the hanging indent we reserved.
    drawn_markers = []  # (text_left, line_top, line_height, marker_text|None)
    for pos, marker in markers:
        b = doc.findBlock(pos)
        lyt = b.layout()
        if lyt.lineCount() > 0:
            line = lyt.lineAt(0)
            br = lay.blockBoundingRect(b)
            top = br.top() + line.y()
            drawn_markers.append(
                (br.left() + line.x(), top, line.height(), marker))

    dh = min(doc.size().height(), rect.height())
    oy = rect.top() + (max(0.0, (rect.height() - dh) / 2) if vcenter else 0.0)
    painter.save()
    painter.setClipRect(rect)
    painter.translate(rect.left(), oy)
    ctx = QAbstractTextDocumentLayout.PaintContext()
    ctx.palette.setColor(QPalette.ColorRole.Text, color)
    ctx.palette.setColor(QPalette.ColorRole.Link, NOTE_PEN_COLOR)
    ctx.clip = QRectF(0, 0, rect.width(), rect.height())
    lay.draw(painter, ctx)

    r = max(2.0, gutter * 0.16)
    marker_font = QFont(FONT_FAMILY)
    marker_font.setPixelSize(size)
    for text_left, top, line_h, marker in drawn_markers:
        if marker is None:
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                QPointF(text_left - gutter * 0.55, top + line_h / 2), r, r)
        else:
            painter.setFont(marker_font)
            painter.setPen(QPen(color))
            # Right-align the number/letter in the gutter, just left of text.
            box = QRectF(text_left - gutter, top, gutter * 0.82, line_h)
            painter.drawText(box, int(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter), marker)
    painter.restore()
    return overflow


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
