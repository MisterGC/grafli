"""Pure layout algorithm for auto-arranging boxes. No Qt dependency."""

from __future__ import annotations

import enum
import math
from collections import defaultdict
from collections.abc import Callable

from grafli.constants import LAYOUT_LAYER_GAP, LAYOUT_NODE_GAP, LAYOUT_PADDING
from grafli.format import Arrow, Board


class Direction(enum.Enum):
    LTR = "ltr"  # left-to-right (layers along x, nodes along y)
    TTB = "ttb"  # top-to-bottom (layers along y, nodes along x)


def compute_layout(
    board: Board,
    target_ids: set[str],
    parent_id: str,
    direction: Direction | None,
    grid: float,
    label_height: float,
    box_sizes: dict[str, tuple[float, float]],
    arrow_label_size: ArrowLabelSizeFn | None = None,
) -> dict[str, tuple[float, float]]:
    """Return {box_id: (new_x, new_y)} for each box in target_ids.

    With *arrow_label_size*, the gap between two layers grows to hold the
    widest label of an arrow between them, so the label sits in the gap
    instead of on a box.

    A pinned box (``!pin``) gets no entry: it stays where it is, and the
    other boxes are placed around it. It still takes part in the ranking,
    so ``a -> pinned -> b`` keeps ``a`` before ``b``."""
    pinned = {bid for bid in target_ids
              if (box := board.box_by_id(bid)) and box.pinned}
    obstacles = [_rect_of(board, bid, box_sizes) for bid in sorted(pinned)]
    free_ids = target_ids - pinned
    if not free_ids:
        return {}
    if len(free_ids) == 1 and not obstacles:
        return _layout_single(board, free_ids, parent_id, grid, label_height, box_sizes)

    constraint = _constraint_rect(board, free_ids, parent_id, label_height, box_sizes)
    adj, radj = _build_dag(board, target_ids)
    # Without a parent the area is the boxes' own bounding box, which the
    # layout itself changes: centring in it would shift every rerun.
    in_parent = bool(parent_id and board.box_by_id(parent_id))
    if in_parent:
        constraint = _inner_on_grid(constraint, grid)

    def _place_in(d: Direction, area: Rect) -> dict[str, tuple[float, float]]:
        layers = _assign_layers(target_ids, adj, radj)
        layers = _order_within_layers(layers, adj, board, d, target_ids, box_sizes)
        layers = [kept for layer in layers
                  if (kept := [n for n in layer if n not in pinned])]
        gaps = _layer_gaps(board, layers, d, target_ids, arrow_label_size)
        return _assign_coordinates(layers, d, area, grid, box_sizes,
                                   obstacles, center_on_widest=not in_parent,
                                   layer_gaps=gaps)

    def _place(d: Direction) -> dict[str, tuple[float, float]]:
        if in_parent or not obstacles:
            return _place_in(d, constraint)
        # At the root the next run starts from the free boxes' own edge.
        # A pin can push the widest layer off that edge and leave a
        # centred layer as the leftmost box, so shift the start until the
        # free boxes begin at the edge they began at: a rerun then finds
        # the same edge and reproduces the layout.
        axis = 0 if d == Direction.TTB else 1
        target = _snap(constraint[axis], grid)
        area = constraint
        for _ in range(_ROOT_EDGE_TRIES):
            positions = _place_in(d, area)
            lo = min(pos[axis] for pos in positions.values())
            if lo == target:
                break
            shifted = list(area)
            shifted[axis] += target - lo
            area = (shifted[0], shifted[1], shifted[2], shifted[3])
        return positions

    if direction is not None:
        return _place(direction)
    preferred = _auto_direction(board, parent_id, constraint)
    if not in_parent:
        return _place(preferred)
    # In a container, take the flow that needs the container to grow the
    # least, by its shape when both fit: choosing by shape alone would let
    # a container the layout reshaped flip its flow on the next run.
    other = Direction.TTB if preferred == Direction.LTR else Direction.LTR
    placed = [(_growth(pos, constraint, box_sizes), i, pos)
              for i, pos in enumerate((_place(preferred), _place(other)))]
    return min(placed, key=lambda t: (t[0], t[1]))[2]


