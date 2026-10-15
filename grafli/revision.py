"""The git revision a repo sits at, and whether a recorded one still matches.

Overlay files and boards both record the revision their data was read at;
this compares it with the repo's ``HEAD``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


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
