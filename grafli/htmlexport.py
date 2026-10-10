"""Interactive HTML export: one self-contained page, the whole map (D17).

``export_html`` writes a board and every board reachable from it through
``&graph``, ``.grafli`` ``&link`` and tour stops in other boards into one
HTML file that needs no server and no internet. Each board is drawn by the
app's own SVG export, once without an overlay and once per overlay file
beside it, so the page looks exactly like the app. A JSON block beside the
SVGs holds what the page needs to act — element rects and ids, attachments,
bookmark rects, box docs as HTML, overlay legends and notes, the tours with
each stop's board and dwell — and the page's script places invisible click
areas from those rects and plays the tours by moving its camera. No second renderer is written in JS.

Code refs (``@path:line``) stay plain text: the people the page is sent to
don't have the checkout. Miniatures and editing are left out.
"""

from __future__ import annotations

import base64
import gzip
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainterPath, QTextDocument

from grafli import theme
from grafli.flows import DEFAULT_DWELL
from grafli.format import Arrow, Board, Image, Note, doc_name, parse
from grafli.format import split_board_fragment, split_step_ref

# Above this the export still writes the page, and says it is heavy to send.
SIZE_WARN_BYTES = 20 * 1024 * 1024

_ASSETS = Path(__file__).parent / "assets" / "html_export"
_FONTS = Path(__file__).parent / "fonts"

# (family, bold) as the SVG names it → the bundled file that draws it.
_FONT_FILES = {
    ("JetBrainsMono Nerd Font", False): "JetBrainsMonoNerdFont-Regular.ttf",
    ("JetBrainsMono Nerd Font", True): "JetBrainsMonoNerdFont-Bold.ttf",
    ("Patrick Hand", False): "PatrickHand-Regular.ttf",
}

_SVG_FONT_RE = re.compile(
    r'font-family="([^"]+)"[^>]*?font-weight="(\d+)"')


@dataclass
class HtmlExport:
    """What an export wrote: its size, the boards in it, and what it had to
    leave out or could not read."""
    path: Path
    size: int
    boards: list[Path]
    warnings: list[str] = field(default_factory=list)

    @property
    def too_big(self) -> bool:
        return self.size > SIZE_WARN_BYTES


def format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


# ── Which boards go in ──

def _board_link(board_path: Path, el) -> tuple[Path, str] | None:
    """The board an element leads into and the ``#<id>`` it frames, or None
    when its attachment is not a board."""
    from grafli.resources import graph_path
    if el.attach_kind == "graph" and el.url:
        name, target = split_board_fragment(el.url)
        return graph_path(board_path, name), target
    if el.attach_kind == "link" and el.url:
        raw, _, target = el.url.partition("#")
        if raw.endswith(".grafli") and "://" not in raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = board_path.parent / path
            return path, target
    return None


def _elements(board: Board):
    yield from board.boxes
    yield from board.notes
    yield from board.images
    yield from board.arrows


def _read_board(path: Path) -> Board:
    from grafli.resources import classify_attachments, load_docs
    board = parse(path.read_text(encoding="utf-8"))
    classify_attachments(path, board)
    load_docs(path, board)
    return board


def _stop_board(board_path: Path, ref: str) -> Path | None:
    """The other board a tour stop ``<board>#<bookmark>`` lies in, or None
    for a stop on the flow's own board."""
    from grafli.resources import board_target_path
    target, _bookmark = split_step_ref(ref)
    return board_target_path(board_path, target) if target else None


def _board_refs(board_path: Path, board: Board):
    """Each board *board* leads to — through a level, a link or a tour stop
    in another board — as (path, what names it)."""
    for el in _elements(board):
        link = _board_link(board_path, el)
        if link is not None:
            yield link[0], f"'{el.id}' links to"
    for flow in board.flows:
        for step in flow.steps:
            path = _stop_board(board_path, step.ref)
            if path is not None:
                yield path, f"the tour '{flow.id}' stops in"


def reachable_boards(root: Path) -> tuple[list[Path], list[str]]:
    """The root board and every board reachable from it — through levels,
    links and tour stops — each once, in the order they are first reached;
    plus a warning per reference to a missing board."""
    root = root.resolve()
    order = [root]
    seen = {root}
    warnings: list[str] = []
    i = 0
    while i < len(order):
        here = order[i]
        i += 1
        for path, what in _board_refs(here, _read_board(here)):
            target = path.resolve()
            if target in seen:
                continue
            if not target.is_file():
                warnings.append(f"{here.name}: {what} "
                                f"{target.name}, which does not exist")
                seen.add(target)
                continue
            seen.add(target)
            order.append(target)
    return order, warnings


