"""Format-agnostic slide plan for a flow.

The flow → slide exporters (PDF, PPTX) share one decision layer: given a flow,
work out *what* each slide contains — its kind (title / text / diagram), title,
caption, the scene rect to frame, which notes overlay as live text, and which
items to suppress while rasterizing the diagram. Each exporter then *renders*
that plan its own way (QPainter onto a QPdfWriter, or python-pptx shapes), so
the slide-typing logic lives here once instead of being duplicated per format.

The plan references live graphics items (note/box items, scene rects) because
both renderers rasterize the scene anyway and need that handle; what is factored
out is the decision logic, not the Qt dependency.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF

from grafli.flows import (bookmark_target_rect, presentation_detail,
                          presentation_focus, step_detail, step_focus,
                          text_slide_note)


@dataclass
class SlidePlan:
    """One slide's content, independent of output format.

    ``kind`` selects the rendering path:
    - ``"title"``  — the cover: ``flow_label`` + ``flow_description`` over the
      optional thumbnail-art background (``thumbnail_art``).
    - ``"text"``   — a single focused note rendered as native text
      (``text_note``); no diagram.
    - ``"diagram"``— the bookmark's framed region (``source``) rasterized, with
      ``overlays`` redrawn as live text and ``chrome_suppress`` hidden during the
      raster. A null/None ``source`` means "no anchor to render".
    """
    kind: str
    # cover
    flow_label: str = ""
    flow_description: str = ""
    thumbnail_art: bool = False
    # content (text + diagram)
    title: str = ""
    caption: str = ""
    index: int = 0
    total: int = 0
    # text slide
    text_note: object | None = None
    text_rect: QRectF | None = None   # padded scene rect playback frames
    # diagram slide
    source: QRectF | None = None
    isolate: list[str] | None = None
    overlays: list = field(default_factory=list)        # note items → live text
    chrome_suppress: list = field(default_factory=list)  # items hidden in raster
    # Effective per-step presentation settings (step ← flow, "" = inherit /
    # off) — applied around the raster via slide_presentation().
    detail: str = ""
    focus: str = ""


def build_slide_plan(view, flow) -> list[SlidePlan]:
    """The ordered slide plan for ``flow``: a title cover followed by one content
    slide per step. ``view`` is a GrafliView whose scene holds the rendered graph
    (used to resolve anchors and as the eventual render source)."""
    board = view.board
    plans: list[SlidePlan] = [SlidePlan(
        kind="title",
        flow_label=flow.label,
        flow_description=flow.description,
        thumbnail_art=(board is not None and board.title_bg == "thumbnail-art"),
    )]
    total = len(flow.steps)
    for i, step in enumerate(flow.steps):
        bm = board.bookmark_by_id(step.ref)
        plan = _content_plan(view, bm, i, total)
        plan.detail = step_detail(flow, step)
        plan.focus = step_focus(flow, step)
        plans.append(plan)
    return plans


@contextmanager
def slide_presentation(view, plan: SlidePlan):
    """Apply a plan's detail/focus settings for the duration of its raster.

    The focus frame is the plan's own source rect: the exported image shows
    exactly that region, so "completely inside the frame" and "completely on
    the slide" coincide."""
    with presentation_detail(view, plan.detail):
        rect = (plan.source if plan.focus == "complete"
                and plan.source is not None else None)
        with presentation_focus(view, rect):
            yield


def live_overlays(view, plan: SlidePlan) -> list:
    """The plan's overlay notes that should still be drawn as native text
    under its presentation settings — call inside :func:`slide_presentation`.

    A note hidden by a "summary" collapse is subsumed by its container's tile;
    a note faded by "complete" focus must keep its faded raster look instead
    of being re-drawn as full-opacity text."""
    items = [it for it in plan.overlays if it.isVisible()]
    if plan.focus == "complete" and plan.source is not None:
        contained = view._presentation_focus_contained()
        items = [it for it in items if it.note.id in contained]
    return items


def _content_plan(view, bm, index: int, total: int) -> SlidePlan:
    """Decide one content slide's kind and contents from its bookmark."""
    board = view.board
    # Title ladder: a manual bookmark label wins; else, when the step frames a
    # single subtree, the container box's label titles the slide; else no title.
    container = _container_box(board, bm) if bm else None
    title = (bm.label if bm else "(missing bookmark)") \
        or (container.label if container else "")
    caption = bm.description if bm else ""

    # A single-note, description-less step renders its note as native text.
    note = text_slide_note(view, bm) if bm else None
    if note is not None:
        return SlidePlan(kind="text", title=title, caption=caption,
                         index=index, total=total, text_note=note,
                         text_rect=bookmark_target_rect(view, bm))

    source = _slide_source(view, bm, container)
    overlays = _overlay_notes(view, bm, source) if not source.isNull() else []
    chrome: list = []
    if container is not None:
        cbox = view._box_items.get(container.id)
        if cbox is not None:
            chrome.append(cbox)
            chrome.append(cbox._label)
    isolate = list(bm.focus) if (bm and bm.isolate and bm.focus) else None
    return SlidePlan(kind="diagram", title=title, caption=caption,
                     index=index, total=total,
                     source=source if not source.isNull() else None,
                     isolate=isolate, overlays=overlays, chrome_suppress=chrome)


