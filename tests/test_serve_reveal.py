"""Reveal mode in grafli serve: a prepared board starts with only its title
showing to the guests, and the presenter reveals a box, a box with its
neighbours or a container, in any order. Over a real server, the real render
worker and WebSocket clients standing in for tabs. None of it touches the
file."""

from __future__ import annotations

import os

import pytest

from grafli.format import parse
from grafli.serve import reveal

BOARD = """#!grafli v1
# Payments: a prepared board
@ note title 0,-160 "Payments: where a charge goes" ~xlarge
@ box client "Client" 0,0 160x80
@ box svc "Payment service" 300,-40 520x200
@ box api "API" 320,0 160x80 >svc
@ box pay "Payments" 620,0 160x80 >svc
@ box fraud "Fraud check" 620,300 160x80
@ box ledger "Ledger" 1000,0 160x80
@ note why 1000,200 "Ledger is append-only" &doc
@ arrow client -> api "charge"
@ arrow api -> pay "forward"
@ arrow pay -> fraud "score"
@ arrow pay -> ledger "write"
@ bookmark bm1 "The write" @pay,ledger "Where money lands"
@ flow tour "The charge" bm1
"""


def _ids(frame):
    return {e["id"] for e in frame["board"]["elements"]}


def _placed(frame, hidden=None):
    """The ids with a rect; with *hidden* True/False only those (not)
    marked hidden."""
    return {e["id"] for e in frame["board"]["elements"] if "rect" in e
            and (hidden is None or bool(e.get("hidden")) == hidden)}


# ── Unit: what is hidden, what a reveal shows ──

def test_reveal_mode_hides_all_but_the_title():
    board = parse(BOARD)
    assert reveal.start(board) == {"client", "svc", "api", "pay", "fraud",
                                   "ledger", "why"}


def test_the_title_keeps_the_container_it_sits_in():
    board = parse("@ box frame \"Frame\" 0,0 400x300\n"
                  "@ note title 10,10 \"T\" >frame\n"
                  "@ box a \"A\" 10,100 100x50 >frame\n")
    assert reveal.start(board) == {"a"}


def test_a_box_shows_with_the_container_it_sits_in():
    board = parse(BOARD)
    assert reveal.uncover(board, "api") == {"api", "svc"}


def test_a_container_shows_with_what_it_holds():
    board = parse(BOARD)
    assert reveal.uncover(board, "svc") == {"svc", "api", "pay"}


def test_a_box_with_its_neighbours():
    board = parse(BOARD)
    assert reveal.uncover(board, "pay", near=True) == {
        "pay", "svc", "api", "fraud", "ledger"}


def test_an_unknown_element_cannot_be_revealed():
    with pytest.raises(KeyError):
        reveal.uncover(parse(BOARD), "nope")


def test_a_hidden_container_hides_what_it_holds():
    board = parse(BOARD)
    assert reveal.hidden_now(board, {"svc"}) == {"svc", "api", "pay"}


def test_the_guests_board_has_nothing_hidden_in_it():
    text = reveal.guest_text(BOARD, reveal.start(parse(BOARD)) - {"client"})
    guest = parse(text)
    assert [b.id for b in guest.boxes] == ["client"]
    assert [n.id for n in guest.notes] == ["title"]
    assert guest.arrows == [] and guest.bookmarks == [] and guest.flows == []
    for word in ("Ledger", "Fraud", "append-only", "Where money lands"):
        assert word not in text


def test_an_arrow_shows_once_both_its_ends_do():
    hidden = reveal.start(parse(BOARD)) - {"client", "api", "svc"}
    guest = parse(reveal.guest_text(BOARD, hidden))
    assert [(a.from_id, a.to_id) for a in guest.arrows] == [("client", "api")]


def test_a_bookmark_and_its_flow_show_once_their_focus_does():
    hidden = reveal.start(parse(BOARD)) - reveal.uncover(parse(BOARD), "pay",
                                                         near=True)
    guest = parse(reveal.guest_text(BOARD, hidden))
    assert [b.id for b in guest.bookmarks] == ["bm1"]
    assert [f.id for f in guest.flows] == ["tour"]


