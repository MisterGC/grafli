"""grafli serve end to end: a real server on 127.0.0.1, the real render
worker, and WebSocket clients standing in for tabs."""

from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
websockets_sync = pytest.importorskip("websockets.sync.client")

from grafli.serve import server as srv  # noqa: E402
from grafli.sync import atomic_write  # noqa: E402

BOARD = """#!grafli v1
@ box a "A" 0,0 120x60
@ box b "B" 240,0 120x60
@ arrow a -> b "calls"
"""


class Served:
    def __init__(self, root: Path):
        import uvicorn
        self.root = root
        self.keys = srv.Keys()
        self.sock = srv.bind("127.0.0.1", 0)
        self.port = self.sock.getsockname()[1]
        self.app = srv.create_app(root, self.keys)
        config = uvicorn.Config(self.app, log_level="warning", ws="auto",
                                lifespan="on")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.sock]},
            daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)

    def url(self, name: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/{name}"

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    root = tmp_path_factory.mktemp("boards")
    s = Served(root)
    yield s
    s.stop()


@pytest.fixture
def board(served, request):
    path = served.root / f"{request.node.name.replace('[', '_').strip(']')}.grafli"
    path.write_text(BOARD, encoding="utf-8")
    return path


class Tab:
    """A WebSocket client speaking the live page's protocol."""

    def __init__(self, served: Served, name: str, key: str, author=None):
        self._conn = websockets_sync.connect(served.url(name), max_size=None)
        self.ws = self._conn.__enter__()
        hello = {"t": "hello", "key": key}
        if author is not None:
            hello["author"] = author
        self.ws.send(json.dumps(hello))
        self.next_id = 1
        self.frames: list[dict] = []

    def recv(self, timeout=10):
        msg = json.loads(self.ws.recv(timeout=timeout))
        if msg["t"] == "frame":
            self.frames.append(msg)
        return msg

    def recv_until(self, kind, timeout=10):
        deadline = time.monotonic() + timeout
        skipped = []
        while True:
            try:
                msg = self.recv(max(deadline - time.monotonic(), 0.01))
            except TimeoutError as e:
                # Say what came instead: a render error reads as a timeout.
                raise TimeoutError(f"no {kind!r} in {timeout} s; got "
                                   f"{[m.get('message', m['t']) for m in skipped]}"
                                   ) from e
            if msg["t"] == kind:
                return msg
            skipped.append(msg)

    def open(self):
        welcome = self.recv()
        assert welcome["t"] == "welcome"
        frame = self.recv_until("frame")
        return welcome, frame

    def edit(self, base, op):
        return self.send({"t": "edit", "base": base, "op": op})

    def undo(self):
        return self.send({"t": "undo"})

    def send(self, msg):
        req = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({**msg, "id": req}))
        while True:
            msg = self.recv()
            if msg.get("id") == req:
                return msg

    def latest(self):
        """The newest frame this tab has seen."""
        return self.frames[-1]

    def close(self):
        self._conn.__exit__(None, None, None)


def _labels(frame):
    """The boxes', notes' and images' labels (arrows have no rect)."""
    return {e["id"]: e["label"] for e in frame["board"]["elements"]
            if "rect" in e}


# ── Binding, keys and links ──

