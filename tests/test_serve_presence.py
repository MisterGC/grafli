"""Presence in grafli serve: named cursors, the laser, the presenter's view,
who follows, and the presenter going to another board — over a real server
and WebSocket clients standing in for tabs. None of it touches the file."""

from __future__ import annotations

import json
import os
import time

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
websockets_sync = pytest.importorskip("websockets.sync.client")

from grafli.serve import presence  # noqa: E402
from tests.test_serve import BOARD, Served, Tab  # noqa: E402


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path_factory.mktemp("presence"))
    yield s
    s.stop()


@pytest.fixture
def board(served, request):
    name = request.node.name.replace("[", "_").strip("]")
    path = served.root / f"{name}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    return path


class Peer(Tab):
    """A tab whose hello may carry a name and whether it follows."""

    def __init__(self, served, board, key, **hello):
        self._conn = websockets_sync.connect(served.url(board), max_size=None)
        self.ws = self._conn.__enter__()
        self.ws.send(json.dumps({"t": "hello", "key": key, **hello}))
        self.next_id = 1
        self.frames = []
        self.seen = []
        welcome = self.recv()
        assert welcome["t"] == "welcome"
        self.id = welcome["id"]
        self.role = welcome["role"]
        self.recv_until("frame")

    def recv(self, timeout=10):
        msg = super().recv(timeout)
        self.seen.append(msg)
        return msg

    def post(self, **msg):
        self.ws.send(json.dumps(msg))

    def until(self, pred, timeout=10):
        """The first message from now on for which *pred* is true."""
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("no such message")
            msg = self.recv(left)
            if pred(msg):
                return msg

    def quiet(self, s=0.4):
        """Every message in the next *s* seconds."""
        got = []
        deadline = time.monotonic() + s
        while (left := deadline - time.monotonic()) > 0:
            try:
                got.append(self.recv(left))
            except TimeoutError:
                break
        return got

    def peers(self, pred=lambda m: True):
        return self.until(lambda m: m["t"] == "peers" and pred(m))


def _keys(served):
    return served.keys.presenter, served.keys.editor, served.keys.viewer


def _names(msg):
    return [p["name"] for p in msg["peers"]]


# ── Unit: what a presence message may carry ──

def test_a_name_is_one_short_line_of_printable_text():
    assert presence.clean_name("  Anna \n Berg\t") == "Anna Berg"
    assert presence.clean_name("x" * 100) == "x" * presence.MAX_NAME_CHARS
    assert presence.clean_name("‮evil\u0000") == "evil"
    assert presence.clean_name(42) == "" and presence.clean_name("   ") == ""


def test_a_point_and_a_view_are_finite_numbers_on_a_board():
    assert presence.point({"x": 1, "y": 2.555}) == {"x": 1.0, "y": 2.56}
    assert presence.point({"off": True}) == {"off": True}
    for bad in ({"x": 1}, {"x": "1", "y": 2}, {"x": True, "y": 2},
                {"x": float("nan"), "y": 0}, {"x": 1e9, "y": 0}):
        assert presence.point(bad) is None, bad
    assert presence.view({"x": -5, "y": 0, "w": 800, "h": 600}) == {
        "x": -5.0, "y": 0.0, "w": 800.0, "h": 600.0}
    for bad in ({"x": 0, "y": 0, "w": 0, "h": 10},
                {"x": 0, "y": 0, "w": -1, "h": 10},
                {"x": 0, "y": 0, "w": float("inf"), "h": 10}):
        assert presence.view(bad) is None, bad


def test_the_rate_limit_lets_a_burst_through_then_the_steady_rate():
    now = [0.0]
    bucket = presence.Bucket(rate=10, burst=5, clock=lambda: now[0])
    assert [bucket.take() for _ in range(7)] == [True] * 5 + [False] * 2
    now[0] += 0.25
    assert [bucket.take() for _ in range(3)] == [True, True, False]


# ── Over the socket ──

