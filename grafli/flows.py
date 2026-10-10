"""Flow playback engine — drives the canvas through a sequence of bookmarks.

Kept separate from ``view.py`` so the sequencing/animation logic stays
self-contained: the view exposes a couple of small hooks (``goto_rect``,
``_set_flow_overlay``/``_clear_flow_overlay``) and this module owns the
stepping, auto-play timing, and smooth/instant transition state.
"""

from __future__ import annotations

import random
import zlib
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QPainter,
    QPixmap,
)

from grafli import theme
from grafli.format import DEFAULT_BOOKMARK_PAD, Bookmark, Flow, split_step_ref

DEFAULT_DWELL = 4.0   # seconds to rest on a stop during auto-play


def step_detail(flow, step) -> str:
    """A step's effective detail setting: step wins over flow; "" = inherit
    the global GUI state (as does an explicit "auto", which lets a step reset
    a flow-wide default)."""
    value = step.detail or flow.detail
    return "" if value == "auto" else value


def step_focus(flow, step) -> str:
    """A step's effective focus setting: step wins over flow; "" and "none"
    both mean off (an explicit "none" lets a step opt out of a flow-wide
    "complete")."""
    value = step.focus or flow.focus
    return "" if value == "none" else value


def frame_rect(target: QRectF, aspect: float) -> QRectF:
    """The scene rect actually shown when ``target`` is fitted into a surface
    of the given width/height ``aspect`` (viewport or slide hero): the target
    grown symmetrically on its shorter-fitting axis. This is the rect the
    "complete" focus mode tests containment against — an element inside the
    letterboxed margin is fully visible too."""
    if target.isNull() or target.height() <= 0 or aspect <= 0:
        return QRectF(target)
    if target.width() / target.height() < aspect:
        w = target.height() * aspect
        return QRectF(target.center().x() - w / 2, target.y(),
                      w, target.height())
    h = target.width() / aspect
    return QRectF(target.x(), target.center().y() - h / 2,
                  target.width(), h)


@contextmanager
def presentation_detail(view, detail: str):
    """Temporarily force the view's presentation detail ("full"/"summary");
    "" yields unchanged. Restores the previous override on exit — used by the
    exporters and headless render so a step's setting scopes to its slide."""
    if detail not in ("full", "summary"):
        yield
        return
    prev = view._present_detail
    view._set_presentation_detail(detail)
    try:
        yield
    finally:
        view._set_presentation_detail(prev)


@contextmanager
def presentation_focus(view, rect: QRectF | None):
    """Temporarily apply the "complete" focus fade against ``rect`` (None
    yields unchanged), restoring the previous state on exit."""
    if rect is None:
        yield
        return
    prev = view._present_focus_rect
    view._set_presentation_focus(rect)
    try:
        yield
    finally:
        view._set_presentation_focus(prev)


@contextmanager
def isolate_focus(view, focus_ids: list[str]):
    """Temporarily hide everything except the focus items while rendering.

    Used for scoped (``isolate``) bookmarks so thumbnails and the PDF show
    only the narrowed selection: every box/note/image not in ``focus_ids``
    is hidden (along with each box's separate scene-level label), as is every
    arrow that does not run between two focus items. Visibility is restored on
    exit, so the live canvas is unaffected.
    """
    keep = set(focus_ids)
    # An arrow in the focus keeps its two ends, and so the arrow itself.
    if view._board is not None:
        for arrow in focus_arrows(view._board, focus_ids):
            keep.update((arrow.from_id, arrow.to_id))
    hidden = []

    def hide(item):
        if item is not None and item.isVisible():
            item.setVisible(False)
            hidden.append(item)

    for bid, item in view._box_items.items():
        if bid not in keep:
            hide(item)
            hide(item._label)
    for nid, item in view._note_items.items():
        if nid not in keep:
            hide(item)
    for iid, item in view._image_items.items():
        if iid not in keep:
            hide(item)
    for aitem in view._arrow_items:
        arrow = aitem.data(0)
        if arrow is None or arrow.from_id not in keep or arrow.to_id not in keep:
            hide(aitem)
    try:
        yield
    finally:
        for item in hidden:
            item.setVisible(True)


