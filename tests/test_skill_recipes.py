"""The grafli skill's software-diagram recipes (#308): the state-machine
encoding draws every transition the way the catalogue says, the
architecture exemplar takes its kinds from the palette and keeps its
secondary relations in doc lines, and icons encode kind in software
diagrams while the sketchnote playbook keeps its fill symbols."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from grafli.format import parse
from grafli.skills import skill_references

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "live-session.grafli"
VAULT = ROOT / "examples" / "live-session-res"


def _section(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


def _state_machine_snippet() -> str:
    sec = _section(skill_references()["design.md"], "### State machine",
                   "## 3. Layout strategy")
    return re.search(r"```\n(.*?)```", sec, re.S).group(1)


def _diagnose(path: Path) -> str:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        [sys.executable, "-m", "grafli.app", "diagnose", str(path)],
        capture_output=True, text=True, env=env, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


# ── the state-machine encoding ────────────────────────────────────


def test_the_catalogue_lists_the_state_machine():
    design = skill_references()["design.md"]
    table = _section(design, "| Encoding |", "**When nothing fits.**")
    assert "| state machine |" in table


def test_the_state_machine_snippet_draws_every_part_the_recipe_names():
    board = parse(_state_machine_snippet())
    boxes = {b.id: b for b in board.boxes}
    starts = [b for b in board.boxes if b.round and not b.label]
    assert len(starts) == 1, "one unlabelled round start dot"
    start = starts[0]
    out_of_start = [a for a in board.arrows if a.from_id == start.id]
    assert len(out_of_start) == 1
    ends = [b for b in board.boxes
            if b.round and b.label
            and not any(a.from_id == b.id for a in board.arrows)]
    assert ends, "a round end state no transition leaves"
    assert any(a.from_id == a.to_id for a in board.arrows), "a self-loop"
    for a in board.arrows:
        assert a.from_id in boxes and a.to_id in boxes
        if a.from_id != start.id:
            assert a.label, f"{a.from_id} -> {a.to_id} has no label"
    labels = [a.label for a in board.arrows]
    assert any("[" in l and "]" in l for l in labels), "a guard"
    assert any(" / " in l for l in labels), "an action"


def test_the_state_machine_snippet_diagnoses_clean(tmp_path):
    board = tmp_path / "state-machine.grafli"
    board.write_text(_state_machine_snippet(), encoding="utf-8")
    assert "No findings." in _diagnose(board)


# ── the architecture exemplar ─────────────────────────────────────


def _palette() -> dict:
    return json.loads((VAULT / "palette.json").read_text())["entries"]


def test_the_architecture_recipe_names_its_exemplar():
    genres = skill_references()["genres.md"]
    assert "`examples/live-session.grafli`" in genres
    software = genres[genres.index("## Software diagrams"):]
    for feature in ("palette.json", "--legend", "doc line", "~large"):
        assert feature in software, feature


def test_every_kind_has_an_icon_a_label_and_its_own_icon():
    entries = _palette()
    icons = [e.get("icon") for e in entries.values()]
    assert all(icons), "every kind carries an icon"
    assert len(set(icons)) == len(icons), "one icon per kind"
    assert all(e.get("label") for e in entries.values())


def test_every_box_of_the_exemplar_takes_a_kind_and_has_a_doc_line():
    board = parse(EXAMPLE.read_text(encoding="utf-8"))
    kinds = set(_palette())
    parents = {b.parent for b in board.boxes if b.parent}
    for b in board.boxes:
        if b.id in parents:
            # a layer: a container whose title is the heading
            assert (b.anchor, b.textsize, b.style) == ("topleft", "large",
                                                       "flat"), b.id
            continue
        assert b.color.lstrip("%") in kinds, b.id
        assert not b.icon, f"{b.id}: its icon comes from its kind"
        assert b.attach_kind == "doc", b.id
        doc = (VAULT / f"{b.url}.md").read_text(encoding="utf-8")
        first = doc.split("\n", 1)[0]
        assert first.endswith(".") and len(first) <= 48, (b.id, first)


def test_the_exemplar_doc_refs_point_into_the_code():
    refs = []
    for doc in VAULT.glob("*.md"):
        refs += re.findall(r"`(grafli/[\w/]+\.py):(\d+)`",
                           doc.read_text(encoding="utf-8"))
    assert refs, "the exemplar anchors its claims in the code"
    for path, line in refs:
        lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
        assert int(line) <= len(lines), f"{path}:{line}"


def test_the_exemplar_diagnoses_clean():
    assert "No findings." in _diagnose(EXAMPLE)


# ── icons encode kind ─────────────────────────────────────────────


def test_software_diagrams_let_icons_encode_kind():
    genres = skill_references()["genres.md"]
    software = genres[genres.index("## Software diagrams"):]
    assert "icons encode kind" in software.lower()
    assert "| fill symbols (tiny actor leads" not in software
    design = skill_references()["design.md"]
    assert "Icons encode kind" in design


def test_the_sketchnote_playbook_keeps_its_fill_symbols():
    genres = skill_references()["genres.md"]
    sketchnote = _section(genres, "## Sketchnote", "## Infographic")
    assert "fill symbols (`*person`, `*brain`, `*plant`…)" in sketchnote
