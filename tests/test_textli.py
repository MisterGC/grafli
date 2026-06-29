"""textli standalone launcher: location (``path#heading-slug``) + read/write
mode, for the CLI and the host API."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from grafli.textli import TextliHost, split_location  # noqa: E402

MD = (
    "# Intro\n\nbody intro.\n\n"
    "## Design Decisions\n\nbody design.\n\n"
    "## Final Notes\n\nbody final.\n"
)


# ── location parsing ──

def test_split_location_plain_path():
    assert split_location("notes.md") == ("notes.md", "")


def test_split_location_with_anchor():
    assert split_location("notes.md#design-decisions") == (
        "notes.md", "design-decisions",
    )


def test_split_location_only_first_hash_starts_fragment():
    # slugs are [a-z0-9-]; the first '#' begins the fragment
    assert split_location("a.md#one#two") == ("a.md", "one#two")


# ── host forwards location + mode to the editor ──

def _host():
    QApplication.instance() or QApplication([])
    host = TextliHost()
    host.resize(800, 600)
    host.show()
    return host


def test_host_open_read_mode_at_anchor():
    host = _host()
    host.open(Path("notes.md"), MD, anchor="design-decisions", read=True)
    ed = host._editor
    assert ed._rendered_mode is True                 # opened in the read view
    block = ed._rendered.textCursor().block()
    assert block.blockFormat().headingLevel() == 2   # caret on the heading
    assert block.text() == "Design Decisions"


def test_host_open_write_mode_at_anchor():
    host = _host()
    host.open(Path("notes.md"), MD, anchor="final-notes")
    ed = host._editor
    assert ed._rendered_mode is False                # editable write view
    assert ed._editor.textCursor().block().text() == "## Final Notes"


def test_host_open_defaults_to_write_no_anchor():
    host = _host()
    host.open(Path("notes.md"), MD)
    assert host._editor._rendered_mode is False