def test_an_element_added_later_is_not_hidden():
    hidden = reveal.start(parse(BOARD))
    board = parse(BOARD + '@ box cache "Cache" 0,400 160x80\n')
    assert "cache" not in reveal.hidden_now(board, hidden)


def test_nothing_hidden_draws_the_board_as_it_is():
    assert reveal.guest_text(BOARD, set()) is None
    assert reveal.guest_text(BOARD, {"gone"}) is None


# ── Over the socket ──

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from tests.test_serve import Served, Tab as _Tab  # noqa: E402

_open: list = []


class Tab(_Tab):
    """A tab closed after its test even when the test fails, so no socket
    thread outlives it into the next tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.closed = False
        _open.append(self)

    def close(self):
        if not self.closed:
            self.closed = True
            super().close()


@pytest.fixture(autouse=True)
def _close_tabs():
    yield
    while _open:
        _open.pop().close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path_factory.mktemp("reveal"), reveal=True)
    yield s
    s.stop()


@pytest.fixture
def board(served, request):
    path = served.root / f"{request.node.name}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    vault = served.root / f"{request.node.name}-res"
    vault.mkdir()
    (vault / "why.md").write_text("The ledger never forgets a charge.\n",
                                  encoding="utf-8")
    return path


def _tabs(served, board):
    p = Tab(served, board.stem, served.keys.presenter)
    _, pf = p.open()
    e = Tab(served, board.stem, served.keys.editor)
    _, ef = e.open()
    w = Tab(served, board.stem, served.keys.viewer)
    _, wf = w.open()
    return (p, pf), (e, ef), (w, wf)


def _reveal(tab, **msg):
    return tab.send({"t": "reveal", **msg})


def _drawn(frame):
    """Everything a guest's frame carries that could show a word."""
    import json
    return json.dumps({k: frame[k] for k in ("board", "svgs", "docs")})


def test_guests_see_only_what_is_revealed_and_the_presenter_the_rest_faint(
        served, board):
    before, mtime = board.read_bytes(), os.stat(board).st_mtime_ns
    (p, pf), (e, ef), (w, wf) = _tabs(served, board)

    # The board starts with its title only, for the watch and edit links.
    for frame in (ef, wf):
        assert _placed(frame) == {"title"}
        assert frame["board"]["lines"] == []
        drawn = _drawn(frame)
        for word in ("Client", "Ledger", "Fraud", "never forgets",
                     "Where money lands", "charge\""):
            assert word not in drawn, word
    # The presenter sees the same drawing, and everything else marked
    # hidden, with its rect, for the faint outlines.
    assert pf["svgs"] == wf["svgs"]
    assert _placed(pf, hidden=False) == {"title"}
    assert _placed(pf, hidden=True) == {"client", "svc", "api", "pay", "fraud",
                                        "ledger", "why"}
    assert len(pf["board"]["hidden_lines"]) == 4
    assert pf["board"]["reveal"] == {"hidden": 7}
    assert "reveal" not in wf["board"]

    # A box: the guests' next frame has it, still no arrow.
    ack = _reveal(p, do="show", el="client")
    assert ack["t"] == "ack" and ack["revealed"] == ["client"]
    assert ack["hidden"] == 6 and ack["on"] is True
    for tab in (w, e):
        frame = tab.recv_until("frame")
        assert frame["version"] == ack["version"]
        assert _placed(frame) == {"title", "client"}
    # A box in a container: the container's frame comes with it, and the
    # arrow between two revealed boxes.
    ack = _reveal(p, do="show", el="api")
    assert ack["revealed"] == ["api", "svc"]
    frame = w.recv_until("frame")
    assert _placed(frame) == {"title", "client", "svc", "api"}
    assert [line["ends"] for line in frame["board"]["lines"]] == [["client",
                                                                  "api"]]
    assert "Fraud" not in _drawn(frame) and "Ledger" not in _drawn(frame)
    # A box with its neighbours, in one step.
    ack = _reveal(p, do="show", el="pay", near=True)
    assert ack["revealed"] == ["fraud", "ledger", "pay"]
    frame = w.recv_until("frame")
    assert _placed(frame) == {"title", "client", "svc", "api", "pay", "fraud",
                              "ledger"}
    assert len(frame["board"]["lines"]) == 4
    # What the presenter still holds back is the note, faint.
    # (The presenter's frame comes before the answer to its step.)
    lead = p.latest()
    assert lead["version"] == ack["version"]
    assert _placed(lead, hidden=True) == {"why"}
    assert lead["board"]["reveal"] == {"hidden": 1}
    assert lead["svgs"] == frame["svgs"]

    # The rest, then reveal mode off: everyone has the board as it is.
    assert _reveal(p, do="all")["hidden"] == 0
    frame = w.recv_until("frame")
    assert "never forgets" in _drawn(frame)
    ack = _reveal(p, do="stop")
    assert ack["on"] is False
    frame, lead = w.recv_until("frame"), p.latest()
    assert "reveal" not in lead["board"]
    assert lead["svgs"] == frame["svgs"]

    # The board file is unchanged after the whole session.
    for tab in (p, e, w):
        tab.close()
    assert board.read_bytes() == before
    assert os.stat(board).st_mtime_ns == mtime


