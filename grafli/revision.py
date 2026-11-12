"""The git revision a repo sits at, and whether a recorded one still matches.

Overlay files and boards both record the revision their data was read at;
this compares it with the repo's ``HEAD``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from grafli.format import Board, board_source, ref_root

# How a stale notice starts when git cannot read the repo's HEAD at all.
UNREADABLE = "refs stale?"


def head_revision(repo: Path) -> str | None:
    """The full hash of *repo*'s ``HEAD``, or None when git can't read it."""
    try:
        out = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def revisions_match(recorded: str, head: str) -> bool:
    """True when one is a prefix of the other, so a short hash matches the
    full ``HEAD``."""
    rev, head = recorded.lower(), head.lower()
    return head.startswith(rev) or rev.startswith(head)


def refs_stale_line(board: Board, base_dir: Path) -> str:
    """The notice for a board whose ``# source: <repo> @ <rev>`` comment
    names a revision its repo's ``HEAD`` has moved on from, or "" while they
    match or the comment names no revision. A relative repo is taken from
    *base_dir*, the board's directory."""
    source = board_source(board)
    if source is None or not source[1]:
        return ""
    repo, rev = source
    head = head_revision(ref_root(board, base_dir))
    if head is None:
        return f"{UNREADABLE} cannot read the HEAD of {repo}"
    if revisions_match(rev, head):
        return ""
    return (f"refs read at {rev[:7]}, {repo} is at {head[:7]} — "
            "@path:line refs may open moved lines")
