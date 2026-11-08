"""The agent's edits on a live board: a small one lands at once and every
tab is told what it touched, by name; undo works per author, so undoing the
agent's edit leaves what the presenter changed later; a change of more than
5 elements waits as a proposal the presenter takes or drops, and the agent
hears which. The agent is the ``grafli agent`` bridge driven over stdio;
the tabs are WebSocket clients."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
pytest.importorskip("websockets.sync.client")

from grafli.format import parse  # noqa: E402
from grafli.serve import agent as agents  # noqa: E402
from grafli.serve.changes import PROPOSE_OVER, changes  # noqa: E402
from tests.test_serve_agent import (_agent_is, _text, board, served,  # noqa: E402,F401
                                    sessions)
from tests.test_serve_presence import Peer  # noqa: E402

# On BOARD (a, b, a -> b): b and its arrow go, three boxes and two arrows
# come — 7 changes, more than 5.
SPLIT = """#!grafli v1
@ box a "A" 0,0 120x60
@ box c "Charge" 240,-100 120x60
@ box d "Refund" 240,0 120x60
@ box e "Payout" 240,100 120x60
@ arrow a -> c
@ arrow a -> d
"""


# ── Unit: what an edit changed ──

def test_changes_counts_each_element_added_removed_or_changed_once():
    before = parse('#!grafli v1\n@ box a "A" 0,0 120x60\n'
                   '@ box b "B" 240,0 120x60\n@ arrow a -> b "calls"\n')
    done = changes(before, parse(SPLIT))
    assert done.added == {"c": "box", "d": "box", "e": "box",
                          "a->c": "arrow", "a->d": "arrow"}
    assert done.removed == {"b": "box", "a->b": "arrow"}
    assert done.changed == {} and done.count == 7 > PROPOSE_OVER
    assert done.summary() == "+3 boxes, +2 arrows, −1 box, −1 arrow"
    moved = parse('#!grafli v1\n@ box a "A" 10,0 120x60\n'
                  '@ box b "B" 240,0 120x60\n@ arrow a -> b "calls"\n')
    assert changes(before, moved).changed == {"a": "box"}
    assert changes(before, before).count == 0


# ── End to end ──

def _connect(served, board, sessions, name="Serein"):
    presenter = Peer(served, board.stem, served.keys.presenter, name=name)
    guest = Peer(served, board.stem, served.keys.viewer)
    session = sessions()
    assert not session.tool("connect").get("isError")
    _agent_is(presenter, lambda a: a["present"])
    return presenter, guest, session


def _read(session, name):
    got = session.tool("read_board", board=name)
    return json.loads(_text(got)), got["content"][1]["text"]


def _write(session, name, version, text, **extra):
    got = session.tool("write_board", board=name, base_version=version,
                       text=text, **extra)
    assert not got.get("isError"), got
    return json.loads(_text(got))


def _since(tab, at, pred, timeout=10):
    """The first message *tab* got from its *at*-th on for which *pred* is
    true, waiting for it when it has not come yet."""
    for msg in tab.seen[at:]:
        if pred(msg):
            return msg
    return tab.until(pred, timeout)


def _rename(tab, el_id, label):
    ack = tab.send({"t": "edit", "base": tab.latest()["version"],
                    "op": {"op": "rename", "id": el_id, "label": label}})
    assert ack["t"] == "ack", ack
    return ack


def test_a_small_edit_lands_at_once_and_every_tab_hears_what_it_touched(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    meta, text = _read(session, board.stem)
    text = text.replace('"B"', '"Billing"') + '@ box c "Cache" 0,200 120x60\n'
    wrote = _write(session, board.stem, meta["version"], text)
    assert wrote["changes"] == 2 and wrote["summary"] == "+1 box, ~1 box"
    assert "proposed" not in wrote
    assert '"Billing"' in board.read_text(encoding="utf-8")
    for tab in (presenter, guest):
        mark = tab.until(lambda m: m["t"] == "marked")
        assert mark["by"] == "Serein's agent"
        assert mark["color"] == agents.AGENT_COLOR
        assert mark["ids"] == ["b", "c"] and mark["removed"] == 0
        assert mark["version"] == wrote["version"] and not mark["undone"]
        # The frame that shows it came first.
        assert tab.latest()["version"] >= mark["version"]
    presenter.close()
    guest.close()


def test_undoing_the_agents_edit_keeps_the_presenters_later_edits(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    meta, text = _read(session, board.stem)
    text = text.replace('"B"', '"Billing"') + '@ box c "Cache" 0,200 120x60\n'
    _write(session, board.stem, meta["version"], text)
    presenter.until(lambda m: m["t"] == "marked")
    # The presenter edits after the agent: renames A, adds a box.
    _rename(presenter, "a", "Gateway")
    ack = presenter.send({"t": "edit", "base": presenter.latest()["version"],
                          "op": {"op": "add_box", "label": "Mine",
                                 "x": 0, "y": 400}})
    mine = ack["touched"]

    # The presenter undoes the agent's edit, not their own.
    ack = presenter.send({"t": "undo", "of": "agent"})
    assert ack["t"] == "ack" and ack["conflicts"] == [], ack
    saved = parse(board.read_text(encoding="utf-8"))
    labels = {b.id: b.label for b in saved.boxes}
    assert labels["b"] == "B" and "c" not in labels
    assert labels["a"] == "Gateway" and labels[mine] == "Mine"
    # The agent hears that its edit was undone, as a channel turn.
    note = session.note()
    assert note["method"] == "notifications/claude/channel"
    assert note["params"]["meta"] == {"board": board.stem, "event": "undone"}
    assert "Serein undid your last edit" in note["params"]["content"]
    # Nothing of the agent's is left to undo; the presenter's own undo
    # still takes back their own last edit.
    again = presenter.send({"t": "undo", "of": "agent"})
    assert again["t"] == "error" and "no edit" in again["message"]
    assert presenter.send({"t": "undo"})["t"] == "ack"
    assert mine not in {b.id for b in parse(
        board.read_text(encoding="utf-8")).boxes}
    presenter.close()
    guest.close()


def test_the_agent_undoes_its_own_edit_and_the_presenters_stays(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    meta, text = _read(session, board.stem)
    _write(session, board.stem, meta["version"],
           text.replace('"B"', '"Billing"'))
    _rename(presenter, "a", "Gateway")
    got = session.tool("undo_board", board=board.stem)
    assert not got.get("isError"), got
    saved = board.read_text(encoding="utf-8")
    assert '"B"' in saved and '"Gateway"' in saved and "Billing" not in saved
    mark = guest.until(lambda m: m["t"] == "marked" and m["undone"])
    assert mark["ids"] == ["b"] and mark["by"] == "Serein's agent"
    nothing = session.tool("undo_board", board=board.stem)
    assert nothing["isError"] and "no edit" in _text(nothing)
    presenter.close()
    guest.close()


def test_only_the_present_link_undoes_the_agents_edit(served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    editor = Peer(served, board.stem, served.keys.editor)
    meta, text = _read(session, board.stem)
    _write(session, board.stem, meta["version"],
           text.replace('"B"', '"Billing"'))
    got = editor.send({"t": "undo", "of": "agent"})
    assert got["t"] == "error" and "present link" in got["message"]
    assert '"Billing"' in board.read_text(encoding="utf-8")
    for tab in (presenter, guest, editor):
        tab.close()


def test_a_seven_element_change_waits_as_a_proposal_taken_with_take(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    before = board.read_bytes()
    meta, _text_ = _read(session, board.stem)
    wrote = _write(session, board.stem, meta["version"], SPLIT,
                   about="split B")
    assert wrote["proposed"] and wrote["changes"] == 7
    assert "Enter" in wrote["note"] and wrote["version"] == meta["version"]
    # The file is as it was: the change waits on the board.
    assert board.read_bytes() == before
    for tab in (presenter, guest):
        shown = tab.until(lambda m: m["t"] == "proposal")["proposal"]
        assert shown["count"] == 7 and shown["by"] == "Serein's agent"
        assert shown["about"] == "split B"
        assert sorted(s["id"] for s in shown["added"]) == [
            "a->c", "a->d", "c", "d", "e"]
        assert shown["removed"] == ["a->b", "b"]
        box = next(s for s in shown["added"] if s["id"] == "c")
        assert box["label"] == "Charge" and len(box["rect"]) == 4
        arrow = next(s for s in shown["added"] if s["id"] == "a->c")
        assert arrow["paths"]
    # The agent sees it waiting when it reads the board.
    assert _read(session, board.stem)[0]["proposal"]["changes"] == 7
    # A tab that comes now sees it too.
    late = Peer(served, board.stem, served.keys.viewer)
    assert late.until(lambda m: m["t"] == "proposal")["proposal"]["count"] == 7

    # A guest cannot take it; the presenter can.
    at = {tab: len(tab.seen) for tab in (presenter, guest, late)}
    refused = guest.send({"t": "proposal", "do": "take",
                          "proposal": shown["id"]})
    assert refused["t"] == "error" and "present link" in refused["message"]
    ack = presenter.send({"t": "proposal", "do": "take",
                          "proposal": shown["id"]})
    assert ack["t"] == "ack" and ack["taken"] == 7, ack
    saved = parse(board.read_text(encoding="utf-8"))
    assert sorted(b.id for b in saved.boxes) == ["a", "c", "d", "e"]
    for tab in (presenter, guest, late):
        assert _since(tab, at[tab],
                      lambda m: m["t"] == "proposal")["proposal"] is None
        mark = _since(tab, at[tab], lambda m: m["t"] == "marked")
        assert mark["ids"] == ["a->c", "a->d", "c", "d", "e"]
        assert mark["removed"] == 2
    note = session.note()
    assert note["params"]["meta"] == {"board": board.stem, "event": "taken"}
    assert f"version {ack['version']}" in note["params"]["content"]
    assert _read(session, board.stem)[0]["proposal"] is None

    # Taken, it is the agent's edit: the presenter's U undoes it.
    assert presenter.send({"t": "undo", "of": "agent"})["t"] == "ack"
    assert board.read_bytes() == before
    for tab in (presenter, guest, late):
        tab.close()


def test_a_proposal_dropped_leaves_the_file_and_the_agent_hears_it(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    before = board.read_bytes()
    meta, _text_ = _read(session, board.stem)
    _write(session, board.stem, meta["version"], SPLIT)
    shown = presenter.until(lambda m: m["t"] == "proposal")["proposal"]
    stale = presenter.send({"t": "proposal", "do": "drop",
                            "proposal": shown["id"] + 1000})
    assert stale["t"] == "error" and "changed" in stale["message"]
    ack = presenter.send({"t": "proposal", "do": "drop",
                          "proposal": shown["id"]})
    assert ack["t"] == "ack" and ack["dropped"] == 7
    assert board.read_bytes() == before
    assert guest.until(lambda m: m["t"] == "proposal")["proposal"]["count"] == 7
    assert guest.until(lambda m: m["t"] == "proposal")["proposal"] is None
    note = session.note()
    assert note["params"]["meta"] == {"board": board.stem, "event": "dropped"}
    again = presenter.send({"t": "proposal", "do": "take"})
    assert again["t"] == "error" and "no proposal" in again["message"]
    presenter.close()
    guest.close()


def test_a_proposal_taken_later_keeps_what_the_presenter_changed_meanwhile(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    meta, _text_ = _read(session, board.stem)
    _write(session, board.stem, meta["version"], SPLIT)
    shown = presenter.until(lambda m: m["t"] == "proposal")["proposal"]
    _rename(presenter, "a", "Gateway")
    ack = presenter.send({"t": "proposal", "do": "take",
                          "proposal": shown["id"]})
    assert ack["t"] == "ack", ack
    saved = parse(board.read_text(encoding="utf-8"))
    labels = {b.id: b.label for b in saved.boxes}
    assert labels == {"a": "Gateway", "c": "Charge", "d": "Refund",
                      "e": "Payout"}
    presenter.close()
    guest.close()


def test_in_reveal_mode_a_guest_sees_only_who_proposes_how_much(
        served, board, sessions):
    presenter, guest, session = _connect(served, board, sessions)
    started = presenter.send({"t": "reveal", "do": "start"})
    assert started["t"] == "ack", started
    meta, _text_ = _read(session, board.stem)
    _write(session, board.stem, meta["version"], SPLIT)
    lead = presenter.until(lambda m: m["t"] == "proposal")["proposal"]
    seen = guest.until(lambda m: m["t"] == "proposal")["proposal"]
    assert lead["added"] and lead["removed"]
    assert seen["count"] == 7 and seen["by"] == "Serein's agent"
    assert "added" not in seen and "removed" not in seen
    presenter.send({"t": "proposal", "do": "drop", "proposal": lead["id"]})
    presenter.send({"t": "reveal", "do": "stop"})
    presenter.close()
    guest.close()
