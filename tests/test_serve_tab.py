"""The presenter's keys in a grafli serve tab, in headless Chrome: a real
server, the real render worker, and key presses sent the way a keyboard
sends them (Chrome's DevTools protocol). Skipped when no Chrome or Chromium
is found; ``GRAFLI_CHROME`` names one."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("starlette")
pytest.importorskip("uvicorn")
websockets_sync = pytest.importorskip("websockets.sync.client")

from grafli.serve import server as srv  # noqa: E402
from grafli.serve.render import RenderWorker  # noqa: E402

_MAC_APPS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
             "/Applications/Chromium.app/Contents/MacOS/Chromium"]


def find_chrome() -> str | None:
    named = os.environ.get("GRAFLI_CHROME")
    if named:
        return named
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in _MAC_APPS if os.path.exists(p)), None)


CHROME = find_chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="no Chrome or Chromium")


class SlowRenderer:
    """The real worker, holding every frame after the first back for
    *delay_s*: long enough to see an edit's placeholder on screen."""

    def __init__(self, delay_s: float):
        self.inner = RenderWorker()
        self.delay_s = delay_s
        self.renders = 0

    async def shell(self):
        return await self.inner.shell()

    async def render(self, path, text, root):
        self.renders += 1
        if self.renders > 1:
            await asyncio.sleep(self.delay_s)
        return await self.inner.render(path, text, root)

    async def close(self):
        await self.inner.close()


