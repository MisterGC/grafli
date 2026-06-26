"""Level-of-Detail (semantic zoom) structural model — see issue #103.

Pure, Qt-free derivation of the structural facts LoD rendering needs, kept
separate from painting on purpose:

* **Structural clock (this module).** Rebuilt only when the *board* changes
  (add / remove / move / reparent a box, add / remove an arrow). It derives
  the parent/child hierarchy, per-container summaries (headline + counts +
  aggregate rect), connectivity (components of parent-less "loose" boxes),
  the proxy -> backing-element map used for selection, and the ancestor
  chains used to re-route arrows when a group collapses.
* **Zoom clock (the view).** Picks the active tier from the live zoom with
  hysteresis and just *reads* this warm model — so crossing a zoom threshold
  never triggers graph work mid-scroll.

Keeping it Qt-free means the whole structural layer is unit-testable headless.
The numeric tier helpers (`should_collapse`) take already-resolved pixel sizes
so this module never has to reach into the font stack or the view transform.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

# A level collapses once its child labels would render below the legibility
# floor (on-screen pixels). The two thresholds form a hysteresis band so that
# scrubbing the zoom across the boundary doesn't strobe: a group collapses at
# COLLAPSE_PX but only re-expands once labels are comfortably above EXPAND_PX.
COLLAPSE_PX = 8.0
EXPAND_PX = 10.0

# A container collapses to a single tile once its children render smaller than
# this on-screen (the largest child's shorter side, in pixels). Smaller, deeper
# children cross the floor first, so nesting collapses innermost-first.
CHILD_COLLAPSE_PX = 50.0
CHILD_EXPAND_PX = 64.0

Rect = tuple[float, float, float, float]  # x, y, w, h


def _hysteretic(value: float, lo: float, hi: float, was: bool) -> bool:
    """Collapsed if `value` is below `lo`; once collapsed, stay so until `hi`."""
    return value < (hi if was else lo)


def should_collapse(label_px: float, was_collapsed: bool) -> bool:
    """Hysteretic per-element label legibility (the phase-2 "shell" tier).

    `label_px` is the element's label size in *screen* pixels (font px x view
    scale). The dead band between the thresholds stops flicker at the boundary.
    """
    return _hysteretic(label_px, COLLAPSE_PX, EXPAND_PX, was_collapsed)


def should_collapse_container(child_px: float, was_collapsed: bool) -> bool:
    """Hysteretic container collapse, driven by on-screen child size."""
    return _hysteretic(child_px, CHILD_COLLAPSE_PX, CHILD_EXPAND_PX, was_collapsed)


@dataclass(frozen=True)
class ContainerSummary:
    """What a collapsed container renders as: a headline tile."""

    id: str
    label: str
    direct_children: int
    descendants: int
    rect: Rect  # union of the container and all its descendants


class LodModel:
    """Derived structural view of a board for Level-of-Detail rendering.

    Build once with :meth:`from_board`; rebuild (cheap) on board mutations.
    Nothing here depends on the live zoom — that is the view's concern.
    """

    def __init__(
        self,
        *,
        parent: dict[str, str],
        children: dict[str, list[str]],
        rects: dict[str, Rect],
        labels: dict[str, str],
        adjacency: dict[str, set[str]],
        loose: set[str],
        components: list[list[str]],
        note_ids: set[str] | None = None,
    ) -> None:
        self._parent = parent
        self._children = children
        self.containers: set[str] = set(children)
        self._rects = rects
        self._labels = labels
        self._adjacency = adjacency
        self.loose = loose
        self.components = components
        self._note_ids: set[str] = note_ids or set()
        self._summaries: dict[str, ContainerSummary] = {}

    # ── construction ────────────────────────────────────────────────────

    @classmethod
    def from_board(cls, board) -> "LodModel":
        parent: dict[str, str] = {}
        rects: dict[str, Rect] = {}
        labels: dict[str, str] = {}

        for b in board.boxes:
            parent[b.id] = b.parent
            rects[b.id] = (b.x, b.y, b.w, b.h)
            labels[b.id] = b.label
        for im in getattr(board, "images", []):
            parent[im.id] = im.parent
            rects[im.id] = (im.x, im.y, im.w, im.h)
        for n in board.notes:
            parent[n.id] = n.parent
            # Notes carry no width/height; treat as a zero-size point so they
            # still extend a container's aggregate rect by their position.
            rects[n.id] = (n.x, n.y, 0.0, 0.0)

        children: dict[str, list[str]] = defaultdict(list)
        for cid, pid in parent.items():
            if pid:
                children[pid].append(cid)
        children = {k: v for k, v in children.items()}

        # Undirected adjacency over boxes, from arrow endpoints.
        adjacency: dict[str, set[str]] = defaultdict(set)
        box_ids = {b.id for b in board.boxes}
        for a in board.arrows:
            if a.from_id in box_ids and a.to_id in box_ids:
                adjacency[a.from_id].add(a.to_id)
                adjacency[a.to_id].add(a.from_id)
        adjacency = {k: v for k, v in adjacency.items()}

        # Loose = top-level boxes that are not themselves containers: the
        # free-floating region LoD renders as a label-only constellation.
        containers = set(children)
        loose = {
            b.id for b in board.boxes if not b.parent and b.id not in containers
        }
        components = _components(loose, adjacency)

        return cls(
            parent=parent,
            children=children,
            rects=rects,
            labels=labels,
            adjacency=adjacency,
            loose=loose,
            components=components,
            note_ids={n.id for n in board.notes},
        )

    def set_note_extents(self, sizes: dict[str, tuple[float, float]]) -> None:
        """Replace notes' placeholder zero size with their rendered footprint
        (scene units), so a note counts as a real child for the collapse
        decision — a notes-only container (a legend, a stack of stickies)
        aggregates into a tile like any box container instead of just having
        its notes vanish. Position is kept; only width/height change."""
        for nid, (w, h) in sizes.items():
            r = self._rects.get(nid)
            if r is not None:
                self._rects[nid] = (r[0], r[1], w, h)
        self._summaries.clear()

    # ── hierarchy queries ───────────────────────────────────────────────

    def is_container(self, elem_id: str) -> bool:
        return elem_id in self.containers

    def children_of(self, elem_id: str) -> list[str]:
        return list(self._children.get(elem_id, ()))

    def ancestors(self, elem_id: str) -> list[str]:
        """Parent chain, immediate parent first up to the root."""
        chain: list[str] = []
        seen: set[str] = {elem_id}
        cur = self._parent.get(elem_id, "")
        while cur and cur not in seen:
            chain.append(cur)
            seen.add(cur)
            cur = self._parent.get(cur, "")
        return chain

    def descendants(self, elem_id: str) -> list[str]:
        out: list[str] = []
        stack = list(self._children.get(elem_id, ()))
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(self._children.get(cur, ()))
        return out

    # ── proxy / selection ───────────────────────────────────────────────

    def proxy_backing(self, proxy_id: str) -> str:
        """The real model element a proxy resolves to.

        A collapsed container tile *is* its parent box, so the proxy maps to
        the same id — selection and styling apply to a real element with all
        the existing edit machinery. (Synthetic cluster tiles, which have no
        backing element, are deferred and would be navigation-only.)
        """
        return proxy_id

    def resolve_visible(self, elem_id: str, collapsed: set[str]) -> str:
        """Map an element to the outermost collapsed ancestor that hides it.

        Used to re-route an arrow whose endpoint sits inside a collapsed group:
        the arrow re-attaches to the highest collapsed tile in the chain. If no
        ancestor (nor the element itself) is collapsed, the element is visible
        and returned unchanged.
        """
        visible = elem_id
        for node in [elem_id, *self.ancestors(elem_id)]:
            if node in collapsed:
                visible = node  # keep climbing; last match = outermost
        return visible

    # ── loose clusters (parent-less connected components) ────────────────

    def component_edges(self, component) -> list[tuple[str, str]]:
        """Undirected member-to-member edges within a component (each once)."""
        members = set(component)
        out: list[tuple[str, str]] = []
        seen: set[frozenset[str]] = set()
        for a in members:
            for b in self._adjacency.get(a, ()):
                if b in members and a != b:
                    key = frozenset((a, b))
                    if key not in seen:
                        seen.add(key)
                        out.append((a, b))
        return out

    def component_hub(self, component) -> str:
        """The most-connected member (highest in-component degree) — the label
        a collapsed cluster borrows, since it has no author-given name."""
        members = set(component)
        best, best_deg = component[0], -1
        for m in component:
            deg = sum(1 for n in self._adjacency.get(m, ()) if n in members)
            if deg > best_deg:
                best, best_deg = m, deg
        return best

    def cluster_pad(self, component) -> float:
        """Adaptive hull padding (scene units): the smallest cushion that still
        reads as one region, scaled to the members' size. Connectivity itself is
        guaranteed by stroking the member edges, so this only sets tightness."""
        dims = []
        for m in component:
            r = self._rects.get(m)
            if r and r[2] > 0 and r[3] > 0:
                dims.append(min(r[2], r[3]))
        if not dims:
            return 18.0
        dims.sort()
        median = dims[len(dims) // 2]
        return max(16.0, min(36.0, 0.34 * median))

    def label_of(self, elem_id: str) -> str:
        return self._labels.get(elem_id, elem_id)

    # ── summaries ───────────────────────────────────────────────────────

    def child_extent(self, container_id: str) -> float:
        """On-screen-size driver for collapse: the largest direct child's
        shorter side (scene units). The view multiplies by the zoom scale and
        compares against the collapse threshold. ``inf`` when no sized child
        exists, so such a container never collapses on size alone.
        """
        best = 0.0
        for cid in self._children.get(container_id, ()):
            r = self._rects.get(cid)
            if r is None:
                continue
            _, _, w, h = r
            if w <= 0 or h <= 0:
                continue
            # A box uses its shorter side. A note is a thin horizontal badge:
            # its height alone would keep a legend collapsed even at full zoom,
            # while its width would inflate a mixed container above its boxes and
            # delay collapse out of step with note-free siblings. The geometric
            # mean (the "equivalent square") sits between — comparable to a small
            # box, so notes neither dominate nor get ignored.
            ext = (w * h) ** 0.5 if cid in self._note_ids else min(w, h)
            best = max(best, ext)
        return best if best > 0 else float("inf")

    def summary(self, container_id: str) -> ContainerSummary:
        cached = self._summaries.get(container_id)
        if cached is not None:
            return cached
        desc = self.descendants(container_id)
        rect = self._union_rect([container_id, *desc])
        summ = ContainerSummary(
            id=container_id,
            label=self._labels.get(container_id, container_id),
            direct_children=len(self._children.get(container_id, ())),
            descendants=len(desc),
            rect=rect,
        )
        self._summaries[container_id] = summ
        return summ

    def _union_rect(self, ids: list[str]) -> Rect:
        xs0, ys0, xs1, ys1 = [], [], [], []
        for i in ids:
            r = self._rects.get(i)
            if r is None:
                continue
            x, y, w, h = r
            xs0.append(x)
            ys0.append(y)
            xs1.append(x + w)
            ys1.append(y + h)
        if not xs0:
            return (0.0, 0.0, 0.0, 0.0)
        x0, y0 = min(xs0), min(ys0)
        return (x0, y0, max(xs1) - x0, max(ys1) - y0)


def _components(nodes: set[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    """Connected components within `nodes` (edges restricted to `nodes`)."""
    seen: set[str] = set()
    out: list[list[str]] = []
    for start in nodes:
        if start in seen:
            continue
        comp: list[str] = []
        q = deque([start])
        seen.add(start)
        while q:
            cur = q.popleft()
            comp.append(cur)
            for nb in adjacency.get(cur, ()):
                if nb in nodes and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        out.append(comp)
    return out