def test_only_the_present_link_reveals(served, board):
    (p, _), (e, _), (w, _) = _tabs(served, board)
    for tab in (e, w):
        ack = _reveal(tab, do="show", el="client")
        assert ack["t"] == "error"
        assert ack["message"] == "only the present link reveals"
        assert _reveal(tab, do="stop")["t"] == "error"
    assert _reveal(p, do="show", el="nope")["message"] == (
        "no element 'nope' to reveal")
    assert _reveal(p, do="peek")["message"] == "no reveal step 'peek'"
    for tab in (p, e, w):
        tab.close()


def test_reveal_mode_can_start_again_and_shows_new_boxes_at_once(served, board):
    before = board.read_bytes()
    (p, _), (e, ef), (w, _) = _tabs(served, board)
    assert _reveal(p, do="stop")["on"] is False
    assert _placed(w.recv_until("frame")) >= {"client", "ledger"}
    # Start again: everything is hidden again but the title.
    ack = _reveal(p, do="start")
    assert ack["on"] is True and ack["hidden"] == 7
    assert _placed(w.recv_until("frame")) == {"title"}
    _reveal(p, do="show", el="client")
    frame = e.recv_until("frame")
    # A box the editor adds beside a revealed one shows at once; it is the
    # only change the session makes to the file.
    ack = e.edit(frame["version"], {"op": "add_box", "label": "Cache",
                                    "beside": "client", "side": "below"})
    assert ack["t"] == "ack"
    frame = w.recv_until("frame")
    while frame["version"] < ack["version"]:
        frame = w.recv_until("frame")
    assert _placed(frame) == {"title", "client", ack["touched"]}
    assert parse(board.read_text()).box_by_id(ack["touched"]) is not None
    assert len(parse(board.read_text()).boxes) == len(parse(before.decode()).boxes) + 1
    for tab in (p, e, w):
        tab.close()


def test_a_reload_finds_the_board_as_the_presenter_left_it(served, board):
    p = Tab(served, board.stem, served.keys.presenter)
    p.open()
    _reveal(p, do="show", el="client")
    p.close()
    # The last tab left; the board's room closed. A new tab comes.
    w = Tab(served, board.stem, served.keys.viewer)
    _, frame = w.open()
    assert _placed(frame) == {"title", "client"}
    w.close()


def test_without_reveal_a_board_shows_whole(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path)
    try:
        (tmp_path / "b.grafli").write_text(BOARD, encoding="utf-8")
        w = Tab(s, "b", s.keys.viewer)
        _, frame = w.open()
        assert "ledger" in _placed(frame)
        p = Tab(s, "b", s.keys.presenter)
        _, lead = p.open()
        assert "reveal" not in lead["board"]
        # The presenter can still start it.
        assert _reveal(p, do="start")["hidden"] == 7
        assert _placed(w.recv_until("frame")) == {"title"}
        for tab in (p, w):
            tab.close()
    finally:
        s.stop()