# ── Drawing a board ──

def _rect(r: QRectF) -> list[float]:
    return [round(r.x(), 2), round(r.y(), 2),
            round(r.width(), 2), round(r.height(), 2)]


def _svg_body(svg: bytes, rect: QRectF) -> str:
    """The Qt SVG's drawing as one ``<svg>`` in board coordinates, without
    its XML prolog, title and fixed millimetre size."""
    text = svg.decode("utf-8")
    start = text.index("<svg")
    open_end = text.index(">", start) + 1
    end = text.rindex("</svg>")
    inner = re.sub(r"<title>.*?</title>|<desc>.*?</desc>", "",
                   text[open_end:end], flags=re.S)
    x, y, w, h = _rect(rect)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{x} {y} {w} {h}">{inner}</svg>')


def _path_d(path: QPainterPath) -> str:
    """An SVG path ``d`` for a Qt painter path."""
    out: list[str] = []
    i = 0
    n = path.elementCount()
    while i < n:
        el = path.elementAt(i)
        if el.isMoveTo():
            out.append(f"M{el.x:.1f},{el.y:.1f}")
        elif el.isLineTo():
            out.append(f"L{el.x:.1f},{el.y:.1f}")
        elif el.isCurveTo() and i + 2 < n:
            c2, end = path.elementAt(i + 1), path.elementAt(i + 2)
            out.append(f"C{el.x:.1f},{el.y:.1f} {c2.x:.1f},{c2.y:.1f} "
                       f"{end.x:.1f},{end.y:.1f}")
            i += 2
        i += 1
    return " ".join(out)


_LOCAL_LINK_RE = re.compile(
    r'<a href="(?!https?:|mailto:|#)[^"]*">(.*?)</a>', re.S)


def doc_html(body: str) -> str:
    """A box doc's Markdown as HTML, the way the peek renders it; links into
    local files (``@path:line`` refs among them) become plain text."""
    doc = QTextDocument()
    doc.setMarkdown(body, QTextDocument.MarkdownFeature.MarkdownDialectGitHub)
    full = doc.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", full, re.S)
    inner = m.group(1) if m else full
    return _LOCAL_LINK_RE.sub(r"\1", inner).strip()


def _color_hex(color) -> str:
    return color.name() if hasattr(color, "name") else str(color)


def _legend(reading) -> dict:
    legend = reading.legend
    out = {"title": legend.title, "producer": legend.producer,
           "stale": legend.stale}
    if legend.categories:
        out["categories"] = [
            [label, theme.resolve_color(color) or _color_hex(theme.INK)]
            for label, color in legend.categories]
    else:
        out["scale"] = {
            "low": legend.low, "high": legend.high,
            "stops": [[pos, _color_hex(c)] for pos, c in theme.HEATMAP_STOPS],
        }
    out["details"] = {
        elem_id: {"reading": d.reading, "note": d.note, "refs": list(d.refs)}
        for elem_id, d in reading.details.items()}
    return out