def resolve_focus_rect(view, focus_ids: list[str]) -> QRectF:
    """Union of the scene rects of the given item ids, or a null rect.

    Resolves against the live graphics items so the framing reflects the
    current layout. Ids that no longer exist are skipped.
    """
    rect = QRectF()

    def add(r: QRectF):
        nonlocal rect
        rect = QRectF(r) if rect.isNull() else rect.united(r)

    for fid in focus_ids:
        item = _element_item(view, fid)
        if item is not None:
            add(item.sceneBoundingRect())
            continue
        # An arrow id frames the arrow's two ends and the line drawn between
        # them, which may bow or route outside the ends' union.
        arrow = view._board.arrow_by_id(fid) if view._board else None
        if arrow is None:
            continue
        for end_id in (arrow.from_id, arrow.to_id):
            end = _element_item(view, end_id)
            if end is not None:
                add(end.sceneBoundingRect())
        for gfx in view._arrow_items:
            if gfx.data(0) is arrow and gfx.isVisible():
                add(gfx.sceneBoundingRect())
    return rect


def _element_item(view, element_id: str):
    """The graphics item of a box, note or image id, or None."""
    return (view._box_items.get(element_id)
            or view._note_items.get(element_id)
            or view._image_items.get(element_id))


def focus_arrows(board, focus_ids: list[str]) -> list:
    """The arrows a bookmark's focus names by their ``~id=``. An element id
    wins over an arrow carrying the same id, as it does when framing."""
    arrows = []
    for fid in focus_ids:
        if (board.box_by_id(fid) or board.note_by_id(fid)
                or board.image_by_id(fid)):
            continue
        arrow = board.arrow_by_id(fid)
        if arrow is not None:
            arrows.append(arrow)
    return arrows


