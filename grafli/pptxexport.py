"""Export a flow as an editable PowerPoint (.pptx) presentation.

Hybrid by design: the bookmark's framed diagram region is a flattened picture
(rasterized via ``QGraphicsScene.render``, exactly as the PDF exporter does), but
everything textual — title, progress, caption, footer and in-place notes — is a
native, editable PowerPoint textbox. So the deck is directly usable on export yet
fully tweakable: retext, restyle, add or remove slides.

Theme-friendly: text is styled through *theme* colour and font references rather
than hardcoded values, so a global theme/font swap in PowerPoint (Design ▸
Variants, or applying a corporate ``.thmx``) cascades onto it. Two presets:

- ``grafli`` (default) — injects grafli's palette (paper background, ``#D4804E``
  accent) and font into the deck theme, plus the title accent rule and bar
  dividers, so the export looks like grafli out of the box.
- ``blank`` — leaves the neutral default Office theme and drops the decorative
  accent rule/dividers: the cleanest base for merging into a corporate template.

The slide-typing/decision layer is shared with the PDF exporter via
``grafli.slideplan.build_slide_plan`` so both formats stay in lock-step.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Pt
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QFont, QImage, QPainter, QTextDocument

from grafli.constants import FONT_FAMILY, resolve_textsize_px
from grafli.flows import isolate_focus, render_thumbnail_art
from grafli.md_note import is_md_note, md_body
from grafli.slideplan import SlidePlan, build_slide_plan

# PowerPoint 16:9 canvas in points — same fixed geometry as the PDF exporter, so
# the fractional layout math below mirrors pdfexport on a 960x540 pt page.
_PAGE_W = 960.0
_PAGE_H = 540.0
_FOOTER_RESERVE_RATIO = 0.10

# Single-line text sizes in points.
_TITLE_PT = 27.0          # slide title bar
_PROGRESS_PT = 18.0       # "i / n"
_FOOTER_PT = 12.0
_COVER_TITLE_PT = 46.0

# Area-filling text uses a (min, ideal, max) point band and a grow-to-fill rule,
# mirroring the PDF exporter: PowerPoint's autofit only *shrinks* text, never
# grows it, so we compute the fill size ourselves and set it explicitly. Bands
# match grafli.pdfexport so the PPTX text fills the slide exactly like the PDF.
_BODY_BAND = (18.0, 24.0, 30.0)     # text-slide hero
_DESC_BAND = (14.0, 18.0, 22.0)     # cover description
_CAPTION_BAND = (12.0, 15.0, 18.0)
_FILL_FLOOR = 0.45                  # grow until the text fills this much height
_HEADING_SCALE = {1: 1.4, 2: 1.2, 3: 1.05}
# Default PowerPoint textbox internal margins (0.1in x 0.05in) in points — the
# fill fit subtracts these so the chosen size accounts for the inset.
_TF_MARGIN_W = 7.2
_TF_MARGIN_H = 3.6

# An in-place note overlay below this point size is too small to read on a slide;
# we place it anyway (faithful position wins) but flag the slide as overloaded.
_READABLE_MIN_PT = 11.0

# grafli theme palette (mirrors grafli.constants), injected into the deck theme
# so theme-referenced runs/shapes default to the grafli look yet stay swappable.
_GRAFLI_COLORS = {
    "dk1": "2F3437", "lt1": "E8E4DD", "dk2": "4A4A4A", "lt2": "F5F2ED",
    "accent1": "D4804E", "accent2": "004578", "accent3": "0178D4",
    "accent4": "4EBF71", "accent5": "D4BA6A", "accent6": "B0A1CA",
    "hlink": "2B6CB0", "folHlink": "805AD5",
}


@dataclass
class _Theme:
    name: str
    inject_grafli: bool   # rewrite the deck theme with the grafli palette/font
    chrome: bool          # draw the title accent rule + bar dividers


_THEMES = {
    "grafli": _Theme("grafli", inject_grafli=True, chrome=True),
    "blank": _Theme("blank", inject_grafli=False, chrome=False),
}

# Theme-font reference tokens — resolve to the deck's major/minor latin fonts, so
# a font-theme change in PowerPoint cascades onto the text.
_FONT_MAJOR = "+mj-lt"
_FONT_MINOR = "+mn-lt"


def export_flow_to_pptx(view, flow, out_path: str | Path,
                        theme: str = "grafli") -> tuple[int, list]:
    """Render ``flow`` to a .pptx at ``out_path`` using the ``theme`` preset.

    Returns ``(slide_count, overloaded)`` — same contract as the PDF exporter —
    where ``overloaded`` lists ``(step_index, title)`` for slides whose in-place
    notes fall below the readable floor, so the caller can warn the author.
    """
    board = view.board
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    th = _THEMES.get(theme, _THEMES["grafli"])

    prs = Presentation()
    prs.slide_width = Pt(_PAGE_W)
    prs.slide_height = Pt(_PAGE_H)
    if th.inject_grafli:
        _apply_grafli_theme(prs)
    blank = prs.slide_layouts[6]

    footer = board.footer or ""
    plans = build_slide_plan(view, flow)

    # Clear selection and suppress the paper background so rasterized regions are
    # transparent outside their items (they then blend onto the slide), restoring
    # both afterwards — mirrors the PDF exporter.
    sel = list(view._scene.selectedItems())
    for item in sel:
        item.setSelected(False)
    old_bg = view._scene.backgroundBrush()
    view._scene.setBackgroundBrush(Qt.GlobalColor.transparent)

    overloaded = []
    try:
        _build_title_slide(prs.slides.add_slide(blank), view, board, flow, th)
        for plan in plans[1:]:
            slide = prs.slides.add_slide(blank)
            if _build_content_slide(slide, view, plan, footer, th):
                overloaded.append((plan.index, plan.title))
    finally:
        view._scene.setBackgroundBrush(old_bg)
        for item in sel:
            item.setSelected(True)

    prs.save(str(out_path))
    return len(plans), overloaded


# ── theme ───────────────────────────────────────────────────────────────────

def _apply_grafli_theme(prs) -> None:
    """Rewrite the deck theme's colour scheme and latin fonts with grafli's, so
    theme-referenced text/shapes default to the grafli look while a later theme
    swap still overrides them. Best-effort: on any structural surprise we leave
    the default Office theme (text stays theme-referenced, just Office-coloured)."""
    try:
        part = prs.slide_masters[0].part.part_related_by(RT.THEME)
        theme = etree.fromstring(part.blob)
        clr = theme.find(".//" + qn("a:clrScheme"))
        for slot, hexv in _GRAFLI_COLORS.items():
            el = clr.find(qn("a:" + slot))
            if el is None:
                continue
            for child in list(el):
                el.remove(child)
            etree.SubElement(el, qn("a:srgbClr"), val=hexv)
        fonts = theme.find(".//" + qn("a:fontScheme"))
        for which in ("a:majorFont", "a:minorFont"):
            latin = fonts.find(qn(which) + "/" + qn("a:latin"))
            if latin is not None:
                latin.set("typeface", FONT_FAMILY)
        part._blob = etree.tostring(theme, xml_declaration=True,
                                    encoding="UTF-8", standalone=True)
    except Exception:
        pass


# ── slides ──────────────────────────────────────────────────────────────────

def _build_title_slide(slide, view, board, flow, th: _Theme) -> None:
    margin = _PAGE_H * 0.10
    if th.inject_grafli:
        _fill_background(slide, MSO_THEME_COLOR.BACKGROUND_1)
    if board is not None and board.title_bg == "thumbnail-art":
        art = render_thumbnail_art(view, board, flow, 1600,
                                   int(1600 * _PAGE_H / _PAGE_W))
        if art is not None:
            slide.shapes.add_picture(_png_stream(art), 0, 0,
                                     Pt(_PAGE_W), Pt(_PAGE_H))

    y = _PAGE_H * 0.26
    w = _PAGE_W - margin * 2
    box = slide.shapes.add_textbox(Pt(margin), Pt(y), Pt(w), Pt(_PAGE_H * 0.18))
    _fill_text(box.text_frame, flow.label, is_md=False, base_pt=_COVER_TITLE_PT,
               font_ref=_FONT_MAJOR, color=MSO_THEME_COLOR.TEXT_1, bold=True)

    ry = y + _PAGE_H * 0.20
    if th.chrome:
        _accent_rule(slide, margin, ry, w * 0.5, _PAGE_H * 0.006)

    if flow.description:
        drect = (margin, ry + _PAGE_H * 0.03, w, _PAGE_H * 0.55)
        box = slide.shapes.add_textbox(*(Pt(v) for v in drect))
        base = _fit_body_pt(flow.description, True, w - _TF_MARGIN_W * 2,
                            _PAGE_H * 0.55 - _TF_MARGIN_H * 2, _DESC_BAND)
        _fill_text(box.text_frame, flow.description, is_md=True,
                   base_pt=base, font_ref=_FONT_MINOR,
                   color=MSO_THEME_COLOR.TEXT_1, autosize=False)


def _build_content_slide(slide, view, plan: SlidePlan, footer: str,
                         th: _Theme) -> bool:
    margin = _PAGE_H * 0.06
    if th.inject_grafli:
        _fill_background(slide, MSO_THEME_COLOR.BACKGROUND_1)
    if footer:
        _build_footer(slide, footer, th)
    has_title = bool(plan.title)
    has_desc = bool(plan.caption)

    hero_top = margin * 0.5
    hero_bottom = _PAGE_H - margin * 0.5 - _footer_reserve(footer)

    if has_title:
        bar_h = _PAGE_H * 0.12
        tbox = slide.shapes.add_textbox(Pt(margin), Pt(margin * 0.5),
                                        Pt(_PAGE_W - margin * 2), Pt(bar_h))
        _fill_text(tbox.text_frame, plan.title, is_md=False, base_pt=_TITLE_PT,
                   font_ref=_FONT_MAJOR, color=MSO_THEME_COLOR.TEXT_1, bold=True,
                   anchor=MSO_ANCHOR.MIDDLE)
        pbox = slide.shapes.add_textbox(Pt(margin), Pt(margin * 0.5),
                                        Pt(_PAGE_W - margin * 2), Pt(bar_h))
        _fill_text(pbox.text_frame, f"{plan.index + 1} / {plan.total}",
                   is_md=False, base_pt=_PROGRESS_PT, font_ref=_FONT_MINOR,
                   color=MSO_THEME_COLOR.TEXT_1, anchor=MSO_ANCHOR.MIDDLE,
                   align_right=True)
        rule_y = margin * 0.5 + bar_h
        if th.chrome:
            _divider(slide, margin, rule_y, _PAGE_W - margin * 2)
        hero_top = rule_y + margin * 0.5

    hero = QRectF(margin, hero_top, _PAGE_W - margin * 2, hero_bottom - hero_top)

    # Text slide: the single note as native, editable, centred text.
    if plan.kind == "text":
        return _build_text_hero(slide, hero, plan.text_note)

    source = plan.source
    if source is None:
        box = slide.shapes.add_textbox(Pt(hero.left()), Pt(hero.top()),
                                       Pt(hero.width()), Pt(hero.height()))
        _fill_text(box.text_frame, "no anchor to render", is_md=False,
                   base_pt=_DESC_BAND[1], font_ref=_FONT_MINOR,
                   color=MSO_THEME_COLOR.TEXT_1, anchor=MSO_ANCHOR.MIDDLE)
        return False

    # Fit the framed region into the hero, preserving aspect ratio.
    scale = min(hero.width() / source.width(), hero.height() / source.height())
    tw, th_ = source.width() * scale, source.height() * scale
    fitted = QRectF(hero.left() + (hero.width() - tw) / 2,
                    hero.top() + (hero.height() - th_) / 2, tw, th_)

    img = _render_region(view, plan, fitted)
    slide.shapes.add_picture(_png_stream(img), Pt(fitted.left()),
                             Pt(fitted.top()), Pt(fitted.width()),
                             Pt(fitted.height()))

    # Overlay each note as an editable textbox at its mapped position, sized to
    # the same scene scale the diagram was scaled by so it reads in place.
    overloaded = False
    for item in plan.overlays:
        if _build_note_overlay(slide, item, source, fitted, scale):
            overloaded = True

    if has_desc:
        _build_caption(slide, plan.caption, footer)
    return overloaded


def _build_text_hero(slide, hero: QRectF, note) -> bool:
    is_md = is_md_note(note.text)
    body = md_body(note.text) if is_md else note.text
    box = slide.shapes.add_textbox(Pt(hero.left()), Pt(hero.top()),
                                   Pt(hero.width()), Pt(hero.height()))
    base = _fit_body_pt(body, is_md, hero.width() - _TF_MARGIN_W * 2,
                        hero.height() - _TF_MARGIN_H * 2, _BODY_BAND)
    _fill_text(box.text_frame, body, is_md=is_md, base_pt=base,
               font_ref=_FONT_MINOR, color=MSO_THEME_COLOR.TEXT_1,
               anchor=MSO_ANCHOR.MIDDLE, autosize=False)
    return False


def _build_note_overlay(slide, item, source: QRectF, fitted: QRectF,
                        scale: float) -> bool:
    note = item.note
    nr = item.sceneBoundingRect()
    # The PDF clips note overlays to the diagram region, so a note hanging mostly
    # outside the framed area renders as nothing there. A PowerPoint textbox can't
    # be clipped, so a mostly-outside note would otherwise show in full, jammed
    # against a slide edge. Approximate the clip: only place the note when it is
    # substantially inside the framed region.
    inter = nr.intersected(source)
    nr_area = (nr.width() * nr.height()) or 1.0
    if inter.isEmpty() or (inter.width() * inter.height()) < 0.55 * nr_area:
        return False
    is_md = is_md_note(note.text)
    body = md_body(note.text) if is_md else note.text
    mapped = QRectF(fitted.left() + (nr.left() - source.left()) * scale,
                    fitted.top() + (nr.top() - source.top()) * scale,
                    nr.width() * scale, nr.height() * scale)
    # The note's on-canvas font, scaled by the same factor as the diagram, in pt.
    scene_w = nr.width() or 1.0
    note_scale = mapped.width() / scene_w
    base_pt = max(1.0, resolve_textsize_px(note.textsize, "") * note_scale)
    pad = getattr(item, "_PAD", 0) * note_scale
    box = slide.shapes.add_textbox(
        Pt(mapped.left() + pad), Pt(mapped.top() + pad),
        Pt(max(1.0, mapped.width() - pad * 2)),
        Pt(max(1.0, mapped.height() - pad * 2)))
    _fill_text(box.text_frame, body, is_md=is_md, base_pt=base_pt,
               font_ref=_FONT_MINOR, color=MSO_THEME_COLOR.TEXT_1,
               autosize=False)
    return base_pt < _READABLE_MIN_PT


def _build_caption(slide, text: str, footer: str) -> None:
    """A floating dark rounded card with light text at the bottom, over the
    content — matching the on-canvas/PDF playback caption. Card fill and text use
    theme colours (dark text-1 ground, light background-1 text) so they invert
    cleanly under any theme."""
    from pptx.enum.shapes import MSO_SHAPE
    margin = _PAGE_H * 0.06
    pad = _PAGE_H * 0.020
    card_w = min(_PAGE_W * 0.62, _PAGE_W - margin * 2)
    card_h = _PAGE_H * 0.16
    card_x = (_PAGE_W - card_w) / 2
    card_y = _PAGE_H - margin - _footer_reserve(footer) - card_h
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Pt(card_x),
                                  Pt(card_y), Pt(card_w), Pt(card_h))
    card.fill.solid()
    card.fill.fore_color.theme_color = MSO_THEME_COLOR.TEXT_1
    card.line.fill.background()
    card.shadow.inherit = False
    tf = card.text_frame
    tf.margin_left = tf.margin_right = Pt(pad)
    tf.margin_top = tf.margin_bottom = Pt(pad * 0.6)
    base = _fit_body_pt(text, True, card_w - pad * 2, card_h - pad * 1.2,
                        _CAPTION_BAND)
    _fill_text(tf, text, is_md=True, base_pt=base, font_ref=_FONT_MINOR,
               color=MSO_THEME_COLOR.BACKGROUND_1, anchor=MSO_ANCHOR.MIDDLE,
               clear=True, autosize=False)


def _build_footer(slide, footer: str, th: _Theme) -> None:
    """The board-global branding line, muted and left-aligned at the bottom, with
    a thin rule above it (grafli theme only) — mirrors the PDF footer band."""
    margin = _PAGE_H * 0.06
    band_h = _PAGE_H * 0.05
    band_y = _PAGE_H - margin * 0.35 - band_h
    if th.chrome:
        _divider(slide, margin, band_y - _PAGE_H * 0.012, _PAGE_W - margin * 2)
    box = slide.shapes.add_textbox(Pt(margin), Pt(band_y),
                                   Pt(_PAGE_W - margin * 2), Pt(band_h))
    _fill_text(box.text_frame, footer, is_md=True, base_pt=_FOOTER_PT,
               font_ref=_FONT_MINOR, color=MSO_THEME_COLOR.TEXT_1,
               anchor=MSO_ANCHOR.MIDDLE)


def _accent_rule(slide, x: float, y: float, w: float, h: float) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(x), Pt(y),
                                 Pt(w), Pt(max(1.5, h)))
    bar.fill.solid()
    bar.fill.fore_color.theme_color = MSO_THEME_COLOR.ACCENT_1
    bar.line.fill.background()
    bar.shadow.inherit = False


def _divider(slide, x: float, y: float, w: float) -> None:
    """A thin neutral hairline under the title bar."""
    from pptx.enum.shapes import MSO_SHAPE
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(x), Pt(y), Pt(w),
                                  Pt(1.0))
    line.fill.solid()
    line.fill.fore_color.theme_color = MSO_THEME_COLOR.BACKGROUND_2
    line.line.fill.background()
    line.shadow.inherit = False


def _fill_background(slide, theme_color) -> None:
    bg = slide.background
    bg.fill.solid()
    bg.fill.fore_color.theme_color = theme_color


# ── text ─────────────────────────────────────────────────────────────────────

def _fit_body_pt(body: str, is_md: bool, w_pt: float, h_pt: float,
                 band, fill_floor: float = _FILL_FLOOR) -> float:
    """Largest point size from ``band`` (min, ideal, max) at which ``body``,
    reflowed to ``w_pt``, fits ``h_pt`` — grown toward max until it fills
    ``fill_floor`` of the height, shrunk toward min on overflow. Same grow-to-
    fill model as the PDF exporter, so the PPTX text fills like the PDF."""
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    if is_md:
        doc.setMarkdown(body, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    else:
        doc.setPlainText(body)
    f = QFont(FONT_FAMILY)

    def h_at(pt: float) -> float:
        f.setPointSizeF(pt)
        doc.setDefaultFont(f)
        doc.setTextWidth(max(1.0, w_pt))
        return doc.size().height()

    lo, ideal, hi = band
    size = ideal
    if h_at(size) > h_pt:
        while size > lo:
            size -= 1
            if h_at(size) <= h_pt:
                break
    else:
        while size < hi:
            if h_at(size + 1) > h_pt:
                break
            size += 1
            if h_at(size) >= fill_floor * h_pt:
                break
    return float(size)


def _fill_text(tf, body: str, *, is_md: bool, base_pt: float, font_ref: str,
               color, bold: bool = False, anchor=MSO_ANCHOR.TOP,
               align_right: bool = False, autosize: bool = True,
               clear: bool = True) -> None:
    """Render ``body`` into text frame ``tf`` as native runs.

    Markdown (when ``is_md``) is parsed once via ``QTextDocument`` — the same
    engine the canvas and PDF use — and translated into PowerPoint paragraphs and
    runs: bold/italic, inline code (monospace), links (real hyperlinks), headings
    (scaled + bold) and bullet/ordered lists (hand-prefixed markers, like the PDF
    draws). Runs reference the theme font/colour so a theme swap restyles them.
    """
    from pptx.enum.text import PP_ALIGN
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.auto_size = MSO_AUTO_SIZE.NONE if not autosize \
        else MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE

    doc = QTextDocument()
    doc.setDocumentMargin(0)
    f = QFont(FONT_FAMILY)
    f.setPointSizeF(base_pt)
    doc.setDefaultFont(f)
    if is_md:
        doc.setMarkdown(body, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    else:
        doc.setPlainText(body)

    if clear:
        tf.clear()
    first = True
    blk = doc.begin()
    while blk.isValid():
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        if align_right:
            para.alignment = PP_ALIGN.RIGHT
        hl = blk.blockFormat().headingLevel()
        tl = blk.textList()
        if tl is not None:
            from PySide6.QtGui import QTextListFormat
            style = tl.format().style()
            ordered = style in (QTextListFormat.Style.ListDecimal,
                                QTextListFormat.Style.ListLowerAlpha,
                                QTextListFormat.Style.ListUpperAlpha,
                                QTextListFormat.Style.ListLowerRoman,
                                QTextListFormat.Style.ListUpperRoman)
            marker = (tl.itemText(blk) + " ") if ordered else "•  "
            _add_run(para, marker, base_pt, font_ref, color, bold=bold)
        it = blk.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid() and frag.text():
                _add_fragment(para, frag, base_pt, font_ref, color, bold, hl)
            it += 1
        blk = blk.next()


def _add_fragment(para, frag, base_pt: float, font_ref: str, color,
                  base_bold: bool, heading_level: int) -> None:
    cf = frag.charFormat()
    size = base_pt
    is_heading = heading_level > 0
    if is_heading:
        size = base_pt * _HEADING_SCALE.get(heading_level, 1.0)
    bold = base_bold or is_heading or cf.font().bold()
    href = cf.anchorHref() if cf.isAnchor() else None
    _add_run(para, frag.text(), size, font_ref, color, bold=bold,
             italic=cf.fontItalic(), code=cf.fontFixedPitch(), href=href)


def _add_run(para, text: str, size_pt: float, font_ref: str, color, *,
             bold: bool = False, italic: bool = False, code: bool = False,
             href: str | None = None) -> None:
    run = para.add_run()
    run.text = text
    font = run.font
    font.size = Pt(max(1.0, size_pt))
    font.bold = bold
    font.italic = italic
    font.name = "Consolas" if code else font_ref
    if href:
        run.hyperlink.address = href
        font.color.theme_color = MSO_THEME_COLOR.HYPERLINK
    else:
        font.color.theme_color = color


# ── raster ───────────────────────────────────────────────────────────────────

def _render_region(view, plan: SlidePlan, fitted: QRectF) -> QImage:
    """Rasterize the plan's framed scene region to a transparent QImage at the
    fitted size (capped), with overlay notes and container chrome hidden and an
    isolate scope applied — identical to the PDF exporter's diagram raster."""
    source = plan.source
    iw, ih = max(1, round(fitted.width())), max(1, round(fitted.height()))
    cap = 4096
    # Render at ~2x slide points for crisp 16:9 projection without huge files.
    scale = 2
    iw, ih = iw * scale, ih * scale
    if max(iw, ih) > cap:
        k = cap / max(iw, ih)
        iw, ih = max(1, round(iw * k)), max(1, round(ih * k))
    img = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    ip = QPainter(img)
    ip.setRenderHint(QPainter.RenderHint.Antialiasing)
    ip.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    from grafli.pdfexport import _hidden
    with _hidden(list(plan.overlays) + list(plan.chrome_suppress)):
        if plan.isolate:
            with isolate_focus(view, plan.isolate):
                view._scene.render(ip, QRectF(0, 0, iw, ih), source)
        else:
            view._scene.render(ip, QRectF(0, 0, iw, ih), source)
    ip.end()
    return img


def _png_stream(img: QImage) -> io.BytesIO:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return io.BytesIO(bytes(ba))


def _footer_reserve(footer: str) -> float:
    return _PAGE_H * _FOOTER_RESERVE_RATIO if footer else 0.0