def test_every_tab_is_named_and_coloured_and_the_presenter_leads(served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present, name="Serein")
    a = Peer(served, board.stem, edit, name="Anna")
    w = Peer(served, board.stem, watch)
    msg = p.peers(lambda m: len(m["peers"]) == 3)
    assert msg["you"] == p.id and msg["lead"] == p.id
    assert _names(msg) == ["Serein", "Anna", "Guest 2"]
    roles = {x["id"]: (x["role"], x["color"]) for x in msg["peers"]}
    assert roles[p.id] == ("presenter", presence.PRESENTER_COLOR)
    assert roles[a.id] == ("editor", presence.GUEST_COLORS[0])
    assert roles[w.id] == ("viewer", presence.GUEST_COLORS[1])
    w.close()
    assert len(p.peers(lambda m: len(m["peers"]) == 2)["peers"]) == 2
    for tab in (p, a):
        tab.close()


def test_a_cursor_reaches_the_other_tabs_and_not_its_own(served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present, author="presenter-token")
    w = Peer(served, board.stem, watch)
    p.post(t="cursor", x=120.5, y=-40)
    got = w.until(lambda m: m["t"] == "cursor")
    assert got == {"t": "cursor", "id": p.id, "x": 120.5, "y": -40.0}
    p.post(t="cursor", off=True)
    assert w.until(lambda m: m["t"] == "cursor") == {"t": "cursor", "id": p.id,
                                                       "off": True}
    assert not [m for m in p.quiet() if m["t"] == "cursor"]
    assert "presenter-token" not in json.dumps(w.seen)
    p.close()
    w.close()


def test_the_laser_reaches_every_other_tab_and_goes_off(served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present)
    a = Peer(served, board.stem, edit)
    w = Peer(served, board.stem, watch)
    # A guest points with the laser too.
    for x in (0, 10, 20):
        a.post(t="laser", x=x, y=5)
    a.post(t="laser", off=True)
    for tab in (p, w):
        lasers = []
        while not lasers or "off" not in lasers[-1]:
            lasers.append(tab.until(lambda m: m["t"] == "laser"))
        assert [m.get("x") for m in lasers] == [0, 10, 20, None]
        assert {m["id"] for m in lasers} == {a.id}
    for tab in (p, a, w):
        tab.close()


def test_only_the_presenters_view_is_passed_on_and_a_later_tab_gets_it(
        served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present)
    a = Peer(served, board.stem, edit, follow=True)
    a.post(t="view", x=1, y=1, w=10, h=10)
    p.post(t="view", x=-100, y=-50, w=800, h=500)
    got = a.until(lambda m: m["t"] == "view")
    assert got == {"t": "view", "id": p.id, "x": -100.0, "y": -50.0,
                   "w": 800.0, "h": 500.0}
    assert not [m for m in p.quiet() if m["t"] == "view"]
    # A tab that comes now gets the presenter's view before its first frame.
    late = Peer.__new__(Peer)
    late._conn = websockets_sync.connect(served.url(board.stem), max_size=None)
    late.ws = late._conn.__enter__()
    late.ws.send(json.dumps({"t": "hello", "key": watch, "follow": True}))
    late.next_id, late.frames, late.seen = 1, [], []
    kinds = []
    while "frame" not in kinds:
        kinds.append(late.recv()["t"])
    assert kinds.index("view") < kinds.index("frame")
    assert [m for m in late.seen if m["t"] == "view"][0]["w"] == 800.0
    # The presenter gone, no view is passed on any more.
    p.close()
    assert a.peers(lambda m: m["lead"] is None)["lead"] is None
    for tab in (a, late):
        tab.close()


def test_who_follows_shows_in_the_presenters_list(served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present)
    a = Peer(served, board.stem, edit, follow=True)
    w = Peer(served, board.stem, watch, follow=True)

    def following(m):
        return sorted(x["id"] for x in m["peers"] if x["following"])
    assert following(p.peers(lambda m: len(m["peers"]) == 3)) == sorted([a.id, w.id])
    w.post(t="follow", on=False)
    assert following(p.peers(lambda m: len(following(m)) == 1)) == [a.id]
    # The presenter never follows.
    p.post(t="follow", on=True)
    assert not [m for m in p.quiet() if m["t"] == "peers" and following(m) != [a.id]]
    for tab in (p, a, w):
        tab.close()


