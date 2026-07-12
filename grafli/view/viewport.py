"""Viewport control for GrafliView (mixin).

How the camera behaves: content-aware zoom bounds with bounce feedback at
the limits, wheel / trackpad-gesture / keyboard zoom actions, the animated
zoom used by navigation and flows, and the view toggles (grid, notes, ...).
The Qt event overrides that call into these helpers stay on the host
GrafliView.
"""

from __future__ import annotations

import math
import time
from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPointF,
    QRectF,
    QTimeLine,
    Qt,
)
from PySide6.QtGui import QCursor, QTransform
from PySide6.QtWidgets import QGraphicsView
from grafli.lod import CHILD_COLLAPSE_PX


class ViewportMixin:
    # ── View toggles ───────────────────────────────────────

    def _toggle_arrows_dimmed(self):
        """Toggle low-opacity dim on all arrows."""
        self._arrows_dimmed = not self._arrows_dimmed
        if not self._focus_active and not self._complexity_active:
            opacity = 0.08 if self._arrows_dimmed else 1.0
            for gfx in self._arrow_items:
                gfx.setOpacity(opacity)
            self.viewport().update()

    def _toggle_complexity(self):
        """Toggle the complexity-analysis heatmap overlay."""
        if self._complexity_active:
            self._clear_complexity_heatmap()
        else:
            if self._focus_active:
                self._clear_focus_filter()
            self._complexity_active = True
            self._apply_complexity_heatmap()

    def _toggle_notes_hidden(self):
        """Toggle low-opacity dim on all notes and their connector arrows.

        Uses the same 0.08 dim level as the arrow-dim toggle (``,``) so
        the diagram reads as the bare graph while keeping notes faintly
        visible (and still selectable for editing).
        """
        self._notes_hidden = not self._notes_hidden
        self._apply_notes_hidden()

    def _apply_notes_hidden(self):
        from grafli.format import Arrow as _Arrow
        opacity = 0.08 if self._notes_hidden else 1.0
        for note_item in self._note_items.values():
            note_item.setOpacity(opacity)
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if not isinstance(arrow, _Arrow):
                continue
            touches_note = (
                arrow.from_id in self._note_items
                or arrow.to_id in self._note_items
            )
            if touches_note:
                gfx.setOpacity(opacity)

    # ── Pan / Zoom ──

    # Zoom-out is content-aware (stop before the board becomes a speck);
    # zoom-in is a fixed cap (so a few glyphs can't fill the screen).
    MIN_ZOOM_ABS = 0.02
    MAX_ZOOM = 5.0
    # Muted grey for a LoD aggregate whose members don't share a colour.
    LOD_NEUTRAL = "#8E9299"

    def _fit_zoom(self):
        """Scale at which the whole board (plus margin) just fits the viewport,
        or None when there's nothing to fit."""
        rect = self._scene.itemsBoundingRect()
        if rect.isNull():
            return None
        rect = rect.adjusted(-40, -40, 40, 40)
        vp = self.viewport().rect()
        if rect.width() <= 0 or rect.height() <= 0 or vp.width() <= 0 or vp.height() <= 0:
            return None
        return min(vp.width() / rect.width(), vp.height() / rect.height())

    def _zoom_bounds(self) -> tuple[float, float]:
        """(min, max) zoom. Min lets you zoom out until the board fills ~30%
        of the viewport — never forced above 100% — so small boards can't
        shrink to a dot; max is the fixed in-cap.

        When LoD is on, the floor is dropped just past the coarsest top-level
        tile's collapse point if that sits below the 30%-fit floor — otherwise
        you could never zoom out far enough to reach the top-level aggregation.
        The raw board gets small there, but the tiles are counter-scaled, so
        their headlines stay readable: that small overview is what they're for.
        """
        fit = self._fit_zoom()
        lo = (self.MIN_ZOOM_ABS if fit is None
              else min(1.0, max(self.MIN_ZOOM_ABS, fit * 0.3)))
        if self._lod_enabled and self._lod is not None:
            ext = self._lod.coarsest_collapse_extent()
            if ext > 0:
                reach = CHILD_COLLAPSE_PX / ext * 0.9
                lo = max(self.MIN_ZOOM_ABS, min(lo, reach))
        return lo, self.MAX_ZOOM

    def _clamp_zoom_factor(self, factor: float) -> tuple[float, bool]:
        """Adjust a relative zoom ``factor`` so the resulting scale stays in
        bounds. Returns (effective_factor, hit_limit)."""
        cur = self.transform().m11()
        lo, hi = self._zoom_bounds()
        target = max(lo, min(hi, cur * factor))
        eff = target / cur if cur else 1.0
        hit = abs(eff - 1.0) < 1e-9 and abs(factor - 1.0) > 1e-9
        return eff, hit

    def _zoom_limit_feedback(self, zooming_in: bool):
        """A rubber-band bounce plus a throttled toast when a zoom is blocked
        at the min/max bound."""
        self._start_zoom_bounce(zooming_in)
        now = time.monotonic()
        if now - self._zoom_limit_toast_at > 1.2:
            self._zoom_limit_toast_at = now
            self.toast("Max zoom" if zooming_in
                       else "Min zoom — ⇧Z to fit", kind="info")

    def _start_zoom_bounce(self, zooming_in: bool):
        """Spring the canvas ~4% past the limit and settle back. Input is
        briefly consumed (see wheelEvent / _zoom_keyboard) so it can't fight
        a new zoom mid-bounce."""
        if self._bounce_active:
            return
        self._bounce_active = True
        self._bounce_dir = 1.0 if zooming_in else -1.0
        self._bounce_last_s = 1.0
        self._bounce_base = QTransform(self.transform())
        self._bounce_prev_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        tl = QTimeLine(170, self)
        tl.setUpdateInterval(16)
        tl.valueChanged.connect(self._on_bounce_step)
        tl.finished.connect(self._on_bounce_finished)
        self._bounce_timeline = tl
        tl.start()

    def _on_bounce_step(self, v: float):
        s = 1.0 + self._bounce_dir * 0.04 * math.sin(math.pi * v)
        ratio = s / self._bounce_last_s
        self._bounce_last_s = s
        self.scale(ratio, ratio)

    def _on_bounce_finished(self):
        # Restore the exact pre-bounce transform (no float drift).
        self.setTransform(self._bounce_base)
        self.setTransformationAnchor(self._bounce_prev_anchor)
        self._bounce_timeline = None
        self._bounce_active = False
        self._update_status_zoom()

    def _wheel_action(self, pixel: QPoint, angle: QPoint, mods,
                      is_trackpad: bool = False):
        """Decide what a wheel/scroll event does.

        A **trackpad** two-finger scroll (no zoom modifier) **pans**; anything
        else — a mouse wheel, including a high-resolution / Bluetooth wheel that
        also emits pixel deltas, or any scroll with Ctrl/⌘ held — **zooms**.

        The trackpad vs. mouse distinction comes from the event source/phase
        (passed in as ``is_trackpad``), *not* from whether ``pixelDelta`` is
        present: high-res mice emit pixel deltas too, so keying on that routed
        their wheel to pan by mistake.
        Returns ``("pan", dx, dy)``, ``("zoom", factor)``, or ``None``.
        """
        ctrl = bool(mods & (Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.MetaModifier))
        has_pixel = not pixel.isNull()
        if is_trackpad and has_pixel and not ctrl:
            return ("pan", pixel.x(), pixel.y())
        d = pixel.y() if has_pixel else angle.y()
        if d == 0:
            return None
        # Proportional zoom: one wheel notch (120 units) is a 1.15× step, and
        # partial / multi-notch / pixel-precise deltas scale smoothly with it
        # instead of jumping a fixed step.
        return ("zoom", 1.15 ** (d / 120.0))

    def _handle_native_gesture(self, e) -> bool:
        if e.gestureType() != Qt.NativeGestureType.ZoomNativeGesture:
            return False
        if self._bounce_active:
            return True
        factor = 1.0 + e.value()
        if abs(factor - 1.0) < 1e-6:
            return True
        eff, hit = self._clamp_zoom_factor(factor)
        if hit:
            self._zoom_limit_feedback(factor > 1.0)
            return True
        self.scale(eff, eff)   # under-cursor anchor (global)
        self._update_status_zoom()
        return True

    def _zoom_keyboard(self, factor: float):
        """Zoom for the +/- shortcuts, anchored on what the user cares about.

        With a selection, the combined bounding-rect center of the selected
        items is held fixed on screen; otherwise the viewport center is. Either
        way the focal point stays put while the rest of the canvas scales around
        it. (Wheel zoom keeps its own under-the-mouse anchor.)
        """
        if self._bounce_active:
            return
        eff, hit = self._clamp_zoom_factor(factor)
        if hit:
            self._zoom_limit_feedback(factor > 1.0)
            return
        factor = eff
        items = self._scene.selectedItems()
        if items:
            rect = items[0].sceneBoundingRect()
            for it in items[1:]:
                rect = rect.united(it.sceneBoundingRect())
            anchor_scene = rect.center()
        else:
            anchor_scene = self.mapToScene(self.viewport().rect().center())
        prev_anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        before = self.mapFromScene(anchor_scene)
        self.scale(factor, factor)
        delta = self.mapFromScene(anchor_scene) - before
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + delta.x())
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + delta.y())
        self.setTransformationAnchor(prev_anchor)
        self._update_status_zoom()

    # ── Animated zoom ──

    def _animate_to_rect(self, target_rect: QRectF):
        """Smoothly animate zoom and pan to show target_rect."""
        if self._zoom_timeline is not None:
            self._zoom_timeline.stop()
            self._zoom_timeline = None

        vp = self.viewport().rect()
        start_zoom = self.transform().m11()
        start_center = self.mapToScene(vp.center())

        target_zoom = min(vp.width() / max(target_rect.width(), 1),
                          vp.height() / max(target_rect.height(), 1))
        # Clamp to reasonable bounds (same in-cap as interactive zoom).
        target_zoom = max(self.MIN_ZOOM_ABS, min(target_zoom, self.MAX_ZOOM))
        end_center = target_rect.center()

        self._anim_start_zoom = start_zoom
        self._anim_end_zoom = target_zoom
        self._anim_start_center = start_center
        self._anim_end_center = end_center

        tl = QTimeLine(250, self)
        tl.setUpdateInterval(16)
        tl.setEasingCurve(QEasingCurve.Type.OutCubic)
        tl.valueChanged.connect(self._on_zoom_anim_step)
        tl.finished.connect(self._on_zoom_anim_finished)
        self._zoom_timeline = tl
        tl.start()

    def _animate_to_zoom_and_center(self, zoom: float, center: QPointF):
        """Smoothly animate to an explicit zoom level centered on a scene
        point. Unlike `_animate_to_rect` (which derives zoom from a fit),
        this preserves an exact scale — used by search cycling so every
        match lands at the same zoom level.
        """
        if self._zoom_timeline is not None:
            self._zoom_timeline.stop()
            self._zoom_timeline = None

        start_zoom = self.transform().m11()
        start_center = self.mapToScene(self.viewport().rect().center())
        target_zoom = max(self.MIN_ZOOM_ABS, min(zoom, self.MAX_ZOOM))

        self._anim_start_zoom = start_zoom
        self._anim_end_zoom = target_zoom
        self._anim_start_center = start_center
        self._anim_end_center = center

        tl = QTimeLine(250, self)
        tl.setUpdateInterval(16)
        tl.setEasingCurve(QEasingCurve.Type.OutCubic)
        tl.valueChanged.connect(self._on_zoom_anim_step)
        tl.finished.connect(self._on_zoom_anim_finished)
        self._zoom_timeline = tl
        tl.start()

    def _on_zoom_anim_step(self, value: float):
        z = self._anim_start_zoom + (self._anim_end_zoom - self._anim_start_zoom) * value
        cx = self._anim_start_center.x() + (self._anim_end_center.x() - self._anim_start_center.x()) * value
        cy = self._anim_start_center.y() + (self._anim_end_center.y() - self._anim_start_center.y()) * value
        self.setTransform(QTransform().scale(z, z))
        self.centerOn(QPointF(cx, cy))

    def _on_zoom_anim_finished(self):
        self._zoom_timeline = None
        self._update_status_zoom()

    _AUTOSCROLL_MARGIN = 40   # px from viewport edge to trigger
    _AUTOSCROLL_SPEED = 8     # px per tick

    def _autoscroll_tick(self) -> None:
        selected = self._scene.selectedItems()
        if not selected:
            self._autoscroll_timer.stop()
            return
        vp = self.viewport().rect()
        cursor_vp = self.viewport().mapFromGlobal(QCursor.pos())
        if not vp.contains(cursor_vp):
            return
        margin = self._AUTOSCROLL_MARGIN
        speed = self._AUTOSCROLL_SPEED
        dx = dy = 0
        if cursor_vp.x() > vp.width() - margin:
            dx = speed
        elif cursor_vp.x() < margin:
            dx = -speed
        if cursor_vp.y() > vp.height() - margin:
            dy = speed
        elif cursor_vp.y() < margin:
            dy = -speed
        if dx or dy:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    def _ensure_selection_visible(self) -> None:
        """Scroll viewport if any selected item is near or beyond the edge."""
        selected = self._scene.selectedItems()
        if not selected:
            return
        vp = self.viewport().rect()
        margin = 40
        dx = dy = 0
        for item in selected:
            item_vp = self.mapFromScene(item.sceneBoundingRect()).boundingRect()
            if item_vp.right() > vp.width() - margin:
                dx = max(dx, int(item_vp.right() - (vp.width() - margin)))
            if item_vp.left() < margin:
                dx = min(dx, int(item_vp.left() - margin))
            if item_vp.bottom() > vp.height() - margin:
                dy = max(dy, int(item_vp.bottom() - (vp.height() - margin)))
            if item_vp.top() < margin:
                dy = min(dy, int(item_vp.top() - margin))
        if dx or dy:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + dx)
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + dy)

    _ZOOM_STEPS: tuple[float, ...] = (0.25, 0.5, 1.0, 1.5)

    def _cycle_zoom_step(self):
        """z key: zoom in to the next-larger step in `_ZOOM_STEPS`,
        wrapping back to the smallest after the largest. Always zooms
        *in* relative to current — never sideways or out — so a single
        keypress has a predictable direction. For "fit the whole graph"
        use Shift+Z.
        """
        if not self._board:
            return
        self._push_nav_snapshot()
        current = self.transform().m11()
        # Small tolerance so an "exactly at a step" zoom still advances
        # to the next step instead of getting stuck.
        threshold = current * 1.01
        next_zoom: float | None = None
        for step in self._ZOOM_STEPS:
            if step > threshold:
                next_zoom = step
                break
        if next_zoom is None:
            next_zoom = self._ZOOM_STEPS[0]
        center = self.mapToScene(self.viewport().rect().center())
        self._animate_to_zoom_and_center(next_zoom, center)

    def _zoom_to_fit(self):
        """Shift+Z key: zoom to fit entire diagram."""
        if not self._board:
            return
        items_rect = self._scene.itemsBoundingRect()
        if not items_rect.isNull():
            self._animate_to_rect(items_rect.adjusted(-40, -40, 40, 40))

