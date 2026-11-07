"""Pure layout algorithm for auto-arranging boxes. No Qt dependency."""

from __future__ import annotations

import enum
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
) -> dict[str, tuple[float, float]]:
    """Return {box_id: (new_x, new_y)} for each box in target_ids.

    A pinned box (``!pin``) gets no entry: it stays where it is, and the
    other boxes are placed around it."""
    pinned = {bid for bid in target_ids
              if (box := board.box_by_id(bid)) and box.pinned}
    obstacles = [_rect_of(board, bid, box_sizes) for bid in sorted(pinned)]
    target_ids = target_ids - pinned
    if not target_ids:
        return {}
    if len(target_ids) == 1 and not obstacles:
        return _layout_single(board, target_ids, parent_id, grid, label_height, box_sizes)

    constraint = _constraint_rect(board, target_ids, parent_id, label_height, box_sizes)
    if direction is None:
        direction = _auto_direction(board, parent_id, constraint)

    adj, radj = _build_dag(board, target_ids)
    layers = _assign_layers(target_ids, adj, radj)
    layers = _order_within_layers(layers, adj, board, direction, target_ids, box_sizes)
    positions = _assign_coordinates(layers, direction, constraint, grid, box_sizes,
                                    obstacles)
    return positions


# ── Whole-board driver ──────────────────────────────────────────

# The label band above a container's children, by container id ("" = the
# board root, which has none). The app measures its label; headless callers
# use the documented margin model.
LabelHeightFn = Callable[[str], float]


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
) -> None:
    """Lay out each group in place, deepest container first, so a
    container has grown to fit its children before its own siblings are
    placed. Moving a box moves its descendants and parented notes along."""
    groups = sorted(groups, key=lambda g: -_depth(board, g[0]))
    for parent_id, child_ids in groups:
        _layout_group(board, parent_id, child_ids, grid,
                      label_height(parent_id) if parent_id else 0.0,
                      direction)


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
) -> None:
    box_sizes: dict[str, tuple[float, float]] = {}
    for cid in child_ids:
        box = board.box_by_id(cid)
        if box:
            box_sizes[cid] = (box.w, box.h)

    new_positions = compute_layout(
        board, child_ids, parent_id, direction, grid, label_height, box_sizes,
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
            if needed_w > parent.w:
                parent.w = _snap(needed_w, grid)
            if needed_h > parent.h:
                parent.h = _snap(needed_h, grid)

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
    """Move all descendants and parented notes of *box_id* by (dx, dy)."""
    for box in board.boxes:
        if box.parent == box_id:
            box.x += dx
            box.y += dy
            _propagate_delta(board, box.id, dx, dy)
    for note in board.notes:
        if note.parent == box_id:
            note.x += dx
            note.y += dy


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
    cx = _snap(cx, grid)
    cy = _snap(cy, grid)
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


def _assign_coordinates(
    layers: list[list[str]],
    direction: Direction,
    constraint: tuple[float, float, float, float],
    grid: float,
    box_sizes: dict[str, tuple[float, float]],
    obstacles: list[Rect] | None = None,
) -> dict[str, tuple[float, float]]:
    """Compute final (x, y) positions for all nodes. A node that would
    land on an obstacle (a pinned box) moves along its layer past it,
    and the rest of the layer follows."""
    obstacles = obstacles or []
    cx, cy, cw, ch = constraint
    positions: dict[str, tuple[float, float]] = {}

    if not layers:
        return positions

    # Find disconnected components by grouping layers
    # (already handled by layering — all in one set of layers)

    # Compute layer sizes
    layer_main_sizes: list[float] = []  # size along main axis (max node size)
    layer_cross_sizes: list[float] = []  # total size along cross axis

    for layer in layers:
        if not layer:
            layer_main_sizes.append(0)
            layer_cross_sizes.append(0)
            continue

        if direction == Direction.TTB:
            main_sizes = [box_sizes.get(n, (160, 80))[1] for n in layer]
            cross_sizes = [box_sizes.get(n, (160, 80))[0] for n in layer]
        else:
            main_sizes = [box_sizes.get(n, (160, 80))[0] for n in layer]
            cross_sizes = [box_sizes.get(n, (160, 80))[1] for n in layer]

        layer_main_sizes.append(max(main_sizes))
        total_cross = sum(cross_sizes) + LAYOUT_NODE_GAP * (len(layer) - 1)
        layer_cross_sizes.append(total_cross)

    # Total main-axis span
    total_main = sum(layer_main_sizes) + LAYOUT_LAYER_GAP * max(len(layers) - 1, 0)
    max_cross = max(layer_cross_sizes) if layer_cross_sizes else 0

    if direction == Direction.TTB:
        avail_cross = cw
    else:
        avail_cross = ch

    effective_layer_gap = LAYOUT_LAYER_GAP
    effective_node_gap = LAYOUT_NODE_GAP

    # Place layers
    main_cursor = 0.0
    for li, layer in enumerate(layers):
        if not layer:
            continue

        if direction == Direction.TTB:
            cross_sizes = [box_sizes.get(n, (160, 80))[0] for n in layer]
        else:
            cross_sizes = [box_sizes.get(n, (160, 80))[1] for n in layer]

        total_cross_layer = sum(cross_sizes) + effective_node_gap * max(len(layer) - 1, 0)

        # Center the layer on the cross axis within constraint
        cross_start = (avail_cross - total_cross_layer) / 2 if avail_cross > 0 else 0
        cross_start = max(0, cross_start)
        cross_cursor = cross_start

        for ni, nid in enumerate(layer):
            bw, bh = box_sizes.get(nid, (160, 80))

            while True:
                if direction == Direction.TTB:
                    x = cx + cross_cursor
                    y = cy + main_cursor
                else:
                    x = cx + main_cursor
                    y = cy + cross_cursor

                x = _snap(x, grid)
                y = _snap(y, grid)
                hit = _blocking((x, y, bw, bh), obstacles)
                if hit is None:
                    break
                ox, oy, ow, oh = hit
                past = (ox + ow - cx if direction == Direction.TTB
                        else oy + oh - cy) + effective_node_gap
                cross_cursor = max(cross_cursor + 1, past)
            positions[nid] = (x, y)

            if direction == Direction.TTB:
                cross_cursor += bw + effective_node_gap
            else:
                cross_cursor += bh + effective_node_gap

        main_cursor += layer_main_sizes[li] + effective_layer_gap

    return positions


def _snap(value: float, grid: float) -> float:
    """Snap a coordinate to the nearest grid point."""
    if grid <= 0:
        return value
    return round(value / grid) * grid
