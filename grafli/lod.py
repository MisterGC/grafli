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

Rect = tuple[float, float, float, float]  # x, y, w, h


def should_collapse(label_px: float, was_collapsed: bool) -> bool:
    """Hysteretic collapse decision for one level.

    `label_px` is the element's label size in *screen* pixels (font px x view
    scale). `was_collapsed` is that level's previous state. Returns whether the
    level should be collapsed now.
    """
    if was_collapsed:
        # Stay collapsed until labels are clearly legible again.
        return label_px < EXPAND_PX
    return label_px < COLLAPSE_PX


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
    ) -> None:
        self._parent = parent
        self._children = children
        self.containers: set[str] = set(children)
        self._rects = rects
        self._labels = labels
        self._adjacency = adjacency
        self.loose = loose
        self.components = components
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
        )

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

    # ── summaries ───────────────────────────────────────────────────────

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
