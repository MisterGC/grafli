"""`grafli export-html`: one self-contained page with every reachable board.

The page carries each board's SVG once per overlay state and a JSON block
with what the page script needs: element rects in board coordinates, the
levels they lead into, box docs as HTML and overlay legends. These tests read
that page; the walk through it in a browser is checked by hand (see the PR).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PySide6.QtWidgets import QApplication

from grafli.fonts import register_bundled_fonts
from grafli.htmlexport import export_html, reachable_boards

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app():
    app = QApplication.instance() or QApplication([])
    register_bundled_fonts()
    return app


OVERLAY = {
    "title": "Tests",
    "producer": "overlay_tests.py",
    "kind": "category",
    "categories": [
        {"id": "pass", "label": "Passing", "color": "%forest"},
        {"id": "fail", "label": "Failing", "color": "%rose"},
    ],
    "entries": {
        "core": {"category": "fail", "note": "flaky",
                 "refs": ["@src/core.py:12"]},
        "api": {"category": "pass"},
    },
}


def _map(tmp: Path) -> Path:
    """A root board with a level (holding a deep link back up), a box doc,
    an overlay file, a link to a board that does not exist, and a link out."""
    root = tmp / "system.grafli"
    root.write_text(
        '#!grafli v3\n'
        '@ box api "API" 300,200 160x70 &doc:api\n'
        '@ box core "Core" 560,200 160x70 &graph:core\n'
        '@ box gone "Gone" 820,200 160x70 &link:missing.grafli\n'
        '@ box web "Web" 300,360 160x70 &link:https://example.org/\n'
        '@ arrow api -> core ~id=calls\n'
        '@ bookmark top "Top" @api,core\n')
    res = tmp / "system-res"
    res.mkdir()
    (res / "api.md").write_text(
        "The API takes requests.\n\nSee [the handler](@src/api.py:7) "
        "and [the spec](https://example.org/spec).\n")
    (res / "core.grafli").write_text(
        '#!grafli v3\n'
        '@ box loop "Loop" 0,0 140x60\n'
        '@ box up "Up" 200,0 140x60 &link:../system.grafli#top\n')
    (res / "tests.overlay.json").write_text(json.dumps(OVERLAY))
    return root


def _data(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="grafli-data">'
                  r'(.*?)</script>', page, re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def _el(board: dict, elem_id: str) -> dict:
    return next(e for e in board["elements"] if e["id"] == elem_id)


def test_reachable_boards_go_in_once_each_and_a_missing_one_warns(tmp_path):
    root = _map(tmp_path)
    paths, warnings = reachable_boards(root)
    assert paths == [root.resolve(),
                     (tmp_path / "system-res" / "core.grafli").resolve()]
    assert len(warnings) == 1
    assert "missing.grafli" in warnings[0]


def test_the_page_holds_every_board_its_levels_docs_and_overlays(tmp_path):
    _app()
    root = _map(tmp_path)
    out = tmp_path / "out" / "system.html"
    result = export_html(root, out)
    page = out.read_text(encoding="utf-8")
    assert result.size == out.stat().st_size
    data = _data(page)
    assert set(data["boards"]) == {"b0", "b1"}
    top, sub = data["boards"]["b0"], data["boards"]["b1"]

    # Levels lead into boards of the page; a deep link keeps its target.
    assert _el(top, "core")["level"] == {"board": "b1", "target": ""}
    assert _el(sub, "up")["level"] == {"board": "b0", "target": "top"}
    assert "level" not in _el(top, "gone")
    assert _el(top, "web")["url"] == "https://example.org/"

    # The box doc goes in as HTML, its local ref as plain text.
    doc = data["docs"][_el(top, "api")["doc"]]
    assert "The API takes requests." in doc
    assert "@src/api.py:7" not in doc and "the handler" in doc
    assert 'href="https://example.org/spec"' in doc

    # One drawing without an overlay and one per overlay file.
    assert [s["name"] for s in top["states"]] == ["", "tests.overlay.json"]
    assert [s["name"] for s in sub["states"]] == [""]
    legend = top["states"][1]["legend"]
    assert [label for label, _ in legend["categories"]] == ["Passing",
                                                           "Failing"]
    assert legend["details"]["core"] == {
        "reading": "Failing", "note": "flaky", "refs": ["@src/core.py:12"]}
    for state in top["states"] + sub["states"]:
        assert f'<template id="svg-{state["svg"]}"><svg ' in page
    assert top["states"][1]["background"] != top["states"][0]["background"]

    # Arrows with an id get a click path; bookmarks keep their rect.
    assert _el(top, "calls")["paths"]
    assert top["bookmarks"]["top"]["rect"][2] > 0


def test_rects_are_board_coordinates_inside_the_drawing(tmp_path):
    _app()
    root = _map(tmp_path)
    out = tmp_path / "system.html"
    export_html(root, out)
    page = out.read_text(encoding="utf-8")
    top = _data(page)["boards"]["b0"]
    x, y, w, h = _el(top, "api")["rect"]
    assert abs(x - 300) <= 2 and abs(y - 200) <= 2
    assert abs(w - 160) <= 4 and abs(h - 70) <= 4
    bx, by, bw, bh = top["bounds"]
    viewbox = re.search(r'<template id="svg-b0-0"><svg [^>]*viewBox="([^"]+)"',
                        page).group(1)
    assert [float(v) for v in viewbox.split()] == [bx, by, bw, bh]
    assert bx < x and by < y and x + w < bx + bw and y + h < by + bh


def test_the_page_needs_no_network_and_carries_no_local_paths(tmp_path):
    _app()
    root = _map(tmp_path)
    out = tmp_path / "system.html"
    export_html(root, out)
    page = out.read_text(encoding="utf-8")
    assert "<script src" not in page and "<link" not in page
    assert "url(http" not in page
    assert str(tmp_path) not in page
    fonts = json.loads(re.search(
        r'<script type="application/json" id="grafli-fonts">(.*?)</script>',
        page, re.S).group(1))
    assert {(f["family"], f["weight"]) for f in fonts} >= {
        ("JetBrainsMono Nerd Font", "400"), ("Patrick Hand", "400")}


def test_cli_prints_the_size_and_warns_when_big(tmp_path, capsys,
                                                 monkeypatch):
    from grafli import htmlexport
    from grafli.app import _cmd_export_html
    root = _map(tmp_path)
    out = tmp_path / "system.html"
    assert _cmd_export_html([str(root), str(out)]) == 0
    captured = capsys.readouterr()
    assert re.search(r"Wrote .*system\.html \(\d+(\.\d)? [KM]B, 2 boards\)",
                     captured.out)
    assert "missing.grafli" in captured.err
    assert "above" not in captured.err

    monkeypatch.setattr(htmlexport, "SIZE_WARN_BYTES", 1024)
    assert _cmd_export_html([str(root), str(out)]) == 0
    assert "above 1 KB" in capsys.readouterr().err


def test_cli_rejects_a_missing_input_and_a_wrong_suffix(tmp_path):
    from grafli.app import _cmd_export_html
    root = _map(tmp_path)
    assert _cmd_export_html([str(tmp_path / "nope.grafli"),
                             str(tmp_path / "x.html")]) == 2
    assert _cmd_export_html([str(root), str(tmp_path / "x.pdf")]) == 2


def test_the_menu_entry_sits_with_the_exports_and_writes_the_page(
        tmp_path, monkeypatch):
    _app()
    from PySide6.QtWidgets import QFileDialog
    from grafli.app import MainWindow
    root = _map(tmp_path)
    out = tmp_path / "menu.html"
    w = MainWindow(str(root))
    panel = w._side_panel
    exports = [b for b, wdg in panel._buttons.items()
               if wdg in panel._sections["export"]]
    assert exports[-3:] == ["export_flow_pdf", "export_flow_pptx",
                            "export_html"]
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    toasts = []
    monkeypatch.setattr(w._view, "toast",
                        lambda msg, *a, **k: toasts.append(msg))
    w._on_tool_activated("export_html")
    assert out.is_file()
    assert toasts and toasts[-1].startswith("HTML exported · ")
    assert "2 boards" in toasts[-1]


def _tour_map(tmp: Path) -> Path:
    """A board whose tour has a stop on itself, two in a sub-board nothing
    else links to (one framing an arrow) and one in a board that is gone."""
    root = tmp / "shop.grafli"
    root.write_text(
        '#!grafli v3\n'
        '@ box web "Web" 0,0 160x70\n'
        '@ box api "API" 300,0 160x70\n'
        '@ bookmark entry "Entry" @web,api "Requests come in."\n'
        '@ flow path "Order path" entry:2 steps#pay:3 '
        'steps#done:focus=complete gone#x:1\n')
    res = tmp / "shop-res"
    res.mkdir()
    (res / "steps.grafli").write_text(
        '#!grafli v3\n'
        '@ box pay "Pay" 0,0 140x60\n'
        '@ box save "Save" 240,0 140x60\n'
        '@ arrow pay -> save ~id=charge\n'
        '@ bookmark pay "Pay" @charge\n'
        '@ bookmark done "Done" @save "Saved."\n')
    return root


def test_boards_a_tour_stops_in_go_in_and_a_missing_one_warns(tmp_path):
    root = _tour_map(tmp_path)
    paths, warnings = reachable_boards(root)
    assert paths == [root.resolve(),
                     (tmp_path / "shop-res" / "steps.grafli").resolve()]
    assert len(warnings) == 1
    assert "the tour 'path' stops in gone.grafli" in warnings[0]


def test_each_stop_carries_its_board_and_dwell_and_the_page_its_player(
        tmp_path):
    _app()
    root = _tour_map(tmp_path)
    out = tmp_path / "shop.html"
    export_html(root, out)
    page = out.read_text(encoding="utf-8")
    data = _data(page)
    top, sub = data["boards"]["b0"], data["boards"]["b1"]
    assert top["flows"] == [{"id": "path", "label": "Order path", "steps": [
        {"board": "b0", "bookmark": "entry", "dwell": 2.0, "focus": ""},
        {"board": "b1", "bookmark": "pay", "dwell": 3.0, "focus": ""},
        {"board": "b1", "bookmark": "done", "dwell": None,
         "focus": "complete"},
        {"board": None, "bookmark": "x", "dwell": 1.0, "focus": ""},
    ]}]
    assert data["dwell"] == 4.0
    # Each stop's bookmark sits on its board; a path stop names its arrow.
    assert top["bookmarks"]["entry"]["description"] == "Requests come in."
    assert sub["bookmarks"]["pay"]["arrows"] == ["charge"]
    assert "arrows" not in sub["bookmarks"]["done"]
    assert _el(sub, "charge")["paths"]
    for part in ('id="tour"', 'id="player"', 'id="pl-prev"', 'id="pl-play"',
                 'id="pl-next"', 'id="pl-bar"', 'id="pl-dwell"'):
        assert part in page