def _growth(
    positions: dict[str, tuple[float, float]],
    constraint: tuple[float, float, float, float],
    box_sizes: dict[str, tuple[float, float]],
) -> float:
    """The area the constraint rect must gain to hold *positions*."""
    cx, cy, cw, ch = constraint
    need_w = max((x + box_sizes.get(n, (160, 80))[0] for n, (x, _) in positions.items()),
                 default=cx) - cx
    need_h = max((y + box_sizes.get(n, (160, 80))[1] for n, (_, y) in positions.items()),
                 default=cy) - cy
    return max(cw, need_w) * max(ch, need_h) - cw * ch


# How often a root layout with pinned boxes shifts its start to begin at
# the free boxes' edge before it settles for the last try.
_ROOT_EDGE_TRIES = 4


# ── Whole-board driver ──────────────────────────────────────────

# The label band above a container's children, by container id ("" = the
# board root, which has none). The app measures its label; headless callers
# use the documented margin model.
LabelHeightFn = Callable[[str], float]

# An arrow label's drawn (width, height). The app measures it in the face
# the label is drawn in; without one, layers keep the fixed gap.
ArrowLabelSizeFn = Callable[[Arrow], tuple[float, float]]

# What a label needs beside it in a layer gap: the plate's padding, then
# room for a stub of line and an arrowhead on each side of the label.
_LABEL_GAP_PAD = 4
_LABEL_GAP_STUB = 16


def container_groups(board: Board, parent_id: str = "") -> list[tuple[str, set[str]]]:
    """The (parent_id, child_ids) groups to lay out under *parent_id*,
    recursively: the parent's own children, then each child's."""
    children = {b.id for b in board.boxes if b.parent == parent_id}
    if not children:
        return []
    result: list[tuple[str, set[str]]] = [(parent_id, children)]
    for cid in sorted(children):
        result.extend(container_groups(board, cid))
    return result


def layout_groups(
    board: Board,
    groups: list[tuple[str, set[str]]],
    grid: float,
    label_height: LabelHeightFn,
    direction: Direction | None = None,
    arrow_label_size: ArrowLabelSizeFn | None = None,
) -> None:
    """Lay out each group in place, deepest container first, so a
    container has grown to fit its children before its own siblings are
    placed. Moving a box moves its descendants and parented notes along.
    *arrow_label_size* widens a layer gap to hold its arrow labels."""
    groups = sorted(groups, key=lambda g: -_depth(board, g[0]))
    # Put every container that will be filled on the grid first, so its
    # children are placed in a grid-aligned frame: a container moved onto
    # the grid afterwards would leave them off it, and the next run would
    # shift them back.
    for parent_id, _ in reversed(groups):
        parent = board.box_by_id(parent_id) if parent_id else None
        if parent and not parent.pinned:
            nx, ny = _snap(parent.x, grid), _snap(parent.y, grid)
            dx, dy = nx - parent.x, ny - parent.y
            parent.x, parent.y = nx, ny
            _propagate_delta(board, parent_id, dx, dy)
    for parent_id, child_ids in groups:
        _layout_group(board, parent_id, child_ids, grid,
                      label_height(parent_id) if parent_id else 0.0,
                      direction, arrow_label_size)


def route_placed_arrows(board: Board,
                        groups: list[tuple[str, set[str]]]) -> None:
    """Draw the arrows between placed boxes at right angles (#284).

    An arrow whose two ends are boxes of *groups* that the layout places —
    every one but a ``!pin`` box — and that has no routing flag yet gets
    ``!ortho``. ``!spline``, ``!ortho`` and ``!straight`` stay as they are,
    so ``!straight`` keeps an arrow direct across layout runs. A loop back
    to its own box and an arrow to a note or an image keep their shape."""
    placed = {bid for _, ids in groups for bid in ids
              if (box := board.box_by_id(bid)) and not box.pinned}
    for arrow in board.arrows:
        if (not arrow.routing and arrow.from_id != arrow.to_id
                and arrow.from_id in placed and arrow.to_id in placed):
            arrow.routing = "ortho"


def _depth(board: Board, parent_id: str) -> int:
    """How deep a group sits: 0 for the board root, 1 for a top-level
    container, one more per enclosing container."""
    d = 0
    pid = parent_id
    seen: set[str] = set()
    while pid and pid not in seen:
        seen.add(pid)
        d += 1
        box = board.box_by_id(pid)
        pid = box.parent if box else ""
    return d


