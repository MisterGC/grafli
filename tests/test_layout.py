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
    container_groups,
    layout_groups,
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


class TestLayoutGroups:
    """The whole-board driver the app's `=` and `grafli layout` share."""

    def test_container_groups_recurse(self):
        board = _make_board([
            _box("P", 0, 0, 400, 300), _box("a"), _box("b"), _box("c"),
        ])
        board.box_by_id("a").parent = "P"
        board.box_by_id("b").parent = "P"
        groups = container_groups(board)
        assert groups == [("", {"P", "c"}), ("P", {"a", "b"})]

    def test_container_grows_and_carries_children(self):
        p = _box("P", 0, 0, 100, 300)  # tall: children flow top-down
        a, b = _box("a", 500, 500), _box("b", 600, 500)
        a.parent = b.parent = "P"
        board = _make_board([p, a, b, _box("Q", 0, 600)],
                            [_arrow("a", "b"), _arrow("P", "Q")])
        layout_groups(board, container_groups(board), 20, lambda pid: 20)
        # a above b inside P, P above Q, P grown to hold both children
        assert a.y < b.y
        assert p.y + p.h <= board.box_by_id("Q").y
        for c in (a, b):
            assert p.x <= c.x and c.x + c.w <= p.x + p.w
            assert p.y + 20 <= c.y and c.y + c.h <= p.y + p.h

    def test_top_level_container_grows_before_root_is_placed(self):
        # P must grow to hold its children before its root sibling Q is
        # placed below it, or Q lands inside P's grown area.
        p = _box("P", 0, 0, 400, 100)
        a, b = _box("a"), _box("b")
        a.parent = b.parent = "P"
        board = _make_board([p, a, b, _box("Q")],
                            [_arrow("a", "b"), _arrow("P", "Q")])
        layout_groups(board, container_groups(board), 20, lambda pid: 20,
                      Direction.TTB)
        assert p.y + p.h <= board.box_by_id("Q").y


class TestRankWithinContainers:
    """An arrow between boxes in two sibling containers ranks the containers."""

    def _board(self) -> Board:
        boxes = [_box("X", 0, 0, 400, 200), _box("Y", 0, 0, 400, 200),
                 _box("x1"), _box("y1"), _box("y2")]
        board = _make_board(boxes, [_arrow("y1", "x1"), _arrow("y2", "x1"),
                                    _arrow("y1", "y2")])
        board.box_by_id("x1").parent = "X"
        board.box_by_id("y1").parent = "Y"
        board.box_by_id("y2").parent = "Y"
        return board

    def test_descendant_arrow_ranks_siblings(self):
        adj, _ = _build_dag(self._board(), {"X", "Y"})
        assert adj["Y"] == ["X"]

    def test_arrow_within_one_container_is_ignored_above_it(self):
        board = self._board()
        board.arrows = [_arrow("y1", "y2")]
        adj, _ = _build_dag(board, {"X", "Y"})
        assert not any(adj.values())

    def test_layout_puts_source_container_first(self):
        board = self._board()
        layout_groups(board, container_groups(board), 20, lambda pid: 20,
                      Direction.TTB)
        X, Y = board.box_by_id("X"), board.box_by_id("Y")
        assert Y.y + Y.h <= X.y


def _overlaps(a: Box, b: Box) -> bool:
    return (a.x < b.x + b.w and b.x < a.x + a.w
            and a.y < b.y + b.h and b.y < a.y + a.h)


class TestPinned:
    """A `!pin` box keeps its position; the others are placed around it."""

    def test_pinned_box_keeps_its_position(self):
        pin = _box("B", 333, 777)
        pin.pinned = True
        board = _make_board([_box("A"), pin, _box("C", 0, 300)],
                            [_arrow("A", "B"), _arrow("B", "C")])
        result = compute_layout(board, {"A", "B", "C"}, "", Direction.TTB,
                                20, 0, _sizes("A", "B", "C"))
        assert "B" not in result
        assert set(result) == {"A", "C"}

    def test_free_boxes_move_past_a_pinned_box(self):
        pin = _box("P", 0, 0)
        pin.pinned = True
        free = [_box(b, 0, 0) for b in ("A", "B", "C")]
        board = _make_board([pin, *free])
        layout_groups(board, container_groups(board), 20, lambda pid: 0,
                      Direction.TTB)
        assert (pin.x, pin.y) == (0, 0)
        for b in free:
            assert not _overlaps(b, pin)
        for i, a in enumerate(free):
            for b in free[i + 1:]:
                assert not _overlaps(a, b)

    def test_pinned_container_still_lays_out_its_children(self):
        p = _box("P", 100, 100, 400, 400)
        p.pinned = True
        a, b = _box("a", 400, 400), _box("b", 100, 100)
        a.parent = b.parent = "P"
        board = _make_board([p, a, b, _box("Q", 900, 0)],
                            [_arrow("a", "b"), _arrow("Q", "P")])
        layout_groups(board, container_groups(board), 20, lambda pid: 20,
                      Direction.TTB)
        assert (p.x, p.y) == (100, 100)
        assert a.y < b.y

    def test_pinned_child_moves_with_its_container(self):
        p = _box("P", 500, 500, 400, 300)
        c = _box("c", 540, 560)
        c.parent = "P"
        c.pinned = True
        board = _make_board([_box("Q"), p, c], [_arrow("Q", "P")])
        layout_groups(board, container_groups(board), 20, lambda pid: 20,
                      Direction.TTB)
        assert (c.x - p.x, c.y - p.y) == (40, 60)


class TestStableRerun:
    """A second layout run over a laid-out board moves nothing."""

    def test_root_layout_is_stable(self):
        board = _make_board(
            [_box("A", 300, 0), _box("B", 0, 400), _box("C", 900, 400),
             _box("D", 500, 900, 300, 120)],
            [_arrow("A", "B"), _arrow("A", "C"), _arrow("B", "D")],
        )
        layout_groups(board, container_groups(board), 20, lambda pid: 0)
        first = [(b.x, b.y, b.w, b.h) for b in board.boxes]
        layout_groups(board, container_groups(board), 20, lambda pid: 0)
        assert [(b.x, b.y, b.w, b.h) for b in board.boxes] == first

    def test_root_layout_keeps_the_top_left_corner(self):
        board = _make_board([_box("A", 300, 100), _box("B", 100, 500)],
                            [_arrow("A", "B")])
        layout_groups(board, container_groups(board), 20, lambda pid: 0)
        assert min(b.x for b in board.boxes) == 100
        assert min(b.y for b in board.boxes) == 100