class Served:
    def __init__(self, root: Path, renderer=None, reveal=False):
        import uvicorn
        self.root = root
        self.keys = srv.Keys()
        self.sock = srv.bind("127.0.0.1", 0)
        self.port = self.sock.getsockname()[1]
        app = srv.create_app(root, self.keys, renderer, reveal=reveal)
        self.server = uvicorn.Server(uvicorn.Config(
            app, log_level="warning", ws="auto", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run,
                                       kwargs={"sockets": [self.sock]},
                                       daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)

    def link(self, name: str, role: str = "editor") -> str:
        key = self.keys.editor if role == "editor" else self.keys.viewer
        return srv.link("127.0.0.1", self.port, name, key)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(10)
        self.sock.close()


class Chrome:
    """Headless Chrome with one tab, driven over the DevTools protocol."""

    def __init__(self, width=1400, height=900):
        self.profile = tempfile.mkdtemp(prefix="grafli-chrome-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--remote-debugging-port=0",
             f"--user-data-dir={self.profile}", "--no-first-run",
             "--no-default-browser-check", "--disable-gpu",
             f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        url = None
        deadline = time.monotonic() + 30
        while url is None and time.monotonic() < deadline:
            line = self.proc.stderr.readline()
            m = re.search(r"DevTools listening on (ws://\S+)", line)
            if m:
                url = m.group(1)
        if url is None:
            self.close()
            raise RuntimeError("Chrome did not open its DevTools port")
        self._conn = websockets_sync.connect(url, max_size=None)
        self.ws = self._conn.__enter__()
        self.next_id = 0
        target = self.call("Target.createTarget", url="about:blank")["targetId"]
        self.session = self.call("Target.attachToTarget", targetId=target,
                                 flatten=True)["sessionId"]
        self.call("Page.enable", session=True)
        self.call("Runtime.enable", session=True)

    def call(self, method, session=False, **params):
        self.next_id += 1
        msg = {"id": self.next_id, "method": method, "params": params}
        if session:
            msg["sessionId"] = self.session
        self.ws.send(json.dumps(msg))
        while True:
            reply = json.loads(self.ws.recv(timeout=30))
            if reply.get("id") == self.next_id:
                if "error" in reply:
                    raise RuntimeError(f"{method}: {reply['error']}")
                return reply.get("result", {})

    def js(self, expr):
        out = self.call("Runtime.evaluate", session=True, expression=expr,
                        returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in out:
            raise RuntimeError(f"{expr}: {out['exceptionDetails']}")
        return out["result"].get("value")

    def wait(self, expr, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.js(expr):
                return
            time.sleep(0.02)
        raise TimeoutError(f"never true: {expr}")

    def open(self, url):
        self.call("Page.navigate", session=True, url=url)

    _NAMED = {"Enter": 13, "Escape": 27, "Delete": 46, "Backspace": 8,
              "ArrowDown": 40, "ArrowUp": 38, "ArrowLeft": 37, "ArrowRight": 39}

    def key(self, key, shift=False, ctrl=False, meta=False):
        """Press and let go of *key* (a character or a key name)."""
        mods = (8 if shift else 0) | (2 if ctrl else 0) | (4 if meta else 0)
        down = {"type": "keyDown", "key": key, "modifiers": mods}
        if key in self._NAMED:
            down["windowsVirtualKeyCode"] = self._NAMED[key]
            down["code"] = key
            if key == "Enter":
                down["text"] = "\r"
        elif not (ctrl or meta):
            down["text"] = key
            down["windowsVirtualKeyCode"] = ord(key.upper())
        else:
            down["windowsVirtualKeyCode"] = ord(key.upper())
        self.call("Input.dispatchKeyEvent", session=True, **down)
        self.call("Input.dispatchKeyEvent", session=True, type="keyUp",
                  key=key, modifiers=mods,
                  windowsVirtualKeyCode=down["windowsVirtualKeyCode"])

    def keys(self, text):
        for ch in text:
            self.key(ch, shift=ch.isupper() or ch == ":")

    def type(self, text):
        """Type into the focused field."""
        self.call("Input.insertText", session=True, text=text)

    def screenshot(self, path: Path):
        import base64
        data = self.call("Page.captureScreenshot", session=True,
                         format="png")["data"]
        path.write_bytes(base64.b64decode(data))

    def close(self):
        try:
            self._conn.__exit__(None, None, None)
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)


# ── Driving the tab the way a presenter does ──

def settled(chrome):
    chrome.wait("grafliLive.pending() === 0 && grafliEdit.ghosts() === 0")


def jump_to(chrome, label, key="f"):
    """Press *key* (f selects, c connects), then the jump label of the
    element labelled *label*."""
    chrome.key(key)
    chrome.wait("grafliEdit.jump() !== null")
    elem = chrome.js("grafliPage.current().elements.find("
                     f"(e) => e.label === {json.dumps(label)}).id")
    jump = chrome.js(f"grafliEdit.labelOf({json.dumps(elem)})")
    assert jump, f"no jump label on {label!r}"
    chrome.keys(jump)
    return elem


def new_box(chrome, label, shift=False, side=None):
    """o (O with *shift*; Ctrl+arrow towards *side*), the label, Enter."""
    if side:
        chrome.key(side, ctrl=True)
    else:
        chrome.key("O" if shift else "o", shift=shift)
    chrome.wait("grafliEdit.field() !== null")
    chrome.type(label)
    chrome.key("Enter")
    settled(chrome)
    chrome.wait("(() => { const s = grafliPage.selectedEl();"
                f" return s && s.label === {json.dumps(label)}; }})()")


def boxes(path: Path) -> dict[str, str]:
    from grafli.format import parse
    board = parse(path.read_text())
    return {b.id: b.label for b in board.boxes}


def arrows(path: Path) -> set[tuple[str, str]]:
    from grafli.format import parse
    return {(a.from_id, a.to_id) for a in parse(path.read_text()).arrows}


@pytest.fixture(scope="module")
def chrome():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    c = Chrome()
    yield c
    c.close()


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    s = Served(tmp_path_factory.mktemp("tab-boards"))
    yield s
    s.stop()


def open_board(chrome, served, name, text, role="editor"):
    path = served.root / f"{name}.grafli"
    path.write_text(text, encoding="utf-8")
    chrome.open(served.link(name, role))
    chrome.wait("window.grafliPage && grafliPage.board() !== null"
                " && window.grafliLive && grafliLive.role() !== null")
    return path


# ── The board of five, with keys only ──

def test_five_connected_boxes_built_with_keys_only(chrome, served):
    """From an empty board: o, Ctrl+arrow and a label make each box,
    connected from the selection; : adds one in grafli syntax; c and jump
    labels connect; e renames; x deletes and u takes edits back. No mouse,
    no script."""
    path = open_board(chrome, served, "five", "#!grafli v1\n")
    shots = os.environ.get("GRAFLI_TAB_SHOTS")

    new_box(chrome, "Api")
    new_box(chrome, "Cache")
    new_box(chrome, "DB", side="ArrowRight")
    chrome.key(":", shift=True)
    chrome.wait("grafliEdit.command()")
    chrome.type('@ box queue "Queue"')
    chrome.key("Enter")
    settled(chrome)
    chrome.wait("grafliPage.selected() === 'queue'")
    new_box(chrome, "Worker")

    # Z fits the board in view, so every box has a jump label.
    chrome.key("Z", shift=True)
    # DB → Queue: select DB by its label, then c and Queue's label.
    jump_to(chrome, "DB")
    jump_to(chrome, "Queue", key="c")
    settled(chrome)
    # Api → DB: c with nothing selected picks both ends.
    chrome.key("Escape")
    chrome.key("c")
    chrome.wait("grafliEdit.jump() !== null")
    if shots:
        chrome.screenshot(Path(shots) / "connect-labels.png")
    for label in ("Api", "DB"):
        elem = chrome.js("grafliPage.current().elements.find("
                         f"(e) => e.label === {json.dumps(label)}).id")
        chrome.keys(chrome.js(f"grafliEdit.labelOf({json.dumps(elem)})"))
    settled(chrome)

    # Rename Cache.
    jump_to(chrome, "Cache")
    chrome.key("e")
    chrome.wait("grafliEdit.field() === 'Cache'")
    chrome.type("Redis cache")
    chrome.key("Enter")
    settled(chrome)

    # A box too many: delete it, undo the delete, undo the add.
    jump_to(chrome, "Worker")
    new_box(chrome, "Oops")
    chrome.key("x")
    settled(chrome)
    assert "Oops" not in boxes(path).values()
    chrome.key("u")
    settled(chrome)
    assert "Oops" in boxes(path).values()
    chrome.key("u")
    settled(chrome)

    labels = boxes(path)
    assert sorted(labels.values()) == ["Api", "DB", "Queue", "Redis cache", "Worker"]
    ids = {label: id_ for id_, label in labels.items()}
    assert arrows(path) == {
        (ids["Api"], ids["Redis cache"]), (ids["Redis cache"], ids["DB"]),
        (ids["DB"], ids["Queue"]), (ids["Queue"], ids["Worker"]),
        (ids["Api"], ids["DB"]),
    }
    # The tab shows what the file holds.
    shown = chrome.js("grafliPage.current().elements.filter((e) => e.rect)"
                      ".map((e) => e.label).sort()")
    assert shown == sorted(labels.values())
    if shots:
        chrome.key("Escape")
        chrome.key("Z", shift=True)
        time.sleep(2.5)
        chrome.screenshot(Path(shots) / "five-boxes.png")
        (Path(shots) / "five.grafli").write_text(path.read_text())


def test_a_watch_tab_selects_but_does_not_edit(chrome, served):
    text = '#!grafli v1\n@ box a "A" 0,0 160x80\n'
    path = open_board(chrome, served, "watched", text, role="viewer")
    jump_to(chrome, "A")
    chrome.wait("grafliPage.selected() === 'a'")
    for key in ("o", "x", "u"):
        chrome.key(key)
    chrome.wait("document.getElementById('toast').textContent"
                ".includes('for watching')")
    assert chrome.js("grafliEdit.field()") is None
    assert path.read_text() == text


def test_plain_language_on_the_command_line_says_no_agent_is_connected(
        chrome, served):
    text = '#!grafli v1\n@ box a "A" 0,0 160x80\n'
    path = open_board(chrome, served, "plain", text)
    chrome.key(":", shift=True)
    chrome.wait("grafliEdit.command()")
    chrome.type("add a cache between api and db")
    chrome.key("Enter")
    chrome.wait("document.getElementById('toast').textContent"
                ".includes('none is connected')")
    assert chrome.js("grafliLive.pending()") == 0
    assert path.read_text() == text


# ── Placeholders until the render arrives ──

@pytest.fixture
def slow(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    s = Served(tmp_path, SlowRenderer(1.5))
    yield s
    s.stop()


def test_an_edit_shows_a_placeholder_until_its_render_arrives(chrome, slow):
    """Renders held back 1.5 s: right after Enter the new box is a dashed
    placeholder with its label, the drawing does not have it yet; once the
    frame lands the placeholder is gone and the drawn box is selected."""
    path = open_board(chrome, slow, "slow",
                      '#!grafli v1\n@ box a "Api" 0,0 160x80\n')
    jump_to(chrome, "Api")
    chrome.key("o")
    chrome.wait("grafliEdit.field() !== null")
    chrome.type("Cache")
    chrome.key("Enter")
    chrome.wait("grafliEdit.ghosts() === 1 && grafliLive.pending() === 1")
    shot = os.environ.get("GRAFLI_TAB_SHOTS")
    if shot:
        chrome.screenshot(Path(shot) / "placeholder.png")
    assert chrome.js("document.querySelector('#ghosts text').textContent") == "Cache"
    assert "Cache" not in chrome.js(
        "grafliPage.current().elements.map((e) => e.label)")
    version = chrome.js("grafliLive.version()")
    settled(chrome)
    assert chrome.js("grafliLive.version()") > version
    assert chrome.js("grafliPage.selectedEl().label") == "Cache"
    assert "Cache" in boxes(path).values()
    if shot:
        chrome.screenshot(Path(shot) / "placeholder-landed.png")

    # A rename waits the same way, its new label over the old.
    chrome.key("e")
    chrome.wait("grafliEdit.field() === 'Cache'")
    chrome.type("Redis")
    chrome.key("Enter")
    chrome.wait("grafliEdit.ghosts() === 1")
    assert chrome.js("grafliPage.selectedEl().label") == "Cache"
    settled(chrome)
    assert chrome.js("grafliPage.selectedEl().label") == "Redis"


def test_a_refused_edit_takes_its_placeholder_away(chrome, slow):
    path = open_board(chrome, slow, "refused",
                      '#!grafli v1\n@ box a "Api" 0,0 160x80\n')
    text = path.read_text()
    chrome.key(":", shift=True)
    chrome.wait("grafliEdit.command()")
    chrome.type('@ box b "B" >nowhere')
    chrome.key("Enter")
    chrome.wait("document.getElementById('toast').textContent"
                ".includes(\"no box 'nowhere'\")")
    settled(chrome)
    assert path.read_text() == text