def render_bookmark_pixmap(view, bookmark: Bookmark, max_w: int,
                           max_h: int) -> QPixmap | None:
    """A small preview of what a bookmark frames, fit within max_w x max_h.

    Renders the bookmark's target region the same way the PDF export and
    on-canvas view do, so the thumbnail matches the real framing. Returns
    None when the anchor resolves to nothing.
    """
    rect = bookmark_target_rect(view, bookmark)
    if rect.isNull():
        return None
    ar = rect.width() / rect.height()
    if max_w / max_h > ar:
        ih = max_h
        iw = max(1, round(ih * ar))
    else:
        iw = max_w
        ih = max(1, round(iw / ar))
    img = QImage(iw, ih, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(theme.SCENE_BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    with view.miniatures_held():
        if bookmark.isolate and bookmark.focus:
            with isolate_focus(view, bookmark.focus):
                view._scene.render(p, QRectF(0, 0, iw, ih), rect)
        else:
            view._scene.render(p, QRectF(0, 0, iw, ih), rect)
    p.end()
    return QPixmap.fromImage(img)


def render_thumbnail_art(view, board, flow, w: int, h: int) -> QImage | None:
    """Compose the flow's step thumbnails into a faint, deterministic collage —
    the title-cover background shared by the PDF and PPTX exporters.

    Tiles are scattered on a jittered grid at seeded pseudo-random positions,
    rotations and low opacities (the seed comes from the flow, so the same flow
    always yields the same artwork), then a left-weighted paper-coloured wash
    fades the collage back to the page colour on the left so a headline placed
    there stays crisp. Returns a ``w x h`` ARGB image, or None when the flow has
    no renderable steps.
    """
    thumbs = []
    for step in flow.steps:
        bm = board.bookmark_by_id(step.ref)
        if bm is None:
            continue
        pix = render_bookmark_pixmap(view, bm, 720, 405)
        if pix is not None and not pix.isNull():
            thumbs.append(pix)
    if not thumbs:
        return None

    seed = zlib.crc32(("|".join(s.ref for s in flow.steps) + flow.id).encode())
    rng = random.Random(seed)

    art = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    art.fill(Qt.GlobalColor.transparent)
    ap = QPainter(art)
    ap.setRenderHint(QPainter.RenderHint.Antialiasing)
    ap.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    # Even coverage via a jittered grid: one rotated tile per cell, nudged
    # within the cell — scattered look without the random clumps/holes a pure
    # random scatter leaves. Tiles are mostly paper (box fill == slide paper) so
    # only their thin linework shows, hence the relatively high opacity band.
    cols, rows = 6, 4
    cw, chh = w / cols, h / rows
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
            ap.setPen(theme.CONTENT_BORDER_COLOR)
            ap.setBrush(Qt.BrushStyle.NoBrush)
            ap.drawRect(target)
            ap.restore()

    grad = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
    near = QColor(theme.SCENE_BG); near.setAlpha(232)
    mid = QColor(theme.SCENE_BG); mid.setAlpha(140)
    far = QColor(theme.SCENE_BG); far.setAlpha(0)
    grad.setColorAt(0.0, near)
    grad.setColorAt(0.40, mid)
    grad.setColorAt(0.72, far)
    ap.fillRect(QRectF(0, 0, w, h), QBrush(grad))
    ap.end()
    return art


def text_slide_note(view, bookmark: Bookmark):
    """The single focused Note a step should render as native text, or None.

    A step becomes a text slide when the bookmark has no description and its
    focus resolves to exactly one note (no boxes/images) — then its markdown
    is rendered as selectable, clickable PDF text rather than a diagram image.
    """
    if bookmark is None or bookmark.description or len(bookmark.focus) != 1:
        return None
    item = view._note_items.get(bookmark.focus[0])
    return item.note if item is not None else None


def bookmark_target_rect(view, bookmark: Bookmark) -> QRectF:
    """The scene rect a bookmark wants the viewport to frame.

    Logical first: fit the focus items (padded), which stays correct as the
    layout changes. When no focus item resolves, fall back to the stored
    exact view rect (hand-tuned or empty-space framing). Null if neither.
    """
    rect = resolve_focus_rect(view, bookmark.focus)
    if not rect.isNull():
        pad = bookmark.pad or DEFAULT_BOOKMARK_PAD
        return rect.adjusted(-pad, -pad, pad, pad)
    if bookmark.view is not None:
        x, y, w, h = bookmark.view
        return QRectF(x, y, w, h)
    return QRectF()


def tours_through(board, box_id: str) -> list[tuple[Flow, int]]:
    """The flows of *board* that pass through box *box_id*, each with the
    index of its first stop whose focus holds the box or one of its
    containers. Only stops on the board itself count — a stop in another
    board frames that board's elements."""
    seen = set()
    box = board.box_by_id(box_id)
    while box is not None and box.id not in seen:
        seen.add(box.id)
        box = board.box_by_id(box.parent) if box.parent else None
    tours = []
    for flow in board.flows:
        for index, step in enumerate(flow.steps):
            target, bookmark_id = split_step_ref(step.ref)
            bookmark = None if target else board.bookmark_by_id(bookmark_id)
            if bookmark is not None and seen.intersection(bookmark.focus):
                tours.append((flow, index))
                break
    return tours


class FlowPlayer:
    """Steps a flow on the live canvas, manually or auto-played.

    A stop ``<board>#<bookmark>`` lies in another board: the player asks the
    window to show that board (``_tour_goto_board``) before framing it. The
    flow stays owned by ``home``, the board it started on."""

    _MODES = ("paused", "playing", "loop")

    def __init__(self, view, flow: Flow, home: Path | None = None):
        self.view = view
        self.flow = flow
        self.home = home
        self.index = 0
        self.smooth = True       # smooth camera vs instant cuts
        self.mode = "paused"     # paused | playing | loop
        self.active = True
        # True while the player switches boards for a stop, so loading that
        # board does not end the tour.
        self.navigating = False
        self._timer = QTimer(view)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._auto_advance)

    @property
    def playing(self) -> bool:
        return self.mode != "paused"

    # ── lifecycle ──────────────────────────────────────────────
    def start(self, index: int = 0) -> None:
        if not self.flow.steps:
            self.stop()
            return
        self.goto(index)

    def end(self) -> None:
        """Leave the tour on purpose (Esc): stop, and come back to the board
        the flow belongs to when a stop took you elsewhere."""
        home = self.home
        self.stop()
        if home is not None and not self._on_board(home):
            go = getattr(self.view.window(), "_tour_goto_board", None)
            if go is not None:
                go(home)

    def position(self):
        """Where the tour stands, for a board-stack frame to keep."""
        from grafli.buffers import TourPosition
        return TourPosition(home=self.home, flow_id=self.flow.id,
                            index=self.index, mode=self.mode,
                            smooth=self.smooth, flow_label=self.flow.label,
                            total=len(self.flow.steps))

    def stop(self) -> None:
        self.active = False
        self.mode = "paused"
        self._timer.stop()
        self.view._set_presentation_detail(None)
        self.view._set_presentation_focus(None)
        self.view._clear_flow_overlay()
        if self.view._flow_player is self:
            self.view._flow_player = None
        self.view.playback_ended.emit()

    # ── navigation ─────────────────────────────────────────────
    def goto(self, index: int, move: bool = True) -> None:
        """Show stop *index*. With *move* False the camera stays where it is
        — a resumed tour comes back to the view you left it with."""
        steps = self.flow.steps
        if not steps:
            self.stop()
            return
        self.index = max(0, min(index, len(steps) - 1))
        step = steps[self.index]
        bookmark = self._step_bookmark(step, navigate=True)
        if not self.active:
            return
        # Presentation settings resolve per step (step ← flow ← global) and
        # must be in force before the camera moves, so the stop lands on the
        # intended reading. Detail "" clears the override back to the global
        # GUI state; focus fades everything not fully inside the frame the
        # viewport will actually show (the target grown to viewport aspect).
        self.view._set_presentation_detail(step_detail(self.flow, step) or None)
        focus_frame = None
        rect = QRectF()
        if bookmark is not None:
            rect = bookmark_target_rect(self.view, bookmark)
            if not rect.isNull() and move:
                self.view.goto_rect(rect, animate=self.smooth)
        if step_focus(self.flow, step) == "complete" and not rect.isNull():
            vp = self.view.viewport().rect()
            if vp.height() > 0:
                focus_frame = frame_rect(rect, vp.width() / vp.height())
        self.view._set_presentation_focus(focus_frame)
        self._refresh_overlay(bookmark)
        if self.playing:
            self._schedule_next(step)

    def next(self) -> None:
        if self.index < len(self.flow.steps) - 1:
            self.goto(self.index + 1)
        elif self.mode == "loop":
            self.goto(0)
        elif self.mode == "playing":
            # Reached the end (non-loop) — stop advancing but stay open.
            self.mode = "paused"
            self._timer.stop()
            self._refresh_overlay(self._current_bookmark())

    def prev(self) -> None:
        if self.index > 0:
            self.goto(self.index - 1)

    def toggle_transition(self) -> None:
        self.smooth = not self.smooth
        self._refresh_overlay(self._current_bookmark())

    def cycle_play_mode(self) -> None:
        """paused → playing → loop → paused."""
        self.mode = self._MODES[(self._MODES.index(self.mode) + 1) % len(self._MODES)]
        if self.mode == "paused":
            self._timer.stop()
        else:
            self._schedule_next(self.flow.steps[self.index])
        self._refresh_overlay(self._current_bookmark())

    # ── stops in other boards ──────────────────────────────────
    def _step_board(self, target: str) -> Path | None:
        """The board a step's ``<board>`` names ("" = the flow's own), or
        None when it can't be resolved (no home board to resolve from)."""
        if not target:
            return self.home
        if self.home is None:
            return None
        from grafli.resources import board_target_path
        return board_target_path(self.home, target)

    def _on_board(self, path: Path) -> bool:
        current = getattr(self.view.window(), "_file_path", None)
        return current is not None and \
            Path(current).resolve() == path.resolve()

    def _step_bookmark(self, step, navigate: bool = False) -> Bookmark | None:
        """The bookmark *step* frames, on the board that holds it. With
        *navigate* the window is first switched to that board; without, a
        stop on a board not shown resolves to None."""
        target, bookmark_id = split_step_ref(step.ref)
        path = self._step_board(target)
        if target and path is None:
            return None
        if path is not None and not self._on_board(path):
            go = getattr(self.view.window(), "_tour_goto_board", None)
            if not navigate or go is None:
                return None
            self.navigating = True
            try:
                shown = go(path)
            finally:
                self.navigating = False
            if not shown:
                return None
        board = self.view.board
        return board.bookmark_by_id(bookmark_id) if board else None

    # ── auto-play timing ───────────────────────────────────────
    def _schedule_next(self, step) -> None:
        dwell = step.dwell if step.dwell is not None else DEFAULT_DWELL
        self._timer.start(int(dwell * 1000))

    def _auto_advance(self) -> None:
        if self.playing:
            self.next()

    # ── overlay ────────────────────────────────────────────────
    def _current_bookmark(self) -> Bookmark | None:
        if not self.flow.steps or not self.view.board:
            return None
        return self._step_bookmark(self.flow.steps[self.index])

    def _refresh_overlay(self, bookmark: Bookmark | None) -> None:
        total = len(self.flow.steps)
        label = bookmark.label if bookmark else "(missing bookmark)"
        description = bookmark.description if bookmark else ""
        step = self.flow.steps[self.index] if self.flow.steps else None
        self.view._set_flow_overlay({
            "flow": self.flow.label,
            "index": self.index,
            "total": total,
            "label": label,
            "description": description,
            "smooth": self.smooth,
            "mode": self.mode,
            "detail": step_detail(self.flow, step) if step else "",
            "focus": step_focus(self.flow, step) if step else "",
        })

    # ── input ──────────────────────────────────────────────────
    def handle_key(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.end()
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_L, Qt.Key.Key_J):
            self.next()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_H, Qt.Key.Key_K):
            self.prev()
        elif key == Qt.Key.Key_T:
            self.toggle_transition()
        elif key == Qt.Key.Key_P:
            self.cycle_play_mode()
