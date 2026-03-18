"""Tests for grafli.layout — auto-layout algorithm."""

from grafli.format import Arrow, Board, Box
from grafli.layout import (
    Direction,
    _assign_layers,
    _auto_direction,
    _break_cycles,
    _build_dag,
    _snap,
    compute_layout,
)


def _make_board(boxes: list[Box], arrows: list[Arrow] | None = None) -> Board:
    board = Board()
    for b in boxes:
        board.add_box(b)
    for a in (arrows or []):
        board.add_arrow(a)
    return board


def _box(bid: str, x: float = 0, y: float = 0, w: float = 160, h: float = 80) -> Box:
    return Box(id=bid, label=bid, x=x, y=y, w=w, h=h)


def _arrow(src: str, dst: str) -> Arrow:
    return Arrow(from_id=src, to_id=dst)


def _sizes(*bids: str) -> dict[str, tuple[float, float]]:
    return {bid: (160, 80) for bid in bids}


class TestSnap:
    def test_snap_to_grid(self):
        assert _snap(23, 20) == 20
        assert _snap(30, 20) == 40
        assert _snap(10, 20) == 0
        assert _snap(11, 20) == 20

    def test_snap_zero_grid(self):
        assert _snap(23, 0) == 23


class TestLinearChain:
    """A -> B -> C should produce 3 layers."""

    def test_three_layers(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("C")],
            [_arrow("A", "B"), _arrow("B", "C")],
        )
        ids = {"A", "B", "C"}
        adj, radj = _build_dag(board, ids)
        layers = _assign_layers(ids, adj, radj)
        assert len(layers) == 3
        assert layers[0] == ["A"]
        assert layers[1] == ["B"]
        assert layers[2] == ["C"]

    def test_positions_ttb(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("C")],
            [_arrow("A", "B"), _arrow("B", "C")],
        )
        ids = {"A", "B", "C"}
        sizes = _sizes("A", "B", "C")
        result = compute_layout(board, ids, "", Direction.TTB, 20, 0, sizes)
        assert len(result) == 3
        # All same x (single node per layer, centered)
        assert result["A"][0] == result["B"][0] == result["C"][0]
        # y increases
        assert result["A"][1] < result["B"][1] < result["C"][1]


class TestDiamond:
    """A -> {B, C} -> D should produce layers [A], [B,C], [D]."""

    def test_layers(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("C"), _box("D")],
            [_arrow("A", "B"), _arrow("A", "C"), _arrow("B", "D"), _arrow("C", "D")],
        )
        ids = {"A", "B", "C", "D"}
        adj, radj = _build_dag(board, ids)
        layers = _assign_layers(ids, adj, radj)
        assert len(layers) == 3
        assert layers[0] == ["A"]
        assert set(layers[1]) == {"B", "C"}
        assert layers[2] == ["D"]


class TestCycleBreaking:
    """A -> B -> C -> A — all nodes should be layered after cycle breaking."""

    def test_all_layered(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("C")],
            [_arrow("A", "B"), _arrow("B", "C"), _arrow("C", "A")],
        )
        ids = {"A", "B", "C"}
        adj, radj = _build_dag(board, ids)
        layers = _assign_layers(ids, adj, radj)
        all_nodes = {n for layer in layers for n in layer}
        assert all_nodes == ids

    def test_cycle_break_removes_back_edge(self):
        adj = {"A": ["B"], "B": ["C"], "C": ["A"]}
        radj = {"B": ["A"], "C": ["B"], "A": ["C"]}
        _break_cycles(adj, radj, {"A", "B", "C"})
        # Should be acyclic now — verify no cycle via DFS
        visited = set()
        stack = set()

        def has_cycle(n):
            visited.add(n)
            stack.add(n)
            for v in adj.get(n, []):
                if v in stack:
                    return True
                if v not in visited and has_cycle(v):
                    return True
            stack.discard(n)
            return False

        assert not any(has_cycle(n) for n in {"A", "B", "C"} if n not in visited)


class TestDisconnectedComponents:
    """Two independent chains should tile side-by-side."""

    def test_both_groups_placed(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("X"), _box("Y")],
            [_arrow("A", "B"), _arrow("X", "Y")],
        )
        ids = {"A", "B", "X", "Y"}
        sizes = _sizes("A", "B", "X", "Y")
        result = compute_layout(board, ids, "", Direction.TTB, 20, 0, sizes)
        assert len(result) == 4
        # All should have valid positions
        for pos in result.values():
            assert isinstance(pos[0], float) or isinstance(pos[0], int)