def _layout_group(
    board: Board,
    parent_id: str,
    child_ids: set[str],
    grid: float,
    label_height: float,
    direction: Direction | None,
    arrow_label_size: ArrowLabelSizeFn | None = None,
) -> None:
    box_sizes: dict[str, tuple[float, float]] = {}
    for cid in child_ids:
        box = board.box_by_id(cid)
        if box:
            box_sizes[cid] = (box.w, box.h)

    new_positions = compute_layout(
        board, child_ids, parent_id, direction, grid, label_height, box_sizes,
        arrow_label_size,
    )

    # Grow the parent to fit naturally-spaced children
    if parent_id and new_positions:
        parent = board.box_by_id(parent_id)
        if parent:
            max_right = max(nx + box_sizes[bid][0]
                            for bid, (nx, ny) in new_positions.items())
            max_bottom = max(ny + box_sizes[bid][1]
                             for bid, (nx, ny) in new_positions.items())
            needed_w = max_right + LAYOUT_PADDING - parent.x
            needed_h = max_bottom + LAYOUT_PADDING - parent.y
            # Round up: rounding to the nearest cell would take up to half
            # a cell off the padding below and right of the children.
            if needed_w > parent.w:
                parent.w = _snap_up(needed_w, grid)
            if needed_h > parent.h:
                parent.h = _snap_up(needed_h, grid)

    # Apply positions and carry descendants and notes along
    for bid, (nx, ny) in new_positions.items():
        box = board.box_by_id(bid)
        if not box:
            continue
        dx = nx - box.x
        dy = ny - box.y
        box.x = nx
        box.y = ny
        _propagate_delta(board, bid, dx, dy)


def _propagate_delta(board: Board, box_id: str, dx: float, dy: float) -> None:
    """Move all descendants, parented notes and images of *box_id* by
    (dx, dy)."""
    for box in board.boxes:
        if box.parent == box_id:
            box.x += dx
            box.y += dy
            _propagate_delta(board, box.id, dx, dy)
    for item in (*board.notes, *board.images):
        if item.parent == box_id:
            item.x += dx
            item.y += dy


# ── Internals ────────────────────────────────────────────────────

Rect = tuple[float, float, float, float]


def _rect_of(board: Board, bid: str, box_sizes: dict[str, tuple[float, float]]) -> Rect:
    box = board.box_by_id(bid)
    w, h = box_sizes.get(bid, (box.w, box.h))
    return (box.x, box.y, w, h)


def _blocking(rect: Rect, obstacles: list[Rect]) -> Rect | None:
    """The first obstacle *rect* comes closer to than the node gap."""
    x, y, w, h = rect
    g = LAYOUT_NODE_GAP
    for o in obstacles:
        ox, oy, ow, oh = o
        if x < ox + ow + g and x + w > ox - g and y < oy + oh + g and y + h > oy - g:
            return o
    return None


