"""Bookmarks and flows for GrafliView (mixin).

Guided viewpoints through a board: bookmark capture and recall, flow
playback with per-step presentation overrides (detail / focus), edits
driven by the Flows panel, and auto-generated flows that walk forward
arrows from a start node. Camera moves go through the host's animated
zoom.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QInputDialog
from grafli.flows import FlowPlayer
from grafli.format import Arrow, Bookmark, Flow, FlowStep
from grafli.items import BoxItem, ImageItem, NoteItem
from pathlib import Path


class FlowsMixin:
    # ── Bookmarks & flows ──

    def goto_rect(self, rect: QRectF, animate: bool = True):
        """Frame ``rect`` in the viewport, eased or as an instant cut."""
        if rect.isNull():
            return
        if animate:
            self._animate_to_rect(rect)
            return
        vp = self.viewport().rect()
        zoom = min(vp.width() / max(rect.width(), 1),
                   vp.height() / max(rect.height(), 1))
        zoom = max(0.05, min(zoom, 10.0))
        self.setTransform(QTransform().scale(zoom, zoom))
        self.centerOn(rect.center())
        self._update_status_zoom()

    def goto_bookmark(self, bookmark_id: str, animate: bool = True):
        """Fly the canvas to a bookmark's semantic anchor."""
        if not self._board:
            return
        bm = self._board.bookmark_by_id(bookmark_id)
        if bm is None:
            self.toast("Bookmark not found on this board", "warn")
            return
        from grafli.flows import bookmark_target_rect
        target = bookmark_target_rect(self, bm)
        if target.isNull():
            # All focus elements deleted and no stored view: no rect to fly to.
            self.toast("This bookmark's elements are gone from the board",
                       "warn")
            return
        self.goto_rect(target, animate=animate)
        self.flash_anchor(target)

    def play_flow(self, flow_id: str):
        """Enter modal playback for a flow, starting at its first stop."""
        if not self._board:
            return
        flow = self._board.flow_by_id(flow_id)
        if flow is None:
            return
        if not flow.steps:
            self.toast("This flow has no stops yet", "warn")
            return
        if self._flow_player is not None:
            self._flow_player.stop()
        self._flow_player = FlowPlayer(self, flow)
        self._flow_player.start()
        self.setFocus()

    def export_flow(self, flow, fmt: str = "pdf"):
        """Export a specific flow via the main window's save dialog. ``fmt`` is
        'pdf' (default) or 'pptx'."""
        window = self.window()
        method = "_export_flow_pptx" if fmt == "pptx" else "_export_flow_pdf"
        if window is not None and hasattr(window, method):
            getattr(window, method)(flow)

    def capture_bookmark(self, mode: str = "logical"):
        """Snapshot the current view as a bookmark.

        ``logical`` (gb): anchor to what's shown — the current selection, else
        every item visible in the viewport — so the saved view re-fits as the
        layout changes. If nothing is shown (empty space), it transparently
        falls back to storing the exact viewport, so capture never fails.

        ``viewport`` (gB): always store the exact current viewport, for a
        hand-tuned framing you want reproduced pixel-faithfully.

        Notes are valid anchors, so a note-only (node-less) bookmark works.
        """
        if not self._board:
            return
        vp_scene = self.mapToScene(self.viewport().rect()).boundingRect()
        focus: list[str] = []
        isolate = False
        if mode == "logical":
            focus = [bid for bid, it in self._box_items.items() if it.isSelected()]
            focus += [nid for nid, it in self._note_items.items() if it.isSelected()]
            focus += [iid for iid, it in self._image_items.items() if it.isSelected()]
            # An explicit selection narrows the step's scope: render only these
            # items in thumbnails/PDF. No selection falls back to the viewport.
            isolate = bool(focus)
            if focus:
                # A selected parent brings its whole subtree, so isolating it
                # shows the contents instead of an empty container.
                focus = self._expand_focus_to_subtrees(focus)
            if not focus:
                for bid, it in self._box_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(bid)
                for nid, it in self._note_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(nid)
                for iid, it in self._image_items.items():
                    if it.sceneBoundingRect().intersects(vp_scene):
                        focus.append(iid)

        view_rect = None if focus else (
            vp_scene.x(), vp_scene.y(), vp_scene.width(), vp_scene.height()
        )

        label, ok = QInputDialog.getText(
            self, "New bookmark", "Label (blank = graph-only slide):")
        if not ok:
            self._record_shortcut("bookmark cancelled — not created")
            return
        label = label.strip()
        # A blank label means "let the graph speak" — no title/caption chrome,
        # so we skip the description prompt too.
        description = ""
        if label:
            desc, ok2 = QInputDialog.getMultiLineText(
                self, "Bookmark", "Description (optional):", "")
            if ok2:
                description = desc.strip()
        bm = Bookmark(
            id=self._board.next_bookmark_id(),
            label=label,
            focus=focus,
            description=description,
            view=view_rect,
            isolate=isolate,
        )
        self._board.add_bookmark(bm)
        if self._recording_flow is not None:
            # Recording is sequential — always append to the tour.
            self._recording_flow.steps.append(FlowStep(ref=bm.id))
            self._update_recording_status()
        elif self._active_flow is not None:
            # A flow is open in the panel — insert right after the selected
            # step (or append), then advance the selection so the next
            # capture continues the chain.
            steps = self._active_flow.steps
            idx = self._active_step_index
            if 0 <= idx < len(steps):
                steps.insert(idx + 1, FlowStep(ref=bm.id))
                self._active_step_index = idx + 1
            else:
                steps.append(FlowStep(ref=bm.id))
                self._active_step_index = len(steps) - 1
        self.mark_dirty()
        self.flows_changed.emit()
        from grafli.flows import bookmark_target_rect, text_slide_note
        if text_slide_note(self, bm) is not None:
            kind = "text slide"
        elif isolate:
            kind = f"scoped: {len(focus)} item{'s' if len(focus) != 1 else ''}"
        else:
            kind = "viewport" if view_rect else "logical"
        self._record_shortcut(f"bookmark “{bm.label}” ({kind})")
        self.flash_anchor(bookmark_target_rect(self, bm))

    def toggle_flow_recording(self):
        """Start a new flow recording, or stop the active one.

        While recording, each captured bookmark is also appended to the
        active flow — so a tour accretes as you explore, no separate
        compose step.
        """
        if not self._board:
            return
        if self._recording_flow is not None:
            flow = self._recording_flow
            self._recording_flow = None
            if not flow.steps:
                # An empty recording is noise — drop it, but say so: the
                # recording badge vanishing is not an explanation.
                self._board.remove_flow(flow)
                self.toast("Recording discarded — no stops captured", "warn")
            self.mark_dirty()
            self.flows_changed.emit()
            self._update_recording_status()
            self.viewport().update()
            return
        label, ok = QInputDialog.getText(self, "Record flow", "Flow name:")
        if not ok or not label.strip():
            return
        flow = Flow(id=self._board.next_flow_id(), label=label.strip(), steps=[])
        self._board.add_flow(flow)
        self._recording_flow = flow
        self.mark_dirty()
        self.flows_changed.emit()
        self._update_recording_status()
        self.viewport().update()

    def _update_recording_status(self):
        if self._recording_flow is not None:
            n = len(self._recording_flow.steps)
            self._record_shortcut(
                f"REC {self._recording_flow.label} · {n} stop(s) · gb to add"
            )

    # ── Flow / bookmark editing (driven by the Flows panel) ──

    def set_flow_edit_target(self, flow, step_index: int = -1):
        """Remember which flow/step the panel has selected, so a captured
        bookmark is inserted after it."""
        self._active_flow = flow
        self._active_step_index = step_index

    def _commit_flow_edit(self):
        """Persist a flow/bookmark mutation and refresh the panel."""
        self.mark_dirty()
        self.flows_changed.emit()

    def create_flow(self, label: str, description: str = ""):
        if not self._board:
            return None
        flow = Flow(id=self._board.next_flow_id(), label=label,
                    description=description)
        self._board.add_flow(flow)
        self._commit_flow_edit()
        return flow

    # ── Auto-generated flows (walk forward arrows from a start node) ──

    def _is_annotation_link(self, arrow: Arrow) -> bool:
        """Whether ``arrow`` is an annotation link (vs. a real graph edge).

        ``arrow.kind`` overrides when set; otherwise the kind derives from the
        endpoints — a note or image endpoint makes it an annotation, box↔box is
        a graph edge. This resolver is the single source of truth for rendering,
        the note/image-selection spotlight, auto-flow, and graph-nav.
        """
        if arrow.kind == "annotation":
            return True
        if arrow.kind == "graph":
            return False
        if not self._board:
            return False
        return self._involves_note_or_image(arrow.from_id, arrow.to_id)

    def _involves_note_or_image(self, from_id: str, to_id: str) -> bool:
        """Whether either endpoint is a note or image — the non-box elements
        whose connectors default to (and remember) an annotation/graph kind."""
        if not self._board:
            return False
        return bool(self._board.note_by_id(from_id)
                    or self._board.note_by_id(to_id)
                    or self._board.image_by_id(from_id)
                    or self._board.image_by_id(to_id))

    def _is_graph_edge(self, arrow: Arrow) -> bool:
        """Whether ``arrow`` is a real graph edge (the auto-flow/graph-nav seam)."""
        return self._board is not None and not self._is_annotation_link(arrow)

    def _make_connector(self, from_id: str, to_id: str) -> Arrow:
        """A new connector, applying the sticky connector kind when a note or
        image is involved (so a run of connected notes/images inherits your last
        choice)."""
        arrow = Arrow(from_id=from_id, to_id=to_id)
        if self._involves_note_or_image(from_id, to_id) and self._last_connector_kind:
            arrow.kind = self._last_connector_kind
        return arrow

    def _strict_forward_target(self, arrow: Arrow, node_id: str) -> str | None:
        """The node ``arrow`` leads to from ``node_id`` via a strict-forward
        edge, else None. Strict = exactly one arrowhead, pointing away."""
        if arrow.head_to == arrow.head_from:      # both/neither head → not strict
            return None
        if arrow.from_id == node_id and arrow.head_to:
            return arrow.to_id
        if arrow.to_id == node_id and arrow.head_from:
            return arrow.from_id
        return None

    def _forward_targets(self, node_id: str) -> list[str]:
        """Distinct nodes reachable from ``node_id`` by a strict-forward edge."""
        out: list[str] = []
        if not self._board:
            return out
        for arrow in self._board.arrows:
            if not self._is_graph_edge(arrow):
                continue
            t = self._strict_forward_target(arrow, node_id)
            if t is not None and t not in out:
                out.append(t)
        return out

    def _auto_flow_path(self, start_id: str) -> tuple[list[str], str]:
        """Walk strict-forward from ``start_id``: returns (node ids, stop reason).

        Continues while a node has exactly one forward target; stop reason is
        ``end`` (no forward), ``branch`` (several), or ``cycle`` (revisit).
        """
        path = [start_id]
        visited = {start_id}
        reason = "end"
        current = start_id
        while True:
            targets = self._forward_targets(current)
            if not targets:
                reason = "end"
                break
            if len(targets) > 1:
                reason = "branch"
                break
            nxt = targets[0]
            if nxt in visited:
                reason = "cycle"
                break
            path.append(nxt)
            visited.add(nxt)
            current = nxt
        return path, reason

    def _make_auto_bookmark(self, node_id: str) -> Bookmark:
        """An isolated bookmark framing one node (a parent expands to its
        subtree). A box keeps its label (titled slide); a note stays
        label-less so it renders as a pure text slide."""
        box = self._board.box_by_id(node_id)
        label = box.label if box else ""
        focus = self._expand_focus_to_subtrees([node_id])
        bm = Bookmark(id=self._board.next_bookmark_id(), label=label,
                      focus=focus, isolate=True)
        self._board.add_bookmark(bm)
        return bm

    def _populate_auto_flow(self, flow: Flow) -> None:
        path, reason = self._auto_flow_path(flow.auto_start)
        flow.steps = [FlowStep(ref=self._make_auto_bookmark(nid).id)
                      for nid in path]
        n = len(path)
        steps = f"{n} stop{'s' if n != 1 else ''}"
        if reason == "branch":
            box = self._board.box_by_id(path[-1])
            where = (box.label.replace("\n", " ") if box and box.label
                     else path[-1])
            self._record_shortcut(
                f"auto-flow: {n} step(s), stopped at branch '{where}'")
            self.toast(f"Auto-flow: {steps}, stopped at the branch “{where}”",
                       "info")
        elif reason == "cycle":
            self._record_shortcut(f"auto-flow: {n} step(s), stopped (cycle)")
            self.toast(f"Auto-flow: {steps}, stopped at a cycle", "info")
        else:
            self._record_shortcut(f"auto-flow: {n} step(s)")
            self.toast(f"Auto-flow: {steps}", "info")

    def _discard_auto_bookmarks(self, flow: Flow) -> None:
        """Remove the bookmarks this flow's steps own (not used by any other
        flow), so re-generating doesn't leave orphans behind."""
        others: set[str] = set()
        for f in self._board.flows:
            if f is flow:
                continue
            others.update(s.ref for s in f.steps)
        for step in list(flow.steps):
            if step.ref not in others:
                bm = self._board.bookmark_by_id(step.ref)
                if bm is not None:
                    self._board.remove_bookmark(bm)
        flow.steps = []

    def _node_exists(self, node_id: str) -> bool:
        """True if ``node_id`` is a real graph node (box, note or image)."""
        return bool(self._board and (self._board.box_by_id(node_id)
                                     or self._board.note_by_id(node_id)
                                     or self._board.image_by_id(node_id)))

    def create_auto_flow(self, start_id: str, label: str):
        """Create a flow by walking forward arrows from ``start_id``."""
        if not self._node_exists(start_id):
            self._record_shortcut("auto-flow needs a node")
            self.toast("Auto-flow needs a node to start from", "warn")
            return None
        self._push_undo()
        flow = Flow(id=self._board.next_flow_id(), label=label,
                    auto_start=start_id)
        self._board.add_flow(flow)
        self._populate_auto_flow(flow)
        self._commit_flow_edit()
        return flow

    def regenerate_auto_flow(self, flow):
        """Re-walk from the flow's stored start node: rewrite the steps, keep
        the title page (label/description)."""
        if not self._board or flow is None or not flow.auto_start:
            return
        if not self._node_exists(flow.auto_start):
            self._record_shortcut("auto-flow: start node is gone")
            self.toast("Auto-flow start node is gone from the board", "warn")
            return
        self._push_undo()
        self._discard_auto_bookmarks(flow)
        self._populate_auto_flow(flow)
        self._commit_flow_edit()

    def new_auto_flow_from_selection(self):
        """gF/panel: auto-flow from the single selected node (box, note or image)."""
        nodes = [i for i in self._scene.selectedItems()
                 if isinstance(i, (BoxItem, NoteItem, ImageItem))]
        if len(nodes) != 1:
            self._record_shortcut("auto-flow: select exactly one node first")
            self.toast("Select exactly one node to auto-flow from", "warn")
            return None
        item = nodes[0]
        if isinstance(item, BoxItem):
            text = item.box.label
        elif isinstance(item, NoteItem):
            text = item.note.text
        else:  # ImageItem has no text — name the flow after the image file
            text = Path(item.image.image_path).stem
        label = (text.replace("\n", " ").strip() or "Auto flow")[:60]
        return self.create_auto_flow(self._item_id(item), label)

    def delete_flow(self, flow):
        if not self._board or flow is None:
            return
        if self._recording_flow is flow:
            self._recording_flow = None
        if self._active_flow is flow:
            self._active_flow = None
            self._active_step_index = -1
        self._board.remove_flow(flow)
        self._commit_flow_edit()

    def delete_bookmark(self, bookmark):
        """Delete a bookmark and prune any flow steps that referenced it, so
        no flow is left pointing at a missing stop."""
        if not self._board or bookmark is None:
            return
        for flow in self._board.flows:
            flow.steps = [s for s in flow.steps if s.ref != bookmark.id]
        self._board.remove_bookmark(bookmark)
        self._commit_flow_edit()

    def _set_flow_overlay(self, overlay: dict):
        self._flow_overlay = overlay
        self.viewport().update()

    def _clear_flow_overlay(self):
        self._flow_overlay = None
        self.viewport().update()

    # ── Presentation overrides (per-step detail / focus) ──

    def _set_presentation_detail(self, detail: str | None):
        """Override the global LoD toggle while a step is shown: "full" keeps
        everything as authored, "summary" collapses containers to tiles, and
        None returns control to the global GUI setting."""
        detail = detail if detail in ("full", "summary") else None
        if detail == self._present_detail:
            return
        self._present_detail = detail
        self._refresh_lod()

    def _set_presentation_focus(self, rect: QRectF | None):
        """Set (or clear, with None) the "complete" focus frame: elements not
        completely inside ``rect`` dim to the standard 0.08 blend level, and a
        connector stays at full opacity only when both its endpoints do."""
        if rect is None and self._present_focus_rect is None:
            return
        self._present_focus_rect = QRectF(rect) if rect is not None else None
        self._apply_presentation_focus()
        self.viewport().update()

    def _presentation_focus_contained(self) -> set[str]:
        """Ids of the visible boxes/notes/images completely inside the focus
        frame. Only meaningful while a focus frame is set."""
        rect = self._present_focus_rect
        contained: set[str] = set()
        if rect is None:
            return contained
        for items in (self._box_items, self._note_items, self._image_items):
            for eid, item in items.items():
                if item.isVisible() and rect.contains(item.sceneBoundingRect()):
                    contained.add(eid)
        return contained

    def _apply_presentation_focus(self):
        """(Re)apply the focus fade — or restore the resting opacities, which
        must respect the standing dim toggles (⇧N notes, "," arrows) and the
        subgraph-focus / complexity filters when clearing."""
        if self._present_focus_rect is None:
            for item in self._box_items.values():
                item.setOpacity(1.0)
                item._label.setOpacity(1.0)
            for item in self._note_items.values():
                item.setOpacity(1.0)
            for item in self._image_items.values():
                item.setOpacity(1.0)
            for gfx in self._arrow_items:
                gfx.setOpacity(1.0)
            if self._focus_active:
                self._apply_focus_filter()
            elif self._complexity_active:
                self._apply_complexity_heatmap()
            else:
                if self._arrows_dimmed:
                    for gfx in self._arrow_items:
                        gfx.setOpacity(0.08)
                if self._notes_hidden:
                    self._apply_notes_hidden()
            return
        contained = self._presentation_focus_contained()
        for bid, item in self._box_items.items():
            opacity = 1.0 if bid in contained else 0.08
            item.setOpacity(opacity)
            item._label.setOpacity(opacity)
        for nid, item in self._note_items.items():
            item.setOpacity(1.0 if nid in contained else 0.08)
        for iid, item in self._image_items.items():
            item.setOpacity(1.0 if iid in contained else 0.08)
        for gfx in self._arrow_items:
            arrow = gfx.data(0)
            if arrow is None:
                continue
            # Endpoints may be re-routed to a collapsed tile under LoD — judge
            # the connector by what is actually drawn on screen.
            from_id = self._lod_reroute(arrow.from_id)
            to_id = self._lod_reroute(arrow.to_id)
            both_in = from_id in contained and to_id in contained
            gfx.setOpacity(1.0 if both_in else 0.08)

