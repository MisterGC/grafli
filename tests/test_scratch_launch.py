"""No-file launch falls back to a persistent scratch board.

Starting `grafli` with no path used to open an in-memory untitled buffer that
autosave never touched (no path), so the board was lost on close. It now
resolves to `~/grafli-scratch.grafli`, which `_open_file` creates and autosaves.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from grafli.app import SCRATCH_FILENAME, _resolve_launch_file


def test_no_file_resolves_to_home_scratch():
    resolved = _resolve_launch_file(None)
    assert resolved == Path.home() / SCRATCH_FILENAME
    assert resolved.suffix == ".grafli"


def test_explicit_file_is_kept():
    assert _resolve_launch_file("/tmp/board.grafli") == Path("/tmp/board.grafli")


def test_empty_string_falls_back_to_scratch():
    # argparse yields None for a missing positional, but guard the empty
    # string too so a stray "" arg can't launch a pathless board.
    assert _resolve_launch_file("") == Path.home() / SCRATCH_FILENAME
