"""Overlay files beside a board: schema, discovery, staleness (#168)."""

from __future__ import annotations

import json
import subprocess

import pytest

from grafli.format import parse
from grafli.overlay_file import (
    OverlayProvider,
    load_overlay,
    overlay_paths,
    parse_overlay,
    stale_line,
)

_BOARD = parse("""\
#!grafli v2
@ box a "A" 0,0 120x60
@ box b "B" 300,0 120x60
@ box c "C" 600,0 120x60
""")

TESTS = {
    "title": "Tests",
    "producer": "scripts/overlay_tests.py (pytest 8.3)",
    "created": "2026-10-09T14:00:00Z",
    "kind": "category",
    "categories": [
        {"id": "pass", "label": "Passing", "color": "%forest"},
        {"id": "fail", "label": "Failing", "color": "%rose"},
    ],
    "entries": {
        "a": {"category": "fail", "note": "drifts", "refs": ["@Game.qml:12"]},
        "b": {"category": "pass"},
    },
}

CHURN = {
    "title": "Churn",
    "kind": "value",
    "scale": {"min": 0, "max": 30, "low": "calm", "high": "hot"},
    "entries": {"a": {"value": 30}, "b": {"value": 15}, "c": {"value": 45}},
}


def _read(data, tmp_path):
    overlay = parse_overlay(json.dumps(data), "x")
    return OverlayProvider(overlay, tmp_path).read(_BOARD)


def test_a_category_file_colours_its_entries_and_leaves_the_rest_no_data(
        tmp_path):
    reading = _read(TESTS, tmp_path)

    assert reading.colors == {"a": "%rose", "b": "%forest"}
    assert reading.values == {}
    assert reading.no_data
    assert reading.legend.title == "Tests"
    assert reading.legend.producer.startswith("scripts/overlay_tests.py")
    assert reading.legend.categories == [("Passing", "%forest"),
                                         ("Failing", "%rose")]
    assert reading.details["a"].reading == "Failing"
    assert reading.details["a"].note == "drifts"
    assert reading.details["a"].refs == ["@Game.qml:12"]
    assert "c" not in reading.details


def test_a_value_file_maps_onto_its_scale_not_the_board_maximum(tmp_path):
    reading = _read(CHURN, tmp_path)

    assert reading.values == {"a": 1.0, "b": 0.5, "c": 1.0}
    assert (reading.legend.low, reading.legend.high) == ("calm", "hot")
    assert reading.details["c"].reading == "45"


@pytest.mark.parametrize("patch, message", [
    ({"kind": "heat"}, "'kind'"),
    ({"categories": []}, "'categories'"),
    ({"entries": {"a": {"category": "flaky"}}}, "unknown category 'flaky'"),
    ({"entries": {"a": {"category": "pass", "refs": "x"}}}, "'refs'"),
    ({"entries": []}, "'entries'"),
])
def test_a_broken_file_says_what_is_wrong(patch, message):
    with pytest.raises(ValueError, match=message):
        parse_overlay(json.dumps({**TESTS, **patch}), "x")


def test_a_value_entry_needs_a_number():
    data = {**CHURN, "entries": {"a": {"value": "high"}}}
    with pytest.raises(ValueError, match="entry 'a': 'value'"):
        parse_overlay(json.dumps(data), "x")


def test_not_json_is_an_error():
    with pytest.raises(ValueError, match="not JSON"):
        parse_overlay("{", "x")


def test_overlay_files_are_found_in_the_vault_in_name_order(tmp_path):
    board = tmp_path / "map.grafli"
    assert overlay_paths(board) == []
    vault = tmp_path / "map-res"
    vault.mkdir()
    for name in ("tests", "churn"):
        (vault / f"{name}.overlay.json").write_text(json.dumps(TESTS))
    (vault / "notes.md").write_text("not an overlay")

    paths = overlay_paths(board)
    assert [p.name for p in paths] == ["churn.overlay.json",
                                       "tests.overlay.json"]
    assert load_overlay(paths[1]).name == "tests"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True)


def _commit(repo, text):
    (repo / "f.txt").write_text(text)
    _git(repo, "add", "f.txt")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm",
         text)
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          check=True, capture_output=True,
                          text=True).stdout.strip()


def test_a_revision_behind_head_is_stale(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    old = _commit(repo, "one")
    head = _commit(repo, "two")

    def overlay(rev):
        return parse_overlay(json.dumps(
            {**TESTS, "source": {"repo": "repo", "revision": rev}}), "x")

    assert stale_line(overlay(head[:7]), tmp_path) == ""
    assert stale_line(overlay(old), tmp_path) == (
        f"stale: analysed at {old[:7]}, repo is at {head[:7]}")
    assert _read({**TESTS, "source": {"repo": str(repo), "revision": old}},
                 tmp_path).legend.stale.startswith("stale: analysed at")


def test_without_a_source_nothing_is_stale(tmp_path):
    assert _read(TESTS, tmp_path).legend.stale == ""
