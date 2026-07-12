"""Export a flow as a slide-style PDF presentation.

One title slide (flow name + optional markdown description, over an optional
faint thumbnail-collage background; no footer — it's a clean cover) followed by
one slide per stop: a title bar (label + progress), the bookmark's framed
diagram region rendered as crisp vectors via ``QGraphicsScene.render``, a
caption band with the description, and the board-global branding footer. Kept
separate from the view so it can run both in-app and headless from the CLI.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFont,
    QImage,
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

from grafli.constants import (
    FONT_FAMILY,
    NOTE_PEN_COLOR,
    SCENE_BG,
    resolve_textsize_px,
)
from grafli.flows import isolate_focus, render_thumbnail_art
from grafli.md_note import md_hard_quote_breaks, note_is_md, note_md_body
# Slide-typing/decision layer is shared with the PPTX exporter. ``_container_box``
# and ``_slide_source`` are re-exported here for the existing pdfexport tests.
from grafli.slideplan import (  # noqa: F401
    SlidePlan,
    _container_box,
    _slide_source,
    build_slide_plan,
    live_overlays,
    playback_text_fit,
    slide_presentation,
)

# Slide palette — the slide IS the canvas: paper background everywhere so the
# diagram region blends in seamlessly (boxes stay border-defined, as on-canvas,
# rather than turning into filled blocks on white).
_SLIDE_BG = SCENE_BG
_TITLE_COLOR = QColor("#2F3437")
_DESC_COLOR = QColor("#4A4A4A")
_MUTED_COLOR = QColor("#8A8A8A")
_ACCENT = QColor("#D4804E")
_FRAME = QColor("#D5D0C8")
# Floating description caption — a dark rounded card matching the on-canvas
# playback caption, drawn over the content so it reserves no layout space.
_CAPTION_BG = QColor("#2F3437")
_CAPTION_TEXT = QColor("#ECECEC")

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
_BODY_BAND = (18.0, 24.0, 30.0)   # text-slide hero (fallback for dense notes)
_CODE_BAND = (13.0, 16.0, 20.0)
_FOOTER_BAND = (10.0, 13.0, 14.0)
_CAPTION_BAND = (12.0, 15.0, 18.0)

# A text slide normally sizes at playback parity (the note zoomed to fill the
# hero, like fitInView frames it in the app) capped here; below the body-band
# minimum it falls back to the band's shrink-to-fit instead.
_BODY_MAX_PT = 60.0

# Vertical fill target (fraction of the text rect): below this the slide looks
# too empty, so the fit grows the font toward ``max``. A single-line footer
# passes ``fill_floor=0`` so it sits at its ideal size and never inflates.
_FILL_FLOOR = 0.45

# In-place note overlay: a note rendered at scene scale below this point size is
# too small to read on a slide. We render it anyway (faithful placement wins)
# but flag the slide as overloaded so the author tightens or splits it.
_READABLE_MIN_PT = 11.0

# The readable floor only applies to notes that carry substance. Shorter
# bodies are annotations riding a picture-like frame (sketchnote sections,
# dense diagrams) — they may render small without flagging (issue #123).
_ANNOTATION_MAX_CHARS = 80


def export_flow_to_pdf(view, flow, out_path: str | Path) -> tuple[int, list]:
    """Render ``flow`` to a PDF at ``out_path``.

    Returns ``(slide_count, overloaded)`` where ``overloaded`` is a list of
    ``(step_index, label)`` for content slides whose text overflows even at the
    band minimum (or whose in-place notes fall below the readable floor) — the
    caller surfaces it so the author can trim or split those steps.

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

    overloaded = []
    painter = QPainter(writer)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    plans = build_slide_plan(view, flow)
    try:
        # Title slide is the clean cover — no footer band there.
        _draw_title_slide(painter, page, view, board, flow)
        for plan in plans[1:]:
            writer.newPage()
            if _draw_content_slide(painter, page, view, plan, footer):
                overloaded.append((plan.index, plan.title))
            _draw_footer(painter, page, footer)
    finally:
        painter.end()
        view._scene.setBackgroundBrush(old_bg)
        for item in sel:
            item.setSelected(True)
    return len(flow.steps) + 1, overloaded