def test_binds_to_the_address_given_only():
    sock = srv.bind("127.0.0.1", 0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


def test_default_host_is_this_machine_not_every_interface(tmp_path, monkeypatch):
    from grafli import app
    seen = {}
    monkeypatch.setattr(srv, "run", lambda root, **kw: seen.update(kw) or 0)
    assert app._cmd_serve([str(tmp_path)]) == 0
    assert seen["host"] == "127.0.0.1" == srv.DEFAULT_HOST
    assert not srv.every_interface(seen["host"])
    assert app._cmd_serve([str(tmp_path), "--host", "100.64.0.7"]) == 0
    assert seen["host"] == "100.64.0.7"


def test_viewer_and_editor_keys_differ():
    keys = srv.Keys()
    assert keys.viewer != keys.editor
    assert keys.role(keys.viewer) == "viewer"
    assert keys.role(keys.editor) == "editor"
    assert keys.role("nope") is None and keys.role(None) is None
    with pytest.raises(ValueError):
        srv.Keys("same", "same")


def test_link_carries_the_key_after_the_hash():
    assert (srv.link("192.168.1.5", 7341, "team/api map", "K")
            == "http://192.168.1.5:7341/b/team/api%20map#k=K")
    assert srv.link("fd7a::1", 80, "b", "K") == "http://[fd7a::1]:80/b/b#k=K"


def test_run_prints_a_watch_and_an_edit_link_per_board(tmp_path, monkeypatch):
    import uvicorn
    (tmp_path / "one.grafli").write_text(BOARD)
    (tmp_path / "two.grafli").write_text(BOARD)
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    out = io.StringIO()
    assert srv.run(tmp_path, host="127.0.0.1", port=0, out=out) == 0
    text = out.getvalue()
    watch = [ln.split("watch: ")[1] for ln in text.splitlines() if "watch: " in ln]
    edit = [ln.split("edit:  ")[1] for ln in text.splitlines() if "edit:  " in ln]
    assert [u.split("/b/")[1].split("#")[0] for u in watch] == ["one", "two"]
    assert all(u.startswith("http://127.0.0.1:") for u in watch + edit)
    viewer_keys = {u.split("#k=")[1] for u in watch}
    editor_keys = {u.split("#k=")[1] for u in edit}
    assert len(viewer_keys) == len(editor_keys) == 1
    assert viewer_keys.isdisjoint(editor_keys)
    assert "every interface" not in text


def test_run_warns_when_told_to_listen_everywhere(tmp_path, monkeypatch):
    import uvicorn
    monkeypatch.setattr(uvicorn.Server, "run", lambda self, sockets=None: None)
    out = io.StringIO()
    srv.run(tmp_path, host="0.0.0.0", port=0, out=out)
    assert "Warning: 0.0.0.0 listens on every interface" in out.getvalue()


def test_board_names_stay_under_the_served_directory(tmp_path):
    (tmp_path / "ok.grafli").write_text(BOARD)
    (tmp_path / "ok-res").mkdir()
    (tmp_path / "ok-res" / "sub.grafli").write_text(BOARD)
    (tmp_path.parent / "outside.grafli").write_text(BOARD)
    assert srv.board_path(tmp_path, "ok") == (tmp_path / "ok.grafli").resolve()
    assert srv.board_path(tmp_path, "ok-res/sub") is not None
    for bad in ("../outside", "/etc/passwd", "missing", "", "ok-res/../ok",
                "ok\\x"):
        assert srv.board_path(tmp_path, bad) is None, bad
    assert srv.listed_boards(tmp_path) == ["ok"]


# ── The page and the socket ──

def test_the_page_holds_no_board_until_the_key(served, board):
    from urllib.request import urlopen
    with urlopen(f"http://127.0.0.1:{served.port}/b/{board.stem}") as r:
        page = r.read().decode("utf-8")
    data = page.split('id="grafli-data">', 1)[1].split("</script>", 1)[0]
    assert json.loads(data)["live"] is True
    assert json.loads(data)["boards"] == {}
    assert '<template id="svg-' not in page
    assert "grafliLive" in page
    assert "grafliEdit" in page    # the presenter's keys


def test_a_wrong_key_is_refused(served, board):
    from websockets.exceptions import ConnectionClosed
    tab = Tab(served, board.stem, "not-a-key")
    with pytest.raises(ConnectionClosed) as e:
        tab.recv()
    assert e.value.rcvd.code == srv.CLOSE_BAD_KEY


def test_an_unknown_board_is_refused(served):
    from websockets.exceptions import ConnectionClosed
    tab = Tab(served, "no-such-board", served.keys.viewer)
    with pytest.raises(ConnectionClosed) as e:
        tab.recv()
    assert e.value.rcvd.code == srv.CLOSE_NO_BOARD


def test_the_first_frame_is_the_apps_drawing(served, board):
    tab = Tab(served, board.stem, served.keys.viewer)
    welcome, frame = tab.open()
    assert welcome["role"] == "viewer"
    assert frame["board"]["file"] == f"{board.stem}.grafli"
    assert _labels(frame) == {"a": "A", "b": "B"}
    rects = {e["id"]: e["rect"] for e in frame["board"]["elements"]
             if "rect" in e}
    assert rects["a"][2] >= 120 and rects["b"][0] > rects["a"][0]
    assert frame["svgs"]["b0-0"].startswith("<svg")
    tab.close()


def test_a_frame_lists_every_arrow_and_each_labels_text(served, board):
    """The tab selects, renames and deletes any arrow, and a rename starts
    from the label as written."""
    board.write_text(BOARD + '@ note n1 0,200 "two\\nlines"\n')
    tab = Tab(served, board.stem, served.keys.viewer)
    _welcome, frame = tab.open()
    els = {e["id"]: e for e in frame["board"]["elements"]}
    assert els["a->b"]["kind"] == "arrow" and els["a->b"]["paths"]
    assert els["a->b"]["text"] == "calls"
    assert els["a"]["text"] == "A"
    assert els["n1"]["text"] == "two\nlines"
    tab.close()


@pytest.mark.parametrize("writer", ["editor", "app"])
def test_a_change_to_the_file_shows_within_a_second(served, board, writer):
    """An editor rewrites the file in place; the desktop app saves through
    atomic_write. Either way the new frame arrives well within a second."""
    tab = Tab(served, board.stem, served.keys.viewer)
    _welcome, first = tab.open()
    times = []
    for i in range(5):
        text = BOARD.replace('"B"', f'"B{i}"')
        t0 = time.time()
        if writer == "editor":
            with open(board, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            atomic_write(board, text)
        # The frame that shows this write; an in-place write can be seen
        # half-done first, and that frame may come before it.
        while True:
            frame = tab.recv_until("frame", timeout=max(t0 + 1.0 - time.time(), 0.01))
            if _labels(frame)["b"] == f"B{i}":
                break
        times.append(time.time() - t0)
        assert frame["version"] > first["version"]
        time.sleep(0.05)
    tab.close()
    assert max(times) < 1.0, times


def test_every_tab_on_the_board_gets_the_change(served, board):
    tabs = [Tab(served, board.stem, served.keys.viewer) for _ in range(3)]
    for t in tabs:
        t.open()
    board.write_text(BOARD.replace('"A"', '"Everyone"'))
    for t in tabs:
        assert _labels(t.recv_until("frame"))["a"] == "Everyone"
        t.close()


# ── Edits from a tab, through the merge ──

def test_an_editor_tab_edits_the_file(served, board):
    tab = Tab(served, board.stem, served.keys.editor)
    welcome, frame = tab.open()
    assert welcome["role"] == "editor"
    ack = tab.edit(frame["version"], {"op": "move", "id": "b", "x": 300, "y": 20})
    assert ack["t"] == "ack" and ack["touched"] == "b" and ack["conflicts"] == []
    assert '@ box b "B" 300,20 120x60' in board.read_text()
    # The frame that shows the edit came before its answer.
    frame = tab.latest()
    assert frame["version"] == ack["version"]
    rect = next(e["rect"] for e in frame["board"]["elements"] if e["id"] == "b")
    assert rect[0] > 280
    tab.close()


def test_a_viewer_tab_cannot_edit(served, board):
    tab = Tab(served, board.stem, served.keys.viewer)
    _welcome, frame = tab.open()
    msg = tab.edit(frame["version"], {"op": "move", "id": "b", "x": 1, "y": 1})
    assert msg["t"] == "error" and "editor link" in msg["message"]
    assert board.read_text() == BOARD
    tab.close()


def test_an_edit_merges_with_a_change_it_did_not_see(served, board):
    """The tab moves a box on the version it saw while an agent renamed the
    other box on disk: the merge keeps both."""
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    seen = frame["version"]
    board.write_text(BOARD.replace('"B"', '"Renamed on disk"'))
    tab.recv_until("frame")
    ack = tab.edit(seen, {"op": "move", "id": "a", "x": 10, "y": 10})
    assert ack["t"] == "ack" and ack["conflicts"] == []
    disk = board.read_text()
    assert '@ box a "A" 10,10' in disk
    assert '"Renamed on disk"' in disk
    tab.close()


def test_a_true_conflict_keeps_the_file_and_is_reported(served, board):
    """Both sides rename the same box: sync.merge_boards keeps the file's
    label and reports the field."""
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    seen = frame["version"]
    board.write_text(BOARD.replace('"A"', '"From disk"'))
    tab.recv_until("frame")
    ack = tab.edit(seen, {"op": "rename", "id": "a", "label": "From tab"})
    assert ack["conflicts"] == [{"kind": "box", "key": "a", "detail": "label"}]
    assert '"From disk"' in board.read_text()
    tab.close()


def test_a_bad_edit_leaves_the_file_alone(served, board):
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    msg = tab.edit(frame["version"], {"op": "move", "id": "zz", "x": 0, "y": 0})
    assert msg["t"] == "error" and "'zz'" in msg["message"]
    msg = tab.edit(-5, {"op": "move", "id": "a", "x": 0, "y": 0})
    assert msg["t"] == "error" and "too old" in msg["message"]
    assert board.read_text() == BOARD
    tab.close()


def test_a_nan_coordinate_is_refused_and_the_socket_stays_open(served, board):
    """Starlette's JSON reader takes a bare NaN; the edit is answered with an
    error, the file is untouched and the next edit still goes through."""
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    tab.ws.send('{"t": "edit", "id": 7, "base": %d, '
                '"op": {"op": "move", "id": "a", "x": NaN, "y": 0}}'
                % frame["version"])
    msg = tab.recv_until("error")
    assert msg["id"] == 7 and "finite" in msg["message"]
    assert board.read_text() == BOARD
    ack = tab.edit(frame["version"], {"op": "move", "id": "a", "x": 5, "y": 5})
    assert ack["t"] == "ack"
    tab.close()


# ── Answers that name their frame, and undo per author ──

def test_an_edit_is_answered_once_its_frame_is_pushed(served, board):
    """The ack names the version that shows the edit, and that frame came
    first: the tab can drop its placeholder on the ack."""
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    ack = tab.edit(frame["version"], {"op": "add_box", "label": "C",
                                      "beside": "b", "connect": True})
    assert ack["t"] == "ack" and ack["touched"] == "box1"
    assert ack["version"] > frame["version"]
    shown = next(f for f in tab.frames if f["version"] == ack["version"])
    assert _labels(shown)["box1"] == "C"
    tab.close()


def test_an_edit_that_changes_nothing_names_the_frame_on_screen(served, board):
    tab = Tab(served, board.stem, served.keys.editor)
    _welcome, frame = tab.open()
    ack = tab.edit(frame["version"], {"op": "rename", "id": "a", "label": "A"})
    assert ack["version"] == frame["version"]
    tab.close()


def test_undo_takes_back_only_the_authors_own_edit(served, board):
    """Two editors; one adds a box, the other renames a box. Undo in the
    first tab takes the box away and keeps the other's rename."""
    mine = Tab(served, board.stem, served.keys.editor, author="me")
    theirs = Tab(served, board.stem, served.keys.editor, author="them")
    _w, frame = mine.open()
    theirs.open()
    mine.edit(frame["version"], {"op": "add_box", "label": "Mine",
                                 "beside": "a"})
    seen = mine.latest()["version"]
    theirs.edit(seen, {"op": "rename", "id": "b", "label": "Theirs"})
    ack = mine.undo()
    assert ack["t"] == "ack" and ack["undone"] and ack["touched"] == "box1"
    disk = board.read_text()
    assert '"Mine"' not in disk and '"Theirs"' in disk
    assert mine.undo()["message"] == "nothing of yours to undo"
    ack = theirs.undo()
    assert ack["t"] == "ack" and '"Theirs"' not in board.read_text()
    assert board.read_text() == BOARD
    mine.close()
    theirs.close()


def test_undo_goes_back_step_by_step(served, board):
    tab = Tab(served, board.stem, served.keys.editor, author="steps")
    _w, frame = tab.open()
    for label in ("one", "two", "three"):
        tab.edit(tab.latest()["version"],
                 {"op": "rename", "id": "a", "label": label})
    for expected in ("two", "one", "A"):
        assert tab.undo()["t"] == "ack"
        assert f'@ box a "{expected}"' in board.read_text()
    tab.close()


def test_undo_survives_a_reconnect_with_the_same_author(served, board):
    tab = Tab(served, board.stem, served.keys.editor, author="reloads")
    _w, frame = tab.open()
    tab.edit(frame["version"], {"op": "delete", "id": "b"})
    tab.close()
    again = Tab(served, board.stem, served.keys.editor, author="reloads")
    again.open()
    assert again.undo()["t"] == "ack"
    assert '@ box b "B"' in board.read_text()
    assert '@ arrow a -> b "calls"' in board.read_text()
    again.close()


def test_undoing_an_added_box_drops_an_arrow_others_drew_to_it(served, board):
    mine = Tab(served, board.stem, served.keys.editor, author="adder")
    theirs = Tab(served, board.stem, served.keys.editor, author="linker")
    _w, frame = mine.open()
    theirs.open()
    mine.edit(frame["version"], {"op": "add_box", "label": "New",
                                 "x": 0, "y": 200})
    theirs.edit(mine.latest()["version"],
                {"op": "connect", "from": "a", "to": "box1"})
    assert mine.undo()["t"] == "ack"
    disk = board.read_text()
    assert "box1" not in disk
    assert disk == BOARD
    mine.close()
    theirs.close()


def test_a_watch_tab_cannot_undo(served, board):
    tab = Tab(served, board.stem, served.keys.viewer)
    tab.open()
    msg = tab.undo()
    assert msg["t"] == "error" and "editor link" in msg["message"]
    tab.close()


def test_a_command_line_edit_over_the_socket(served, board):
    tab = Tab(served, board.stem, served.keys.editor)
    _w, frame = tab.open()
    ack = tab.edit(frame["version"], {
        "op": "lines", "beside": "b",
        "text": '@ box cache "Cache"\n@ arrow b -> cache "fills"'})
    assert ack["t"] == "ack" and ack["touched"] == "cache"
    disk = board.read_text()
    assert '@ box cache "Cache" 240,100 120x60' in disk
    assert '@ arrow b -> cache "fills"' in disk
    tab.close()


def test_a_level_into_another_board_opens_its_live_page(served):
    res = served.root / "top-res"
    res.mkdir()
    (res / "inner.grafli").write_text(BOARD)
    top = served.root / "top.grafli"
    top.write_text('#!grafli v1\n@ box z "Zoom in" 0,0 160x80 &graph:inner\n')
    tab = Tab(served, "top", served.keys.viewer)
    _welcome, frame = tab.open()
    assert frame["board"]["file"] == "top.grafli"
    z = next(e for e in frame["board"]["elements"] if e["id"] == "z")
    assert z["level"]["href"] == "/b/top-res/inner"
    tab.close()


def test_a_cancelled_render_does_not_hand_its_frame_to_the_next(tmp_path):
    """A room that closes mid-render cancels its request; the worker's late
    answer must not become the next board's frame."""
    import asyncio
    from grafli.serve.render import RenderWorker
    a = tmp_path / "a.grafli"
    a.write_text(BOARD)
    b = tmp_path / "b.grafli"
    b.write_text(BOARD)

    async def go():
        worker = RenderWorker()
        try:
            await worker.shell()
            first = asyncio.create_task(worker.render(a, BOARD, tmp_path))
            await asyncio.sleep(0.005)
            first.cancel()
            try:
                await first
            except asyncio.CancelledError:
                pass
            return await worker.render(b, BOARD, tmp_path)
        finally:
            await worker.close()

    assert asyncio.run(go())["board"]["file"] == "b.grafli"