def test_a_rename_shows_in_every_tab(served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present)
    w = Peer(served, board.stem, watch)
    w.post(t="name", name="  Marek\n")
    for tab in (p, w):
        msg = tab.peers(lambda m: "Marek" in _names(m))
        assert _names(msg) == ["Presenter", "Marek"]
    w.post(t="name", name="")
    assert _names(p.peers(lambda m: "Marek" not in _names(m))) == ["Presenter", "Guest 1"]
    for tab in (p, w):
        tab.close()


def test_bad_and_flooding_presence_is_dropped_and_the_socket_stays_open(
        served, board):
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present)
    w = Peer(served, board.stem, watch)
    for bad in ({"t": "cursor", "x": "a", "y": 1},
                {"t": "cursor", "x": float("inf"), "y": 1},
                {"t": "view", "x": 0, "y": 0, "w": 0, "h": 1},
                {"t": "name", "name": ["x"]}, {"t": "follow"}):
        w.ws.send(json.dumps(bad, allow_nan=True))
    for i in range(400):
        w.post(t="cursor", x=i, y=0)
    cursors = [m for m in p.quiet(1.0) if m["t"] == "cursor"]
    assert cursors and len(cursors) <= presence.BURST + 10
    assert all(isinstance(m["x"], float) for m in cursors)
    # Still open: an edit from the presenter is answered.
    ack = p.edit(p.latest()["version"], {"op": "rename", "id": "a", "label": "A2"})
    assert ack["t"] == "ack"
    for tab in (p, w):
        tab.close()


def test_the_present_link_edits_like_the_edit_link(served, board):
    p = Peer(served, board.stem, served.keys.presenter)
    ack = p.edit(p.latest()["version"], {"op": "rename", "id": "a",
                                          "label": "Api"})
    assert ack["t"] == "ack", ack
    assert '"Api"' in board.read_text()
    p.close()


def test_tabs_on_another_board_hear_where_the_presenter_went(served):
    for name in ("away-top", "away-sub"):
        (served.root / f"{name}.grafli").write_text(BOARD, encoding="utf-8")
    present, edit, watch = _keys(served)
    p = Peer(served, "away-top", present)
    w = Peer(served, "away-top", watch, follow=True)
    # The presenter opens the other board; its tab on this one closes.
    p.close()
    p2 = Peer(served, "away-sub", present)
    got = w.until(lambda m: m["t"] == "away" and m["board"])
    assert got == {"t": "away", "board": "away-sub", "href": "/b/away-sub"}
    # A tab that opens the first board now hears it at once.
    late = Peer(served, "away-top", edit)
    assert any(m["t"] == "away" and m["board"] == "away-sub" for m in late.seen) \
        or late.until(lambda m: m["t"] == "away")["board"] == "away-sub"
    # The presenter's tab closed: no board has the presenter.
    p2.close()
    assert w.until(lambda m: m["t"] == "away")["board"] is None
    for tab in (w, late):
        tab.close()


def test_a_session_with_presence_leaves_the_board_file_unchanged(served, board):
    """Three tabs come and go, rename, follow and stop, move their cursors,
    use the laser and the presenter's view moves: the file's bytes and its
    modification time stay as they were, and no new frame is drawn."""
    before = board.read_bytes()
    mtime = os.stat(board).st_mtime_ns
    present, edit, watch = _keys(served)
    p = Peer(served, board.stem, present, name="Serein")
    version = p.latest()["version"]
    a = Peer(served, board.stem, edit, name="Anna", follow=True)
    w = Peer(served, board.stem, watch, follow=True)
    for i in range(30):
        p.post(t="view", x=i * 5, y=0, w=800 - i, h=500)
        p.post(t="cursor", x=i * 4, y=i)
        a.post(t="laser", x=i, y=i * 2)
        w.post(t="cursor", x=-i, y=3)
    a.post(t="laser", off=True)
    w.post(t="follow", on=False)
    w.post(t="name", name="Marek")
    w.post(t="follow", on=True)
    a.post(t="cursor", off=True)
    w.until(lambda m: m["t"] == "peers" and "Marek" in _names(m))
    a.close()
    w.close()
    late = Peer(served, board.stem, watch, follow=True)
    seen = p.quiet(0.6)
    late.close()
    p.close()
    time.sleep(0.2)
    assert board.read_bytes() == before
    assert os.stat(board).st_mtime_ns == mtime
    assert not [m for m in seen if m["t"] == "frame"]
    assert late.frames[-1]["version"] == version