class TestIsolatedNodes:
    """Nodes with no arrows should be placed."""

    def test_isolated_placed(self):
        board = _make_board(
            [_box("A"), _box("B"), _box("C")],
            [],
        )
        ids = {"A", "B", "C"}
        sizes = _sizes("A", "B", "C")
        result = compute_layout(board, ids, "", Direction.TTB, 20, 0, sizes)
        assert len(result) == 3


class TestParentConstraint:
    """Positions should be >= parent origin and grid-snapped."""

    def test_within_parent(self):
        parent = _box("parent", x=100, y=100, w=600, h=400)
        child1 = Box(id="c1", label="c1", x=0, y=0, w=160, h=80, parent="parent")
        child2 = Box(id="c2", label="c2", x=0, y=0, w=160, h=80, parent="parent")
        board = _make_board(
            [parent, child1, child2],
            [_arrow("c1", "c2")],
        )
        ids = {"c1", "c2"}
        sizes = {"c1": (160, 80), "c2": (160, 80)}
        result = compute_layout(
            board, ids, "parent", Direction.TTB, 20, 30, sizes,
        )
        for bid, (x, y) in result.items():
            assert x >= 100  # >= parent.x
            assert y >= 100  # >= parent.y
            # Grid-snapped
            assert x % 20 == 0
            assert y % 20 == 0

    def test_no_scaling_small_parent(self):
        """Children in a small parent are NOT scaled — they keep natural gaps."""
        parent = _box("parent", x=0, y=0, w=200, h=100)
        child1 = Box(id="c1", label="c1", x=0, y=0, w=160, h=80, parent="parent")
        child2 = Box(id="c2", label="c2", x=0, y=0, w=160, h=80, parent="parent")
        child3 = Box(id="c3", label="c3", x=0, y=0, w=160, h=80, parent="parent")
        board = _make_board(
            [parent, child1, child2, child3],
            [_arrow("c1", "c2"), _arrow("c2", "c3")],
        )
        ids = {"c1", "c2", "c3"}
        sizes = {"c1": (160, 80), "c2": (160, 80), "c3": (160, 80)}
        result = compute_layout(
            board, ids, "parent", Direction.TTB, 20, 30, sizes,
        )
        # Natural gap between layers is LAYOUT_LAYER_GAP (40px).
        # Positions must NOT be compressed — successive y offsets >= box height + gap.
        ys = sorted(result[bid][1] for bid in ids)
        for i in range(1, len(ys)):
            assert ys[i] - ys[i - 1] >= 80 + 40  # box_h + LAYOUT_LAYER_GAP


class TestDirectionAutoDetect:
    """Wide parent → LTR, tall parent → TTB."""

    def test_wide_parent_ltr(self):
        parent = _box("p", w=800, h=200)
        board = _make_board([parent])
        constraint = (20, 50, 760, 150)  # wide
        d = _auto_direction(board, "p", constraint)
        assert d == Direction.LTR

    def test_tall_parent_ttb(self):
        parent = _box("p", w=200, h=800)
        board = _make_board([parent])
        constraint = (20, 50, 160, 730)  # tall
        d = _auto_direction(board, "p", constraint)
        assert d == Direction.TTB


class TestEdgeCases:
    def test_empty_target(self):
        board = _make_board([])
        result = compute_layout(board, set(), "", None, 20, 0, {})
        assert result == {}

    def test_single_box_no_parent(self):
        board = _make_board([_box("A")])
        sizes = _sizes("A")
        result = compute_layout(board, {"A"}, "", None, 20, 0, sizes)
        assert result == {}  # single box, no parent → unchanged

    def test_single_box_with_parent(self):
        parent = _box("p", x=100, y=100, w=400, h=300)
        child = Box(id="c", label="c", x=0, y=0, w=160, h=80, parent="p")
        board = _make_board([parent, child])
        sizes = {"c": (160, 80)}
        result = compute_layout(board, {"c"}, "p", None, 20, 30, sizes)
        assert "c" in result
        assert result["c"][0] % 20 == 0
        assert result["c"][1] % 20 == 0


class TestReverseArrow:
    """A <- B should treat B as the source."""

    def test_reverse_arrow_layers(self):
        board = _make_board(
            [_box("A"), _box("B")],
            [Arrow(from_id="A", to_id="B", head_from=True, head_to=False)],
        )
        ids = {"A", "B"}
        adj, radj = _build_dag(board, ids)
        layers = _assign_layers(ids, adj, radj)
        # B is the source (has arrow pointing to A)
        assert layers[0] == ["B"]
        assert layers[1] == ["A"]
