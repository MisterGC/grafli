"""Flow playback engine — drives the canvas through a sequence of bookmarks.

Kept separate from ``view.py`` so the sequencing/animation logic stays
self-contained: the view exposes a couple of small hooks (``goto_rect``,
``_set_flow_overlay``/``_clear_flow_overlay``) and this module owns the
stepping, auto-play timing, and smooth/instant transition state.
"""

from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QImage, QKeyEvent, QPainter, QPixmap

from grafli.constants import SCENE_BG
from grafli.format import DEFAULT_BOOKMARK_PAD, Bookmark, Flow

DEFAULT_DWELL = 4.0   # seconds to rest on a stop during auto-play


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
    for fid in focus_ids:
        item = (
            view._box_items.get(fid)
            or view._note_items.get(fid)
            or view._image_items.get(fid)
        )
        if item is None:
            continue
        r = item.sceneBoundingRect()
        rect = QRectF(r) if rect.isNull() else rect.united(r)
    return rect


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
    img.fill(SCENE_BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    if bookmark.isolate and bookmark.focus:
        with isolate_focus(view, bookmark.focus):
            view._scene.render(p, QRectF(0, 0, iw, ih), rect)
    else:
        view._scene.render(p, QRectF(0, 0, iw, ih), rect)
    p.end()
    return QPixmap.fromImage(img)


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


class FlowPlayer:
    """Steps a flow on the live canvas, manually or auto-played."""

    _MODES = ("paused", "playing", "loop")

    def __init__(self, view, flow: Flow):
        self.view = view
        self.flow = flow
        self.index = 0
        self.smooth = True       # smooth camera vs instant cuts
        self.mode = "paused"     # paused | playing | loop
        self.active = True
        self._timer = QTimer(view)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._auto_advance)

    @property
    def playing(self) -> bool:
        return self.mode != "paused"

    # ── lifecycle ──────────────────────────────────────────────
    def start(self) -> None:
        if not self.flow.steps:
            self.stop()
            return
        self.goto(0)

    def stop(self) -> None:
        self.active = False
        self.mode = "paused"
        self._timer.stop()
        self.view._clear_flow_overlay()
        if self.view._flow_player is self:
            self.view._flow_player = None
        self.view.playback_ended.emit()

    # ── navigation ─────────────────────────────────────────────
    def goto(self, index: int) -> None:
        steps = self.flow.steps
        if not steps:
            self.stop()
            return
        self.index = max(0, min(index, len(steps) - 1))
        step = steps[self.index]
        bookmark = self.view.board.bookmark_by_id(step.ref) if self.view.board else None
        if bookmark is not None:
            rect = bookmark_target_rect(self.view, bookmark)
            if not rect.isNull():
                self.view.goto_rect(rect, animate=self.smooth)
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
        return self.view.board.bookmark_by_id(self.flow.steps[self.index].ref)

    def _refresh_overlay(self, bookmark: Bookmark | None) -> None:
        total = len(self.flow.steps)
        label = bookmark.label if bookmark else "(missing bookmark)"
        description = bookmark.description if bookmark else ""
        self.view._set_flow_overlay({
            "flow": self.flow.label,
            "index": self.index,
            "total": total,
            "label": label,
            "description": description,
            "smooth": self.smooth,
            "mode": self.mode,
        })

    # ── input ──────────────────────────────────────────────────
    def handle_key(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
            self.stop()
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_L, Qt.Key.Key_J):
            self.next()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_H, Qt.Key.Key_K):
            self.prev()
        elif key == Qt.Key.Key_T:
            self.toggle_transition()
        elif key == Qt.Key.Key_P:
            self.cycle_play_mode()
