"""Rendering for ``grafli serve``: an offscreen-Qt worker process and its client.

The worker (``python -m grafli.serve.render``) keeps one ``GrafliView``
warm and answers one JSON line per request on stdin with one JSON line on
stdout, carrying back the request's ``seq``:

* ``{"t": "shell"}`` → ``{"ok": true, "html": ...}``: the live page, the
  export page with no board in it and the live client, its editing keys,
  presence, mouse gestures and reveal mode added;
* ``{"t": "render", "path", "text", "root"}`` → ``{"ok": true, "board",
  "svgs", "docs", "fonts", "warnings", "ms"}``: *text* drawn as the board at
  *path*, exactly as ``grafli export-html`` draws it. A level into another
  board under *root* becomes a link to that board's live page. ``fonts``
  holds only the faces this worker has not handed out before;
* ``{"t": "png", "path", "text", "root"}`` → ``{"ok": true, "png",
  "width", "height"}``: *text* drawn as a PNG (base64), at most
  ``PNG_MAX_PX`` wide and high — what the board's agent looks at.

``RenderWorker`` is the server's side: it starts the process, sends one
request at a time and restarts the process when it dies. Nothing here
imports Qt outside the worker's ``main``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

LIVE_JS = Path(__file__).parent.parent / "assets" / "serve" / "live.js"
# The presenter's keys, after the live client they build on; presence after
# both, so the keys' jump labels take a key before the laser does.
EDIT_JS = LIVE_JS.with_name("edit.js")
PRESENCE_JS = LIVE_JS.with_name("presence.js")
# The mouse gestures build on the keys' field and placeholders.
MOUSE_JS = LIVE_JS.with_name("mouse.js")
# Reveal mode's keys take their jump labels from the presenter's keys.
REVEAL_JS = LIVE_JS.with_name("reveal.js")

# The longer side of a PNG for the agent, in pixels.
PNG_MAX_PX = 1600

# Large enough for a board with many overlays; a frame is one line.
_LINE_LIMIT = 256 * 1024 * 1024


class RenderError(RuntimeError):
    """The worker could not draw a board."""


class RenderWorker:
    """The server's handle on the render process."""

    def __init__(self, theme: str = "light"):
        self.theme = theme
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._seq = 0

    async def _start(self) -> asyncio.subprocess.Process:
        env = dict(os.environ)
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        return await asyncio.create_subprocess_exec(
            sys.executable, "-m", "grafli.serve.render", "--theme", self.theme,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            env=env, limit=_LINE_LIMIT)

    async def request(self, req: dict) -> dict:
        async with self._lock:
            if self._proc is None or self._proc.returncode is not None:
                self._proc = await self._start()
            proc = self._proc
            assert proc.stdin is not None and proc.stdout is not None
            self._seq += 1
            seq = self._seq
            try:
                proc.stdin.write(json.dumps({**req, "seq": seq}).encode("utf-8")
                                 + b"\n")
                await proc.stdin.drain()
                # A request whose caller was cancelled (a room that closed
                # mid-render) leaves its answer behind; skip to ours.
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        self._proc = None
                        raise RenderError("the render worker went away")
                    out = json.loads(line)
                    if out.get("seq") == seq:
                        break
            except (BrokenPipeError, ConnectionResetError) as e:
                self._proc = None
                raise RenderError(f"the render worker went away: {e}") from e
        if not out.get("ok"):
            raise RenderError(out.get("error", "the render failed"))
        return out

    async def shell(self) -> str:
        return (await self.request({"t": "shell"}))["html"]

    async def render(self, path: Path, text: str, root: Path) -> dict:
        return await self.request({"t": "render", "path": str(path),
                                   "text": text, "root": str(root)})

    async def png(self, path: Path, text: str, root: Path) -> dict:
        return await self.request({"t": "png", "path": str(path),
                                   "text": text, "root": str(root)})

    async def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        assert proc.stdin is not None
        proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 3)
        except TimeoutError:
            proc.kill()
            await proc.wait()