def playback_text_fit(textsize: float, text_rect: QRectF | None,
                      hero: QRectF, lo: float, hi: float):
    """Playback-parity sizing for a text slide, shared by the PDF and PPTX
    exporters.

    In the app a text step is framed with ``fitInView``: the note block is
    zoomed to fill the viewport, so its apparent text size is its on-canvas
    ``textsize`` times that zoom. Mirror it — fit ``text_rect`` (the padded
    scene rect playback frames) into ``hero`` aspect-preserving and scale
    ``textsize`` along, exactly like the diagram raster is fitted.

    ``hero``, ``lo`` and ``hi`` are in the exporter's own units (points for
    PPTX, device pixels for PDF); the returned ``(size, fitted_rect)`` is in
    the same units. ``size`` is capped at ``hi`` so a two-word note stays
    tasteful rather than billboard-sized. Returns ``None`` when parity can't
    be computed (no rect) or would land below ``lo`` — a note too dense to be
    readable at its framed scale — so the caller falls back to its
    shrink-to-fit band, which guarantees a fit and flags overflow."""
    if text_rect is None or text_rect.isEmpty():
        return None
    scale = min(hero.width() / text_rect.width(),
                hero.height() / text_rect.height())
    size = textsize * scale
    if size < lo:
        return None
    w, h = text_rect.width() * scale, text_rect.height() * scale
    fitted = QRectF(hero.left() + (hero.width() - w) / 2,
                    hero.top() + (hero.height() - h) / 2, w, h)
    return min(size, hi), fitted


# ── slide-typing helpers (moved from pdfexport; re-exported there) ──────────

def _parent_of(board, item_id: str) -> str:
    """Parent id of any box/note/image, or '' when top-level / unknown."""
    for resolve in (board.box_by_id, board.note_by_id, board.image_by_id):
        item = resolve(item_id)
        if item is not None:
            return item.parent
    return ""


def _container_box(board, bm):
    """The focus box that is an ancestor of every other focus item — the slide's
    container. Returns its Box, or None when the step is not a single subtree.

    A container slide promotes this box's label to the title bar and suppresses
    its own chrome (border/fill/label) from the diagram: the box *is* the slide
    frame, so drawing it again inside the hero would just double the label."""
    if bm is None or len(bm.focus) < 2:
        return None

    def is_ancestor(anc: str, item_id: str) -> bool:
        cur, seen = _parent_of(board, item_id), set()
        while cur and cur not in seen:
            if cur == anc:
                return True
            seen.add(cur)
            cur = _parent_of(board, cur)
        return False

    others = set(bm.focus)
    for cid in bm.focus:
        box = board.box_by_id(cid)
        if box is None:
            continue
        rest = others - {cid}
        if rest and all(is_ancestor(cid, o) for o in rest):
            return box
    return None


def _slide_source(view, bm, container) -> QRectF:
    """The scene rect a content slide should frame.

    A container slide frames the union of the container's *contents* (its focus
    descendants), not the container box: the box is the selector and title, so
    its border, padding and vacated label band must not waste slide space — the
    content fills the page like it sits inside the container on the canvas. A
    small uniform pad keeps it off the edges. Every other step uses the padded
    bookmark framing that gives a region of a larger diagram some breathing room.
    """
    if container is not None:
        rects = []
        for fid in bm.focus:
            if fid == container.id:
                continue
            item = (view._box_items.get(fid) or view._note_items.get(fid)
                    or view._image_items.get(fid))
            if item is not None:
                rects.append(item.sceneBoundingRect())
        if rects:
            union = rects[0]
            for r in rects[1:]:
                union = union.united(r)
            pad = max(union.width(), union.height()) * 0.04
            return union.adjusted(-pad, -pad, pad, pad)
        citem = view._box_items.get(container.id)
        if citem is not None:
            return citem.sceneBoundingRect()
    return bookmark_target_rect(view, bm) if bm else QRectF()


def _overlay_notes(view, bm, source: QRectF):
    """The note items rendered inside ``source`` that should be drawn as real
    text instead of rasterized. For a scoped (isolate) bookmark only its focus
    notes count; otherwise every visible note intersecting the framed region."""
    items = view._note_items
    if bm is not None and bm.isolate and bm.focus:
        ids = [nid for nid in bm.focus if nid in items]
    else:
        ids = [nid for nid, it in items.items()
               if it.isVisible() and it.sceneBoundingRect().intersects(source)]
    return [items[nid] for nid in ids]