class _Exporter:
    def __init__(self, root: Path):
        from grafli.view import GrafliView
        self.root = root.resolve()
        self.view = GrafliView()
        self.docs: dict[str, str] = {}
        self.svgs: list[tuple[str, str]] = []
        self.warnings: list[str] = []

    def _load(self, path: Path) -> Board:
        board = _read_board(path)
        view = self.view
        # The view looks up its board file through its window, which a
        # parentless view is itself.
        view._file_path = path
        view.base_dir = str(path.parent)
        view.load_board(board)
        return board

    def _background(self) -> str:
        """The canvas colour the drawing sits on: an overlay darkens it."""
        brush = self.view._scene.backgroundBrush()
        if brush.style() == Qt.BrushStyle.NoBrush:
            return _color_hex(theme.SCENE_BG)
        return _color_hex(brush.color())

    def _render(self, key: str, padding: int) -> QRectF:
        view = self.view
        bounds = view._scene.itemsBoundingRect()
        if bounds.isNull():
            bounds = QRectF(0, 0, 100, 100)
        rect = bounds.adjusted(-padding, -padding, padding, padding)
        svg = bytes(view._render_svg_bytes(region=rect))
        self.svgs.append((key, _svg_body(svg, rect)))
        return rect

    def _doc_key(self, path: Path, key: str, el) -> str:
        """The key of *el*'s doc in the page's docs, "" when it has none."""
        if el.attach_kind != "doc" or isinstance(el, Note):
            return ""
        body = self.view.box_doc_body(el)
        if body is None:
            self.warnings.append(f"{path.name}: the doc '{doc_name(el)}' of "
                                 f"'{el.id}' is missing")
            return ""
        # Keyed by board id, not by path: the page must not carry local paths.
        doc_key = f"{key}/{doc_name(el)}"
        if doc_key not in self.docs:
            self.docs[doc_key] = doc_html(body)
        return doc_key

    def _element(self, path: Path, key: str, el, rect: QRectF,
                 ids: dict[Path, str], kind: str) -> dict:
        entry = {"id": el.id, "kind": kind, "rect": _rect(rect),
                 "label": self.view._crumb_label(el)}
        parent = getattr(el, "parent", "")
        if parent:
            entry["parent"] = parent
        link = _board_link(path, el)
        if link is not None:
            target = ids.get(link[0].resolve())
            if target is not None:
                entry["level"] = {"board": target, "target": link[1]}
        elif el.attach_kind == "link" and re.match(r"https?://", el.url or ""):
            entry["url"] = el.url
        doc = self._doc_key(path, key, el)
        if doc:
            entry["doc"] = doc
        return entry

    def _arrow_paths(self) -> dict[int, list[str]]:
        """The drawn lines of each arrow, by the arrow object's identity."""
        from grafli.items import ArrowLineItem
        paths: dict[int, list[str]] = {}
        for item in self.view._arrow_items:
            arrow = item.data(0)
            if isinstance(item, ArrowLineItem) and isinstance(arrow, Arrow):
                d = _path_d(item.mapToScene(item.path()))
                paths.setdefault(id(arrow), []).append(d)
        return paths

    def _flows(self, path: Path, key: str, board: Board,
               ids: dict[Path, str]) -> list[dict]:
        """The board's flows, each stop with the board it lies in (None when
        that board is missing) and its dwell (None = the default)."""
        flows = []
        for f in board.flows:
            steps = []
            for s in f.steps:
                _target, bookmark = split_step_ref(s.ref)
                other = _stop_board(path, s.ref)
                stop_board = key if other is None else ids.get(other.resolve())
                steps.append({"board": stop_board, "bookmark": bookmark,
                              "dwell": s.dwell})
            flows.append({"id": f.id, "label": f.label, "steps": steps})
        return flows

    def board(self, path: Path, key: str, ids: dict[Path, str],
              padding: int) -> dict:
        from grafli.flows import bookmark_target_rect, focus_arrows
        from grafli.overlay_file import (OverlayProvider, load_overlay,
                                         overlay_paths)
        board = self._load(path)
        view = self.view
        rect = self._render(f"{key}-0", padding)
        background = self._background()

        elements: list[dict] = []
        items = [(view._box_items, "box"), (view._note_items, "note"),
                 (view._image_items, "image")]
        for table, kind in items:
            for item in table.values():
                el = getattr(item, kind)
                elements.append(self._element(
                    path, key, el, item.sceneBoundingRect(), ids, kind))
        arrow_paths = self._arrow_paths()
        for arrow in board.arrows:
            if not (arrow.id or arrow.url or arrow.attach_kind == "doc"):
                continue
            lines = arrow_paths.get(id(arrow))
            if not lines:
                continue
            entry = self._element(path, key, arrow, QRectF(), ids, "arrow")
            entry["id"] = arrow.id or f"{arrow.from_id}->{arrow.to_id}"
            entry["paths"] = lines
            del entry["rect"]
            elements.append(entry)

        bookmarks = {}
        for bm in board.bookmarks:
            r = bookmark_target_rect(view, bm)
            if not r.isNull():
                bookmarks[bm.id] = {"rect": _rect(r), "label": bm.label,
                                    "description": bm.description}
                # A path stop emphasises the arrows its focus names.
                arrows = [a.id for a in focus_arrows(board, bm.focus)]
                if arrows:
                    bookmarks[bm.id]["arrows"] = arrows
        flows = self._flows(path, key, board, ids)

        states = [{"name": "", "svg": f"{key}-0", "background": background}]
        for i, opath in enumerate(overlay_paths(path), start=1):
            try:
                overlay = load_overlay(opath)
            except ValueError as e:
                self.warnings.append(f"{opath.name}: {e} — left out")
                continue
            provider = OverlayProvider(overlay, opath.parent.parent, opath)
            view._show_heat(provider)
            try:
                self._render(f"{key}-{i}", padding)
                legend = _legend(view._complexity_reading)
                overlay_bg = self._background()
            finally:
                view._clear_complexity_heatmap()
            states.append({"name": opath.name, "svg": f"{key}-{i}",
                           "background": overlay_bg, "legend": legend})

        return {"id": key, "title": path.stem, "file": path.name,
                "bounds": _rect(rect), "states": states,
                "elements": elements, "bookmarks": bookmarks,
                "flows": flows}


