"""Pure layout algorithm for auto-arranging boxes. No Qt dependency."""

from __future__ import annotations

import enum
from collections import defaultdict

from grafli.constants import LAYOUT_LAYER_GAP, LAYOUT_NODE_GAP, LAYOUT_PADDING
from grafli.format import Board


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
    """Return {box_id: (new_x, new_y)} for each box in target_ids."""
    if not target_ids:
        return {}
    if len(target_ids) == 1:
        return _layout_single(board, target_ids, parent_id, grid, label_height, box_sizes)

    constraint = _constraint_rect(board, target_ids, parent_id, label_height, box_sizes)
    if direction is None:
        direction = _auto_direction(board, parent_id, constraint)

    adj, radj = _build_dag(board, target_ids)
    layers = _assign_layers(target_ids, adj, radj)
    layers = _order_within_layers(layers, adj, board, direction, target_ids, box_sizes)
    positions = _assign_coordinates(layers, direction, constraint, grid, box_sizes)
    return positions


# ── Internals ────────────────────────────────────────────────────


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


def _build_dag(
    board: Board, target_ids: set[str],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build adjacency lists from arrows connecting target boxes.

    Returns (adj, reverse_adj). Cycles are broken via DFS back-edge removal.
    Self-loops and arrows outside target_ids are ignored.
    """
    adj: dict[str, list[str]] = defaultdict(list)
    radj: dict[str, list[str]] = defaultdict(list)

    for arrow in board.arrows:
        src, dst = arrow.from_id, arrow.to_id
        if src == dst:
            continue
        if src not in target_ids or dst not in target_ids:
            continue

        if arrow.head_to and not arrow.head_from:
            # A -> B
            adj[src].append(dst)
            radj[dst].append(src)
        elif arrow.head_from and not arrow.head_to:
            # A <- B  (reverse)
            adj[dst].append(src)
            radj[src].append(dst)
        elif arrow.head_from and arrow.head_to:
            # Bidi — pick direction: fewer outgoing source wins
            out_src = sum(1 for a in board.arrows if a.from_id == src and a.to_id in target_ids)
            out_dst = sum(1 for a in board.arrows if a.from_id == dst and a.to_id in target_ids)
            if out_src <= out_dst:
                adj[src].append(dst)
                radj[dst].append(src)
            else:
                adj[dst].append(src)
                radj[src].append(dst)
        else:
            # No heads (--), pick alphabetical
            if src < dst:
                adj[src].append(dst)
                radj[dst].append(src)
            else:
                adj[dst].append(src)
                radj[src].append(dst)

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
) -> dict[str, tuple[float, float]]:
    """Compute final (x, y) positions for all nodes."""
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

            if direction == Direction.TTB:
                x = cx + cross_cursor
                y = cy + main_cursor
            else:
                x = cx + main_cursor
                y = cy + cross_cursor

            x = _snap(x, grid)
            y = _snap(y, grid)
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