def slide_content_ratio(board) -> float:
    """Width:height ratio of a content slide's usable area (full-bleed, with the
    board-global footer accounted for) — the target a slide-frame container
    should match so its contents fill the exported page without letterboxing.

    The title bar is intentionally not subtracted: one full-bleed preset keeps a
    single reference shape, and a titled slide just letterboxes by the title
    sliver. The footer is board-global, so it shifts the whole board uniformly.
    """
    pw, ph = _PAGE_PT.width(), _PAGE_PT.height()
    margin = ph * 0.06
    footer = ph * _FOOTER_RESERVE_RATIO if (board and board.footer) else 0.0
    return (pw - margin * 2) / (ph - margin - footer)


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
    """Draw the flow's seeded thumbnail collage behind the title.

    The collage (jittered-grid tiles + left-weighted paper wash) is composed by
    the shared :func:`grafli.flows.render_thumbnail_art` so the PDF and PPTX
    covers match; it is built on an offscreen image and dropped onto the page as
    a single raster (the PDF paint engine is unreliable with per-stop gradient
    alpha and semi-transparent rotated pixmaps, which the QImage avoids)."""
    aw, ah = 1600, int(1600 * page.height() / page.width())
    art = render_thumbnail_art(view, board, flow, aw, ah)
    if art is not None:
        painter.drawImage(page, art)


@contextmanager
def _hidden(items):
    """Temporarily hide the given graphics items, restoring on exit. Used to
    keep notes out of the rasterized diagram so they can be redrawn as text."""
    hidden = []
    for it in items:
        if it is not None and it.isVisible():
            it.setVisible(False)
            hidden.append(it)
    try:
        yield
    finally:
        for it in hidden:
            it.setVisible(True)


def _draw_note_overlay(painter, mapped: QRectF, clip: QRectF, item,
                       px_per_pt: float) -> bool:
    """Draw one note as native text at its mapped page position, sized to the
    scene scale already baked into ``mapped`` so it matches the diagram. Returns
    True when the note renders below the readable floor (an overload signal)."""
    note = item.note
    is_md = note_is_md(note)
    body = (md_hard_quote_breaks(note_md_body(note)) if is_md
            else note.text)
    # Scale the note's on-canvas font by the same factor the diagram region was
    # scaled (mapped width / scene width), so the text keeps its relative size.
    scene_w = item.sceneBoundingRect().width() or 1.0
    scale = mapped.width() / scene_w
    fixed_px = max(1, round(resolve_textsize_px(note.textsize, "") * scale))
    # Wrap to the note's own text column, not its bounding rect: a note's bbox is
    # wider than the text (padding/badges), so filling the bbox would let lines
    # run past where they wrap on canvas — e.g. into an adjacent image. Inset by
    # the note's padding and cap the width to its wrap column.
    pad = getattr(item, "_PAD", 0) * scale
    try:
        wrap_w = item._wrap_width_px(item._note_font()) * scale
    except Exception:
        wrap_w = mapped.width() - pad * 2
    text_rect = QRectF(mapped.left() + pad, mapped.top() + pad,
                       min(wrap_w, mapped.width() - pad), mapped.height() - pad * 2)
    _draw_markdown(painter, text_rect, body, markdown=is_md, band=_BODY_BAND,
                   px_per_pt=px_per_pt, color=_TITLE_COLOR, vcenter=False,
                   fixed_px=fixed_px, clip=clip)
    if len(body.strip()) <= _ANNOTATION_MAX_CHARS:
        return False   # a short annotation rides the picture (issue #123)
    return fixed_px < _READABLE_MIN_PT * px_per_pt