def _fonts(svgs: list[tuple[str, str]], docs: bool) -> list[dict]:
    """The bundled fonts the drawings use, gzipped, as base64."""
    wanted: set[tuple[str, bool]] = set()
    for _key, svg in svgs:
        for family, weight in _SVG_FONT_RE.findall(svg):
            wanted.add((family, int(weight) >= 600))
    if docs:
        # The peek's faces: handwritten text, monospace code.
        wanted |= {("Patrick Hand", False), ("JetBrainsMono Nerd Font", False)}
    fonts = []
    for (family, bold), name in sorted(_FONT_FILES.items()):
        if (family, bold) not in wanted:
            continue
        data = gzip.compress((_FONTS / name).read_bytes(), mtime=0)
        fonts.append({"family": family, "weight": "700" if bold else "400",
                      "data": base64.b64encode(data).decode("ascii")})
    return fonts


def _json_script(data) -> str:
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def _page(title: str, data: dict, svgs: list[tuple[str, str]],
          fonts: list[dict]) -> str:
    css = (_ASSETS / "page.css").read_text(encoding="utf-8")
    js = (_ASSETS / "page.js").read_text(encoding="utf-8")
    colors = {
        "--bg": _color_hex(theme.SCENE_BG),
        "--surface": _color_hex(theme.SURFACE),
        "--ink": _color_hex(theme.INK),
        "--accent": _color_hex(theme.FLOWS_ACCENT),
        "--card": _color_hex(theme.OVERLAY_BG),
        "--card-ink": _color_hex(theme.OVERLAY_FG),
    }
    root_vars = "".join(f"{k}:{v};" for k, v in colors.items())
    templates = "\n".join(
        f'<template id="svg-{key}">{svg}</template>' for key, svg in svgs)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="grafli export-html">
<title>{html.escape(title)}</title>
<style>:root{{{root_vars}}}
{css}</style>
</head>
<body>
<header id="bar">
  <button id="back" type="button" title="Back up a level (Backspace, g u)">&#8593; Back</button>
  <nav id="crumbs" aria-label="Board path"></nav>
  <label id="tour-pick" hidden>Tour
    <select id="tour"></select>
  </label>
  <label id="overlay-pick" hidden>Overlay
    <select id="overlay"></select>
  </label>
</header>
<main id="stage-wrap">
  <svg id="stage" xmlns="http://www.w3.org/2000/svg">
    <g id="art"></g>
    <g id="hits"></g>
    <rect id="sel" style="display:none"></rect>
  </svg>
  <aside id="legend" hidden></aside>
  <aside id="peek" hidden><div id="peek-body"></div></aside>
  <aside id="player" hidden aria-live="polite">
    <div class="head"><span id="pl-flow"></span><span id="pl-count"></span></div>
    <div id="pl-label"></div>
    <div id="pl-desc"></div>
    <div class="track"><div id="pl-bar"></div></div>
    <div class="track dwell"><div id="pl-dwell"></div></div>
    <div class="buttons">
      <button id="pl-prev" type="button" title="Previous stop (&#8592;)">&#8249; Prev</button>
      <button id="pl-play" type="button" title="Play or pause (p cycles play, loop, pause)">&#9654; Play</button>
      <button id="pl-next" type="button" title="Next stop (Space, &#8594;)">Next &#8250;</button>
      <button id="pl-close" type="button" title="Leave the tour (Esc)">&#10005;</button>
    </div>
  </aside>
  <div id="toast" hidden></div>
</main>
{templates}
<script type="application/json" id="grafli-data">{_json_script(data)}</script>
<script type="application/json" id="grafli-fonts">{_json_script(fonts)}</script>
<script>
{js}
</script>
</body>
</html>
"""


def export_html(root: Path, out: Path, padding: int = 40) -> HtmlExport:
    """Write *root* and every board reachable from it into one HTML page at
    *out*. Needs a running QApplication with the bundled fonts registered;
    colours follow the active theme."""
    root = Path(root).resolve()
    paths, warnings = reachable_boards(root)
    ids = {p: f"b{i}" for i, p in enumerate(paths)}
    exporter = _Exporter(root)
    exporter.warnings = warnings
    try:
        boards = [exporter.board(p, ids[p], ids, padding) for p in paths]
    finally:
        exporter.view.deleteLater()
    data = {"root": "b0", "boards": {b["id"]: b for b in boards},
            "docs": exporter.docs, "theme": theme.name(),
            "dwell": DEFAULT_DWELL}
    fonts = _fonts(exporter.svgs, bool(exporter.docs))
    page = _page(root.stem, data, exporter.svgs, fonts)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return HtmlExport(out, out.stat().st_size, paths, exporter.warnings)