def board_name(root: Path, path: Path) -> str | None:
    """The name a board under *root* has in a live link (its path below
    *root* without ``.grafli``), or None when it lies outside *root*."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    if rel.suffix != ".grafli":
        return None
    return rel.with_suffix("").as_posix()


# ── The worker process ──

def _live_exporter_class():
    from grafli.format import parse
    from grafli.htmlexport import _Exporter
    from grafli.resources import board_link, classify_attachments, load_docs

    class LiveExporter(_Exporter):
        """The export's board drawing, from the text the server holds."""

        def __init__(self):
            super().__init__(Path("."))
            self.text = ""
            self.served_root = Path(".")

        def _read(self, path: Path):
            board = parse(self.text)
            classify_attachments(path, board)
            load_docs(path, board)
            return board

        def _element(self, path, key, el, rect, ids, kind):
            entry = super()._element(path, key, el, rect, ids, kind)
            # What a rename in the tab starts from: the label as written.
            entry["text"] = (el.text if kind == "note"
                             else "" if kind == "image" else el.label)
            link = board_link(path, el)
            if "level" not in entry and link is not None:
                name = board_name(self.served_root, link[0])
                if name is not None and link[0].is_file():
                    entry["level"] = {"board": None, "href": f"/b/{name}",
                                      "target": link[1]}
            return entry

        def board(self, path, key, ids, padding):
            out = super().board(path, key, ids, padding)
            # Live, every drawn arrow can be selected, renamed and deleted;
            # the export lists only those with an id or an attachment.
            listed = {e["id"] for e in out["elements"]}
            arrows = {a.id or f"{a.from_id}->{a.to_id}": a
                      for a in parse(self.text).arrows}
            for line in out["lines"]:
                ref = line["id"] or "->".join(line["ends"])
                arrow = arrows.get(ref)
                if ref in listed or arrow is None:
                    continue
                listed.add(ref)
                out["elements"].append({
                    "id": ref, "kind": "arrow", "paths": line["paths"],
                    "label": arrow.label or f"{arrow.from_id} \u2192 {arrow.to_id}",
                    "text": arrow.label})
            return out

        def png(self, path: Path, text: str, root: Path) -> dict:
            import base64

            from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
            self.text = text
            self.served_root = root
            self._load(path.resolve())
            image = self.view._render_png_image(scale=1, padding=40)
            if max(image.width(), image.height()) > PNG_MAX_PX:
                image = image.scaled(
                    PNG_MAX_PX, PNG_MAX_PX, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            data = QByteArray()
            buf = QBuffer(data)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buf, "PNG")
            buf.close()
            return {"png": base64.b64encode(bytes(data)).decode("ascii"),
                    "width": image.width(), "height": image.height()}

        def frame(self, path: Path, text: str, root: Path) -> dict:
            self.text = text
            self.served_root = root
            self.svgs, self.docs, self.warnings = [], {}, []
            path = path.resolve()
            board = self.board(path, "b0", {path: "b0"}, 40)
            return {"board": board, "svgs": dict(self.svgs),
                    "docs": self.docs, "warnings": self.warnings}

    return LiveExporter


def _shell() -> str:
    from grafli import theme
    from grafli.flows import DEFAULT_DWELL
    from grafli.htmlexport import _page
    data = {"live": True, "root": "b0", "boards": {}, "docs": {},
            "theme": theme.name(), "dwell": DEFAULT_DWELL}
    return _page("grafli", data, [], [],
                 extra_js="\n".join(js.read_text(encoding="utf-8") for js in
                                    (LIVE_JS, EDIT_JS, PRESENCE_JS,
                                     MOUSE_JS, REVEAL_JS)),
                 generator="grafli serve")


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m grafli.serve.render")
    parser.add_argument("--theme", default="light", choices=("light", "dark"))
    args = parser.parse_args(argv)

    # Answers go to a private copy of stdout; anything else printed while
    # drawing lands on stderr and cannot break a frame line.
    out = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from grafli import theme
    from grafli.fonts import register_bundled_fonts
    from grafli.htmlexport import font_data, font_keys
    theme.set_theme(args.theme)
    app = QApplication.instance() or QApplication([])
    register_bundled_fonts()
    exporter = _live_exporter_class()()
    handed_out: set[tuple[str, bool]] = set()

    for line in sys.stdin:
        if not line.strip():
            continue
        t0 = time.perf_counter()
        req: dict = {}
        try:
            req = json.loads(line)
            if req.get("t") == "shell":
                answer = {"ok": True, "html": _shell()}
            elif req.get("t") == "png":
                answer = {"ok": True, **exporter.png(
                    Path(req["path"]), req["text"], Path(req["root"]))}
            else:
                frame = exporter.frame(Path(req["path"]), req["text"],
                                       Path(req["root"]))
                wanted = font_keys(list(frame["svgs"].items()),
                                   bool(frame["docs"])) - handed_out
                handed_out |= wanted
                answer = {"ok": True, **frame, "fonts": font_data(wanted)}
        except Exception as e:  # one bad board must not stop the worker
            answer = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        answer["seq"] = req.get("seq") if isinstance(req, dict) else None
        answer["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        out.write(json.dumps(answer, ensure_ascii=False) + "\n")
        out.flush()
    exporter.view.deleteLater()
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