def _layout_single(
    board: Board,
    target_ids: set[str],
    parent_id: str,
    grid: float,
    label_height: float,
    box_sizes: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """Single box: center in parent or keep in place."""
    box_id = next(iter(target_ids))
    if not parent_id:
        return {}
    parent = board.box_by_id(parent_id)
    if not parent:
        return {}
    bw, bh = box_sizes.get(box_id, (0, 0))
    inner_x = parent.x + LAYOUT_PADDING
    inner_y = parent.y + label_height + LAYOUT_PADDING
    inner_w = parent.w - 2 * LAYOUT_PADDING
    inner_h = parent.h - label_height - 2 * LAYOUT_PADDING
    cx = inner_x + (inner_w - bw) / 2
    cy = inner_y + (inner_h - bh) / 2
    # A child larger than the inner area starts at its edge, not past it:
    # the parent then grows on the far side to hold it.
    cx = max(_snap(cx, grid), _snap_up(inner_x, grid))
    cy = max(_snap(cy, grid), _snap_up(inner_y, grid))
    return {box_id: (cx, cy)}


def _constraint_rect(
    board: Board,
    target_ids: set[str],
    parent_id: str,
    label_height: float,
    box_sizes: dict[str, tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return (x, y, w, h) of the area to lay out within."""
    if parent_id:
        parent = board.box_by_id(parent_id)
        if parent:
            x = parent.x + LAYOUT_PADDING
            y = parent.y + label_height + LAYOUT_PADDING
            w = parent.w - 2 * LAYOUT_PADDING
            h = parent.h - label_height - 2 * LAYOUT_PADDING
            return (x, y, max(w, 0), max(h, 0))

    # No parent — bounding box of current positions
    xs, ys, xes, yes = [], [], [], []
    for bid in target_ids:
        box = board.box_by_id(bid)
        if box:
            bw, bh = box_sizes.get(bid, (box.w, box.h))
            xs.append(box.x)
            ys.append(box.y)
            xes.append(box.x + bw)
            yes.append(box.y + bh)
    if not xs:
        return (0, 0, 400, 300)
    return (min(xs), min(ys), max(xes) - min(xs), max(yes) - min(ys))


def _inner_on_grid(area: Rect, grid: float) -> Rect:
    """Move the start of a container's inner area onto the next grid line.

    Positions snap to the nearest grid point; an inner area starting off
    the grid (a measured title band) would let the first child round
    back into the title or out to the edge."""
    x, y, w, h = area
    nx, ny = _snap_up(x, grid), _snap_up(y, grid)
    return (nx, ny, max(w - (nx - x), 0), max(h - (ny - y), 0))


def _auto_direction(
    board: Board,
    parent_id: str,
    constraint: tuple[float, float, float, float],
) -> Direction:
    """Wide → LTR, tall/square → TTB."""
    _, _, w, h = constraint
    if parent_id:
        return Direction.LTR if w > h else Direction.TTB
    return Direction.TTB


def _lift(board: Board, element_id: str, target_ids: set[str]) -> str | None:
    """The box among *target_ids* that is *element_id* or holds it, or None.

    An arrow between two boxes inside different sibling containers ranks
    those containers, so a layout ranks within each container by the
    arrows that cross it."""
    seen: set[str] = set()
    eid = element_id
    while eid and eid not in seen:
        if eid in target_ids:
            return eid
        seen.add(eid)
        el = (board.box_by_id(eid) or board.note_by_id(eid)
              or board.image_by_id(eid))
        eid = el.parent if el else ""
    return None


def _build_dag(
    board: Board, target_ids: set[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build adjacency lists from arrows connecting target boxes.

    Returns (adj, reverse_adj). An arrow end inside a target box counts
    for that box; arrows within one target box, and arrows with an end
    outside every target box, are ignored. Parallel arrows count once.
    Cycles are broken via DFS back-edge removal.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    radj: dict[str, list[str]] = defaultdict(list)

    lifted: list[tuple[str, str, Arrow]] = []
    for arrow in board.arrows:
        src = _lift(board, arrow.from_id, target_ids)
        dst = _lift(board, arrow.to_id, target_ids)
        if src is None or dst is None or src == dst:
            continue
        lifted.append((src, dst, arrow))

    out_degree: dict[str, int] = defaultdict(int)
    for src, _dst, _arrow in lifted:
        out_degree[src] += 1

    def _add(u: str, v: str) -> None:
        if v not in adj[u]:
            adj[u].append(v)
            radj[v].append(u)

    for src, dst, arrow in lifted:
        if arrow.head_to and not arrow.head_from:
            # A -> B
            _add(src, dst)
        elif arrow.head_from and not arrow.head_to:
            # A <- B  (reverse)
            _add(dst, src)
        elif arrow.head_from and arrow.head_to:
            # Bidi — pick direction: fewer outgoing source wins
            if out_degree[src] <= out_degree[dst]:
                _add(src, dst)
            else:
                _add(dst, src)
        else:
            # No heads (--), pick alphabetical
            if src < dst:
                _add(src, dst)
            else:
                _add(dst, src)

    # Break cycles via DFS
    _break_cycles(adj, radj, target_ids)
    return adj, radj


def _break_cycles(
    adj: dict[str, list[str]],
    radj: dict[str, list[str]],
    nodes: set[str],
) -> None:
    """Remove back-edges in-place to make the graph acyclic."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in nodes}
    back_edges: list[tuple[str, str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        for v in list(adj.get(u, [])):
            if color.get(v, WHITE) == GRAY:
                back_edges.append((u, v))
            elif color.get(v, WHITE) == WHITE:
                dfs(v)
        color[u] = BLACK

    for n in sorted(nodes):
        if color[n] == WHITE:
            dfs(n)

    for u, v in back_edges:
        if v in adj.get(u, []):
            adj[u].remove(v)
        if u in radj.get(v, []):
            radj[v].remove(u)


def _assign_layers(
    target_ids: set[str],
    adj: dict[str, list[str]],
    radj: dict[str, list[str]],
) -> list[list[str]]:
    """Longest-path layering. Returns list of layers (layer 0 = roots)."""
    # Topological sort (Kahn's algorithm)
    in_degree: dict[str, int] = {n: 0 for n in target_ids}
    for n in target_ids:
        for v in adj.get(n, []):
            if v in in_degree:
                in_degree[v] += 1

    queue = sorted([n for n in target_ids if in_degree[n] == 0])
    topo: list[str] = []
    while queue:
        u = queue.pop(0)
        topo.append(u)
        for v in sorted(adj.get(u, [])):
            if v in in_degree:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

    # Any nodes not in topo (shouldn't happen after cycle breaking) get appended
    remaining = target_ids - set(topo)
    topo.extend(sorted(remaining))

    # Longest path from roots
    depth: dict[str, int] = {}
    for n in topo:
        preds = [depth[p] for p in radj.get(n, []) if p in depth]
        depth[n] = (max(preds) + 1) if preds else 0

    # Group by layer
    max_layer = max(depth.values()) if depth else 0
    layers: list[list[str]] = [[] for _ in range(max_layer + 1)]
    for n, d in depth.items():
        layers[d].append(n)

    return layers


def _order_within_layers(
    layers: list[list[str]],
    adj: dict[str, list[str]],
    board: Board,
    direction: Direction,
    target_ids: set[str],
    box_sizes: dict[str, tuple[float, float]],
) -> list[list[str]]:
    """Order nodes within each layer. Layer 0 by position, rest by barycenter."""
    if not layers:
        return layers

    # Layer 0: sort by current cross-axis position
    def _cross_pos(bid: str) -> float:
        box = board.box_by_id(bid)
        if not box:
            return 0
        return box.x if direction == Direction.TTB else box.y

    layers[0] = sorted(layers[0], key=_cross_pos)

    # Build position index for barycenter
    pos_in_layer: dict[str, int] = {}
    for idx, nid in enumerate(layers[0]):
        pos_in_layer[nid] = idx

    # Layers 1..N: barycenter of predecessors
    for li in range(1, len(layers)):
        def _bary(nid: str) -> float:
            # Find predecessors in previous layers
            preds = []
            for prev_nid, succs in adj.items():
                if nid in succs and prev_nid in pos_in_layer:
                    preds.append(pos_in_layer[prev_nid])
            if preds:
                return sum(preds) / len(preds)
            return _cross_pos(nid)

        layers[li] = sorted(layers[li], key=lambda n: (_bary(n), _cross_pos(n)))
        for idx, nid in enumerate(layers[li]):
            pos_in_layer[nid] = idx

    return layers


def _layer_gaps(
    board: Board,
    layers: list[list[str]],
    direction: Direction,
    target_ids: set[str],
    arrow_label_size: ArrowLabelSizeFn | None,
) -> list[float]:
    """The gap after each layer: the fixed layer gap, or more where an arrow
    between that layer and the next carries a label longer than it — the
    label is drawn at the arrow's middle, which then lands in the gap."""
    gaps = [float(LAYOUT_LAYER_GAP)] * len(layers)
    if arrow_label_size is None:
        return gaps
    layer_of = {nid: li for li, layer in enumerate(layers) for nid in layer}
    for arrow in board.arrows:
        if not arrow.label:
            continue
        src = _lift(board, arrow.from_id, target_ids)
        dst = _lift(board, arrow.to_id, target_ids)
        if src not in layer_of or dst not in layer_of:
            continue
        a, b = sorted((layer_of[src], layer_of[dst]))
        if b - a != 1:
            continue
        w, h = arrow_label_size(arrow)
        along = w if direction == Direction.LTR else h
        need = along + 2 * (_LABEL_GAP_PAD + _LABEL_GAP_STUB)
        gaps[a] = max(gaps[a], need)
    return gaps


def _assign_coordinates(
    layers: list[list[str]],
    direction: Direction,
    constraint: tuple[float, float, float, float],
    grid: float,
    box_sizes: dict[str, tuple[float, float]],
    obstacles: list[Rect] | None = None,
    center_on_widest: bool = False,
    layer_gaps: list[float] | None = None,
) -> dict[str, tuple[float, float]]:
    """Compute final (x, y) positions for all nodes. A node that would
    land on an obstacle (a pinned box) moves along its layer past it,
    and the rest of the layer follows. Each layer is centred on the
    widest one, and that block on the constraint's cross extent — with
    *center_on_widest* it starts at the constraint's edge instead.

    Every step — node to node, layer to layer, a layer's centring offset —
    is a whole number of grid cells, so the gaps come out even and a
    container that grew to fit its children places them the same way on
    the next run. ``layer_gaps[i]`` is the gap after layer *i* (default
    the fixed layer gap)."""
    obstacles = obstacles or []
    cx, cy, cw, ch = constraint
    positions: dict[str, tuple[float, float]] = {}
    ttb = direction == Direction.TTB
    origin = cx if ttb else cy

    def _main(nid: str) -> float:
        return box_sizes.get(nid, (160, 80))[1 if ttb else 0]

    def _cross(nid: str) -> float:
        return box_sizes.get(nid, (160, 80))[0 if ttb else 1]

    def _step(size: float, gap: float) -> float:
        return _snap_up(size + gap, grid)

    def _extent(layer: list[str]) -> float:
        return (sum(_step(_cross(n), LAYOUT_NODE_GAP) for n in layer[:-1])
                + _cross(layer[-1]))

    layers = [layer for layer in layers if layer]
    if not layers:
        return positions
    extents = [_extent(layer) for layer in layers]
    widest = max(extents)
    # The block of layers is centred in the area, each layer in the block.
    avail_cross = widest if center_on_widest else (cw if ttb else ch)
    block_start = max(0.0, _snap((avail_cross - widest) / 2, grid))

    main_cursor = 0.0
    for li, (layer, extent) in enumerate(zip(layers, extents)):
        cross_cursor = block_start + _snap((widest - extent) / 2, grid)

        def _at(cursor: float) -> tuple[float, float]:
            if ttb:
                return _snap(cx + cursor, grid), _snap(cy + main_cursor, grid)
            return _snap(cx + main_cursor, grid), _snap(cy + cursor, grid)

        for ni, nid in enumerate(layer):
            bw, bh = box_sizes.get(nid, (160, 80))
            size = _cross(nid)
            # A node may step back before an obstacle, but not onto the
            # previous node of its layer or before the area's edge.
            floor = 0.0 if ni == 0 else cross_cursor
            while True:
                x, y = _at(cross_cursor)
                hit = _blocking((x, y, bw, bh), obstacles)
                if hit is None:
                    break
                ox, oy, ow, oh = hit
                o_start, o_len = (ox, ow) if ttb else (oy, oh)
                forward = max(cross_cursor + 1, _snap_up(
                    o_start + o_len + LAYOUT_NODE_GAP - origin, grid))
                back = _snap_down(o_start - LAYOUT_NODE_GAP - size - origin, grid)
                if (floor <= back < cross_cursor
                        and cross_cursor - back < forward - cross_cursor
                        and _blocking((*_at(back), bw, bh), obstacles) is None):
                    cross_cursor = back
                else:
                    cross_cursor = forward
            positions[nid] = (x, y)
            cross_cursor += _step(size, LAYOUT_NODE_GAP)

        gap = (layer_gaps[li] if layer_gaps and li < len(layer_gaps)
               else LAYOUT_LAYER_GAP)
        main_cursor += _step(max(_main(n) for n in layer), gap)

    return positions


def _snap_up(value: float, grid: float) -> float:
    """Snap a length up to whole grid cells."""
    if grid <= 0:
        return value
    return math.ceil(value / grid - 1e-9) * grid


def _snap_down(value: float, grid: float) -> float:
    """Snap a coordinate to the grid point at or below it."""
    if grid <= 0:
        return value
    return math.floor(value / grid) * grid


def _snap(value: float, grid: float) -> float:
    """Snap a coordinate to the nearest grid point."""
    if grid <= 0:
        return value
    return round(value / grid) * grid