def _draw_content_slide(painter, page: QRectF, view, plan: SlidePlan,
                        footer: str = "") -> bool:
    """Draw one content slide from its plan. Returns True when it is overloaded —
    text that overflows even at the band minimum, or an in-place note below the
    readable floor — so the caller can warn the author."""
    painter.fillRect(page, _SLIDE_BG)
    pw, ph = page.width(), page.height()
    margin = ph * 0.06

    # A label-less, description-less stop is a "graph-only" slide: the framed
    # diagram fills the page with no title bar or caption — what the graph
    # shows and nothing more. Chrome appears only for the parts that have text.
    has_title = bool(plan.title)
    has_desc = bool(plan.caption)

    hero_top = margin * 0.5
    hero_bottom = ph - margin * 0.5 - _footer_reserve(page, footer)

    if has_title:
        bar_h = ph * 0.12
        painter.setFont(_font(int(ph * 0.050), bold=True))
        painter.setPen(QPen(_TITLE_COLOR))
        painter.drawText(
            QRectF(margin, margin * 0.5, pw - margin * 2, bar_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            plan.title)
        painter.setFont(_font(int(ph * 0.034)))
        painter.setPen(QPen(_MUTED_COLOR))
        painter.drawText(
            QRectF(margin, margin * 0.5, pw - margin * 2, bar_h),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{plan.index + 1} / {plan.total}")
        rule_y = margin * 0.5 + bar_h
        painter.setPen(QPen(_FRAME, max(1, ph * 0.002)))
        painter.drawLine(int(margin), int(rule_y), int(pw - margin), int(rule_y))
        hero_top = rule_y + margin * 0.5

    # The description is not a reserved band — it floats over the content as a
    # caption card (drawn last), exactly like the on-canvas playback caption, so
    # the diagram keeps full height and the slide matches what you see stepping
    # through the flow. ``has_desc`` only gates whether we draw that card.

    # ── hero: the bookmark's framed diagram region (or a text slide) ──
    hero = QRectF(margin, hero_top, pw - margin * 2, hero_bottom - hero_top)

    # A single-note step with no description renders its note as native,
    # selectable, clickable text instead of a rasterized diagram.
    if plan.kind == "text":
        return _draw_text_hero(painter, hero, plan.text_note, _px_per_pt(page),
                               text_rect=plan.text_rect)

    source = plan.source
    if source is None:
        painter.setFont(_font(int(ph * 0.03)))
        painter.setPen(QPen(_MUTED_COLOR))
        painter.drawText(hero, int(Qt.AlignmentFlag.AlignCenter),
                         "no anchor to render")
        return False

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
    ip.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    # Keep notes out of the raster: they are redrawn below as native text at
    # their mapped scene position, so links stay clickable and text selectable.
    # Suppress the container box's own chrome too — its label is in the title
    # bar. The step's detail/focus settings apply for the raster's duration;
    # notes they hide or fade stay in the raster instead of overlaying as text.
    with slide_presentation(view, plan):
        overlays = live_overlays(view, plan)
        with _hidden(overlays + list(plan.chrome_suppress)):
            if plan.isolate:
                with isolate_focus(view, plan.isolate):
                    view._scene.render(ip, QRectF(0, 0, iw, ih), source)
            else:
                view._scene.render(ip, QRectF(0, 0, iw, ih), source)
    ip.end()
    # Slide and diagram share the paper background, so the image drops in with
    # no visible seam — no frame needed.
    painter.drawImage(fitted, img)

    # Overlay each note as real text at its mapped position (same source->fitted
    # transform as the image), sized to the scene scale so it reads in place.
    overloaded = False
    for item in overlays:
        nr = item.sceneBoundingRect()
        mapped = QRectF(fitted.left() + (nr.left() - source.left()) * scale,
                        fitted.top() + (nr.top() - source.top()) * scale,
                        nr.width() * scale, nr.height() * scale)
        if _draw_note_overlay(painter, mapped, hero, item, _px_per_pt(page)):
            overloaded = True

    if has_desc:
        _draw_caption(painter, page, plan.caption, footer)
    return overloaded


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


def _draw_text_hero(painter, hero: QRectF, note, px_per_pt: float,
                    text_rect: QRectF | None = None) -> bool:
    """Render a note as native, selectable, clickable PDF text in ``hero``.

    Sized at playback parity when ``text_rect`` (the padded scene rect playback
    frames) is given: the note block is fitted into the hero like ``fitInView``
    frames it in the app and its font scaled by the same factor, capped at
    ``_BODY_MAX_PT``. A note too dense for that — or with no rect — falls back
    to the shared body band's shrink-to-fit over the full hero, which is the
    only path that can overflow. Returns ``True`` on such an overflow.
    Thin wrapper over :func:`_draw_markdown`.
    """
    # Notes opt into markdown via a ``md:`` prefix; otherwise render verbatim.
    is_md = note_is_md(note)
    body = (md_hard_quote_breaks(note_md_body(note)) if is_md
            else note.text)
    fit = playback_text_fit(resolve_textsize_px(note.textsize, ""), text_rect,
                            hero, _BODY_BAND[0] * px_per_pt,
                            _BODY_MAX_PT * px_per_pt)
    if fit is not None:
        size_px, rect = fit
        return _draw_markdown(painter, rect, body, markdown=is_md,
                              band=_BODY_BAND, px_per_pt=px_per_pt,
                              color=_TITLE_COLOR, vcenter=True,
                              fixed_px=max(1, round(size_px)))
    return _draw_markdown(painter, hero, body, markdown=is_md, band=_BODY_BAND,
                          px_per_pt=px_per_pt, color=_TITLE_COLOR, vcenter=True)


def render_text_slide_pixmap(note, w: int, h: int, text_rect=None):
    """A 16:9 preview of a text slide: the note's text sized to fill the frame,
    exactly as :func:`_draw_text_hero` renders it on export (pass ``text_rect``,
    the padded scene rect playback frames, for playback-parity sizing). Used by
    the Flows editor so a text step's thumbnail shows how the text fills the
    slide rather than the note floating tiny at its on-canvas scale."""
    from PySide6.QtGui import QPixmap
    w, h = max(1, int(w)), max(1, int(h))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(_SLIDE_BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    page = QRectF(0, 0, w, h)
    margin = h * 0.08
    hero = QRectF(margin, margin, w - margin * 2, h - margin * 2)
    _draw_text_hero(p, hero, note, _px_per_pt(page), text_rect=text_rect)
    p.end()
    return QPixmap.fromImage(img)


def _draw_markdown(painter, rect: QRectF, body: str, *, markdown: bool,
                   band, px_per_pt: float, color, vcenter: bool,
                   fill_floor: float = _FILL_FLOOR, fixed_px: int | None = None,
                   clip: QRectF | None = None) -> bool:
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
    band minimum (an overloaded slide). ``fixed_px`` forces an exact size and
    skips the fit (for scene-scale in-place overlays); ``clip`` overrides the
    paint clip so such an overlay can extend past its own mapped rect.

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

    # ``fixed_px`` skips the fit and lays the text at an exact size — used for
    # in-place note overlays, which size to the on-canvas scene scale so the
    # note reads as it does on the diagram, not reflowed to fill a band. Else
    # pick the base font by the clamp(min, ideal, max) + fill-band model (the
    # list hanging-indent and markdown headings scale with it, re-applied each
    # trial inside ``_fit_font``); ``overflow`` is True when even ``min`` can't
    # fit, so the caller can flag the slide as overloaded.
    if fixed_px is not None:
        size = max(1, fixed_px)
        font.setPixelSize(size)
        doc.setDefaultFont(font)
        _apply_list_gutters(doc, cursor, markers, size)
        doc.setTextWidth(rect.width())
        overflow = False
    else:
        size, overflow = _fit_font(doc, font, cursor, markers, rect,
                                   min_px=min_px, ideal_px=ideal_px,
                                   max_px=max_px, fill_floor=fill_floor)

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
    painter.setClipRect(clip if clip is not None else rect)
    painter.translate(rect.left(), oy)
    ctx = QAbstractTextDocumentLayout.PaintContext()
    ctx.palette.setColor(QPalette.ColorRole.Text, color)
    ctx.palette.setColor(QPalette.ColorRole.Link, NOTE_PEN_COLOR)
    # ``clip`` (when given, e.g. the whole hero) lets an in-place note draw past
    # its own mapped rect without being cut, in document coordinates relative to
    # the translated origin; else keep the original rect-tight clip.
    if clip is not None:
        ctx.clip = QRectF(clip.left() - rect.left(), clip.top() - oy,
                          clip.width(), clip.height())
    else:
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


def _markdown_height(body: str, markdown: bool, width: float, px: int) -> float:
    """Laid-out height of ``body`` at font ``px`` wrapped to ``width`` — used to
    size the caption card to its text before drawing the card behind it."""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    f = QFont(FONT_FAMILY)
    f.setPixelSize(max(1, px))
    doc.setDefaultFont(f)
    if markdown:
        doc.setMarkdown(body, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    else:
        doc.setPlainText(body)
    doc.setTextWidth(width)
    return doc.size().height()


def _draw_caption(painter, page: QRectF, text: str, footer: str) -> None:
    """Draw the step description as a floating dark caption card at the bottom,
    over the content (above the footer). Markdown, with clickable links; matches
    the on-canvas playback caption and reserves no layout space."""
    pw, ph = page.width(), page.height()
    margin = ph * 0.06
    ppp = _px_per_pt(page)
    pad = ph * 0.020
    card_w = min(pw * 0.62, pw - margin * 2)
    text_w = card_w - pad * 2
    ideal_px = max(1, round(_CAPTION_BAND[1] * ppp))
    text_h = min(_markdown_height(text, True, text_w, ideal_px), ph * 0.26)
    card_h = text_h + pad * 2
    card_x = (pw - card_w) / 2
    card_y = ph - margin - _footer_reserve(page, footer) - card_h
    card = QRectF(card_x, card_y, card_w, card_h)

    bg = QColor(_CAPTION_BG)
    bg.setAlphaF(0.94)
    painter.setPen(QPen(QColor(255, 255, 255, 36), max(1.0, ph * 0.0012)))
    painter.setBrush(QBrush(bg))
    radius = ph * 0.014
    painter.drawRoundedRect(card, radius, radius)

    text_rect = QRectF(card_x + pad, card_y + pad, text_w, text_h)
    _draw_markdown(painter, text_rect, text, markdown=True, band=_CAPTION_BAND,
                   px_per_pt=ppp, color=_CAPTION_TEXT, vcenter=True)
