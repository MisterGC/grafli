"""Headless tests for the Level-of-Detail structural model (grafli/lod.py)."""

from __future__ import annotations

from grafli.format import parse
from grafli.lod import (
    CHILD_COLLAPSE_PX,
    CHILD_EXPAND_PX,
    COLLAPSE_PX,
    EXPAND_PX,
    LodModel,
    ContainerSummary,
    should_collapse,
    should_collapse_container,
)

# A compact stand-in for the demo board: two top-level containers (one with a
# nested sub-container), plus a parent-less three-node mesh and a lone orphan.
SAMPLE = """\
@ box backend "Backend" 400,0 560x620 !flat
@ box api "API" 440,80 220x480 !flat >backend
@ box api_gw "Gateway" 460,140 180x70 >api
@ box api_rest "REST" 460,240 180x70 >api
@ box storage "Storage" 1100,0 320x300 !flat
@ box st_pg "Postgres" 1140,80 240x80 >storage
@ box st_redis "Redis" 1140,180 240x80 >storage
@ box obs_a "A" 0,800 160x70
@ box obs_b "B" 250,800 160x70
@ box obs_c "C" 500,800 160x70
@ box orphan "Orphan" 0,1000 160x70
@ arrow api_gw -> api_rest "route"
@ arrow api_rest -> st_pg "sql"
@ arrow obs_a -- obs_b
@ arrow obs_b -- obs_c
"""


def _model() -> LodModel:
    return LodModel.from_board(parse(SAMPLE))


# ── hierarchy ───────────────────────────────────────────────────────────

def test_containers_detected():
    m = _model()
    assert m.containers == {"backend", "api", "storage"}
    assert m.is_container("backend") and not m.is_container("api_gw")


def test_ancestors_walk_up_the_nesting():
    m = _model()
    assert m.ancestors("api_gw") == ["api", "backend"]
    assert m.ancestors("st_pg") == ["storage"]
    assert m.ancestors("backend") == []


def test_descendants_are_recursive():
    m = _model()
    # backend > api > {api_gw, api_rest}, plus api itself
    assert set(m.descendants("backend")) == {"api", "api_gw", "api_rest"}
    assert set(m.descendants("api")) == {"api_gw", "api_rest"}
    assert m.descendants("api_gw") == []


# ── loose nodes / components ────────────────────────────────────────────

def test_loose_set_excludes_containers_and_nested():
    m = _model()
    # Parent-less, non-container boxes only.
    assert m.loose == {"obs_a", "obs_b", "obs_c", "orphan"}


def test_connected_components_find_the_mesh_and_the_orphan():
    m = _model()
    comps = sorted((sorted(c) for c in m.components), key=len, reverse=True)
    assert comps[0] == ["obs_a", "obs_b", "obs_c"]   # the linked mesh
    assert ["orphan"] in [sorted(c) for c in m.components]  # degree-0 island


# ── proxy / selection & arrow re-routing ────────────────────────────────

def test_proxy_resolves_to_the_real_backing_element():
    m = _model()
    # A container tile is its own parent box — selection hits a real element.
    assert m.proxy_backing("backend") == "backend"


def test_resolve_visible_routes_to_outermost_collapsed_ancestor():
    m = _model()
    # Child of a collapsed sub-container -> the sub-container tile.
    assert m.resolve_visible("api_gw", {"api"}) == "api"
    # Both nested levels collapsed -> the outermost (backend) tile.
    assert m.resolve_visible("api_gw", {"api", "backend"}) == "backend"
    # Only the outer collapsed -> outer tile.
    assert m.resolve_visible("api_gw", {"backend"}) == "backend"
    # Nothing collapsed -> the element stays visible.
    assert m.resolve_visible("api_gw", set()) == "api_gw"
    # A collapsed element resolves to itself (it is the tile).
    assert m.resolve_visible("storage", {"storage"}) == "storage"


# ── summaries ───────────────────────────────────────────────────────────

def test_summary_reports_counts_and_a_covering_rect():
    m = _model()
    s = m.summary("backend")
    assert isinstance(s, ContainerSummary)
    assert s.label == "Backend"
    assert s.direct_children == 1          # just the API sub-container
    assert s.descendants == 3              # api + api_gw + api_rest
    x, y, w, h = s.rect
    # The aggregate rect must cover the deepest child (api_gw at 460,140 ..).
    assert x <= 460 and y <= 140
    assert x + w >= 460 + 180 and y + h >= 140 + 70


def test_summary_is_cached():
    m = _model()
    assert m.summary("api") is m.summary("api")


# ── tier hysteresis ─────────────────────────────────────────────────────

def test_should_collapse_is_hysteretic():
    # Below the collapse floor -> collapse regardless of prior state.
    assert should_collapse(COLLAPSE_PX - 1, was_collapsed=False)
    assert should_collapse(COLLAPSE_PX - 1, was_collapsed=True)
    # Comfortably legible -> expanded regardless.
    assert not should_collapse(EXPAND_PX + 1, was_collapsed=False)
    assert not should_collapse(EXPAND_PX + 1, was_collapsed=True)
    # In the dead band the previous state sticks (no flicker).
    mid = (COLLAPSE_PX + EXPAND_PX) / 2
    assert should_collapse(mid, was_collapsed=True)
    assert not should_collapse(mid, was_collapsed=False)


def test_child_extent_drives_innermost_first_collapse():
    m = _model()
    # api's children are leaf boxes (180x70 -> shorter side 70); backend's direct
    # children are the big API sub-container (220x480 -> 220). The bigger extent
    # crosses the collapse floor later, so backend collapses AFTER api.
    assert m.child_extent("api") == 70.0
    assert m.child_extent("backend") == 220.0
    assert m.child_extent("api") < m.child_extent("backend")
    # A container with no sized children never collapses on size alone.
    assert m.child_extent("api_gw") == float("inf")


def test_should_collapse_container_is_hysteretic():
    assert should_collapse_container(CHILD_COLLAPSE_PX - 1, False)
    assert not should_collapse_container(CHILD_EXPAND_PX + 1, True)
    mid = (CHILD_COLLAPSE_PX + CHILD_EXPAND_PX) / 2
    assert should_collapse_container(mid, was_collapsed=True)
    assert not should_collapse_container(mid, was_collapsed=False)


def test_demo_board_parses_and_models_cleanly():
    # Guard that the shipped example stays LoD-meaningful.
    m = LodModel.from_board(parse(open("examples/lod-demo.grafli").read()))
    assert {"frontend", "backend", "api", "workers", "storage"} <= m.containers
    assert m.ancestors("api_gw") == ["api", "backend"]   # 3-level nesting
    # The observability mesh is one parent-less component of six.
    biggest = max(m.components, key=len)
    assert len(biggest) == 6
    assert all(n.startswith("obs_") for n in biggest)
