"""What the agent works on, on every tab: from the moment a request from a
tab reaches the connected Claude Code session until the agent's next
write, proposal or undo, every tab — on that board or another, with any
link — is told the request and what the agent does with it as far as the
server sees (reading the board, rendering it). After ``late_s`` without an
answer the tabs are told it is late; once the session is gone, nothing is
worked on. The session is the ``grafli agent`` bridge driven over stdio, as
Claude Code drives it; the tabs are WebSocket clients."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.serve import agent as agents  # noqa: E402
from tests.test_serve_ask import _ask, _board, _serve  # noqa: E402
from tests.test_serve_ask import sessions  # noqa: E402,F401
from tests.test_serve_presence import Peer  # noqa: E402

ASK = "add a cache between api and db"


@pytest.fixture
def served(tmp_path_factory):
    s = _serve(tmp_path_factory)
    yield s
    s.stop()


def _work(tab, pred=lambda w: True):
    """The next ``work`` message whose work *pred* takes (None included)."""
    return tab.until(lambda m: m["t"] == "work" and pred(m["work"]))["work"]


def _working(tab, pred=lambda w: True):
    return _work(tab, lambda w: w is not None and pred(w))


def _done(tab):
    return _work(tab, lambda w: w is None)


def _connected(served, sessions, *tabs, name="Claude"):
    session = sessions(served)
    assert not session.tool("connect", name=name).get("isError")
    for tab in tabs:
        tab.peers(lambda m: m["agent"] is not None and m["agent"]["present"]
                  and m["agent"]["name"] == name)
    return session


def _asked(tab, text):
    """Ask the agent from *tab*; the work it was shown before the ack."""
    start = len(tab.seen)
    assert _ask(tab, text)["t"] == "ack"
    shown = [m["work"] for m in tab.seen[start:] if m["t"] == "work"]
    assert shown and shown[-1] is not None
    return shown[-1]


def _read(session, board):
    got = session.tool("read_board", board=board)
    return json.loads(got["content"][0]["text"])["version"], \
        got["content"][1]["text"]


def test_every_tab_shows_the_request_and_what_the_agent_does_until_it_writes(
        served, sessions):
    _board(served, "work")
    _board(served, "elsewhere")
    asker = Peer(served, "work", served.keys.editor, name="Anna")
    viewer = Peer(served, "work", served.keys.viewer)
    away = Peer(served, "elsewhere", served.keys.presenter, name="Serein")
    session = _connected(served, sessions, asker, viewer, away)

    asked = _asked(asker, ASK)
    for tab in (asker, viewer, away):
        work = asked if tab is asker else _working(tab)
        assert work == {"by": "Claude", "color": agents.AGENT_COLOR,
                        "board": "work", "text": ASK, "from": "Anna",
                        "doing": "", "late": False,
                        "late_after": agents.LATE_S, "more": 0}
    assert session.note()["params"]["content"] == ASK

    # A tab that opens meanwhile is told at once.
    late_comer = Peer(served, "work", served.keys.viewer)
    assert _working(late_comer)["text"] == ASK

    # The agent reads the board: every tab sees it.
    version, text = _read(session, "work")
    for tab in (asker, viewer, away, late_comer):
        assert _working(tab, lambda w: w["doing"])["doing"] == agents.READING

    # It looks at the drawing.
    assert not session.tool("render_board", board="work").get("isError")
    for tab in (asker, viewer, away, late_comer):
        assert _working(tab, lambda w: w["doing"] == agents.RENDERING)

    # Its edit lands: the frame and its mark first, then nothing is worked on.
    text = text.replace('@ arrow api -> db "write"\n',
                        '@ box cache "Cache" 200,160 160x80\n'
                        '@ arrow api -> cache "read"\n')
    wrote = json.loads(session.tool("write_board", board="work",
                                    base_version=version,
                                    text=text)["content"][0]["text"])
    assert "proposed" not in wrote
    for tab in (asker, viewer, away, late_comer):
        assert _done(tab) is None
    marked = [i for i, m in enumerate(asker.seen) if m["t"] == "marked"]
    cleared = max(i for i, m in enumerate(asker.seen)
                  if m["t"] == "work" and m["work"] is None)
    assert marked and marked[-1] < cleared

    # Reading after the answer shows no work again.
    _read(session, "work")
    assert not any(m["t"] == "work" for m in asker.quiet())
    for tab in (asker, viewer, away, late_comer):
        tab.close()


def test_a_proposal_or_an_undo_answers_the_request_too(served, sessions):
    _board(served, "answers")
    presenter = Peer(served, "answers", served.keys.presenter, name="Serein")
    session = _connected(served, sessions, presenter)

    assert _asked(presenter, "split it into six")["text"] == "split it into six"
    version, text = _read(session, "answers")
    text += "".join(f'@ box b{i} "B{i}" {i * 200},400 160x80\n'
                    for i in range(6))
    wrote = json.loads(session.tool("write_board", board="answers",
                                    base_version=version,
                                    text=text)["content"][0]["text"])
    assert wrote.get("proposed") is not None
    assert _done(presenter) is None

    assert _asked(presenter, "take back your last edit")["more"] == 0
    assert presenter.send({"t": "proposal", "do": "take"})["t"] == "ack"
    # The presenter taking the proposal is not the agent's answer.
    assert not any(m["t"] == "work" and m["work"] is None
                   for m in presenter.quiet())
    assert not session.tool("undo_board", board="answers").get("isError")
    assert _done(presenter) is None
    presenter.close()


def test_a_failed_write_is_no_answer(served, sessions):
    _board(served, "failed")
    guest = Peer(served, "failed", served.keys.editor, name="Anna")
    session = _connected(served, sessions, guest)
    _asked(guest, ASK)
    got = session.tool("write_board", board="failed", base_version=-1,
                       text="@ box x \"X\" 0,0 10x10\n")
    assert got.get("isError")
    assert not any(m["t"] == "work" and m["work"] is None
                   for m in guest.quiet())
    guest.close()


def test_requests_wait_in_turn_and_each_answer_takes_the_oldest(
        served, sessions):
    _board(served, "turns")
    guest = Peer(served, "turns", served.keys.editor, name="Anna")
    session = _connected(served, sessions, guest)
    work = _asked(guest, "first")
    assert work["text"] == "first" and work["more"] == 0
    work = _asked(guest, "second")
    assert work["text"] == "first" and work["more"] == 1

    version, text = _read(session, "turns")
    session.tool("write_board", board="turns", base_version=version,
                 text=text.replace('"API"', '"API v2"'))
    work = _working(guest, lambda w: w["doing"] == "")
    assert work["text"] == "second" and work["more"] == 0
    guest.close()


def test_after_late_s_without_an_answer_the_tabs_are_told(
        served, sessions):
    served.app.state.hub.late_s = 0.6
    _board(served, "late")
    guest = Peer(served, "late", served.keys.editor, name="Anna")
    other = Peer(served, "late", served.keys.viewer)
    session = _connected(served, sessions, guest, other)
    assert not _asked(guest, ASK)["late"]
    for tab in (guest, other):
        work = _working(tab, lambda w: w["late"])
        assert work["text"] == ASK and work["late_after"] == 0.6
    # Late is still being worked on: a read shows it, and a write answers.
    _read(session, "late")
    assert _working(guest, lambda w: w["doing"])["late"]
    version, text = _read(session, "late")
    session.tool("write_board", board="late", base_version=version,
                 text=text.replace('"API"', '"API v2"'))
    assert _done(guest) is None
    guest.close()
    other.close()


def test_once_the_session_is_gone_nothing_is_worked_on(served, sessions):
    _board(served, "gone")
    guest = Peer(served, "gone", served.keys.editor, name="Anna")
    session = _connected(served, sessions, guest)
    _asked(guest, ASK)
    session.kill()
    assert _done(guest) is None
    # The tabs heard it gone first.
    assert not [m for m in guest.seen if m["t"] == "peers"][-1][
        "agent"]["present"]

    # A session that takes the seat over never heard the old requests.
    first = _connected(served, sessions, guest)
    _asked(guest, ASK)
    _connected(served, sessions, guest, name="Other")
    assert _done(guest) is None
    first.kill()
    guest.close()


def test_in_reveal_mode_the_presenters_request_stays_with_the_presenter(
        tmp_path_factory, sessions):
    served = _serve(tmp_path_factory, reveal=True)
    try:
        _board(served, "hidden")
        presenter = Peer(served, "hidden", served.keys.presenter,
                         name="Serein")
        guest = Peer(served, "hidden", served.keys.editor, name="Anna")
        _connected(served, sessions, presenter, guest)
        assert _asked(presenter, "add the ledger's replica")["text"] \
            == "add the ledger's replica"
        work = _working(guest)
        assert work["text"] is None and work["from"] == "Serein"
        presenter.close()
        guest.close()
    finally:
        served.stop()
