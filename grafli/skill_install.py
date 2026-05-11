"""Install / check / uninstall the bundled grafli skill into AI tools.

Pure logic lives here; the CLI orchestrator in ``app.py`` adds prompts,
TTY detection, and exit codes. Each target maps to a user-level skill
directory following the agentskills.io convention — one directory per
skill, named ``grafli``, containing a ``SKILL.md``.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


TARGETS: dict[str, Path] = {
    "claude":   Path("~/.claude/skills/grafli").expanduser(),
    "codex":    Path("~/.agents/skills/grafli").expanduser(),
    "opencode": Path("~/.config/opencode/skills/grafli").expanduser(),
}

ALL_TARGETS: tuple[str, ...] = tuple(TARGETS)

_VERSION_LINE_RE = re.compile(
    r"^<!-- grafli skill version: (\S+) -->\n?", flags=re.MULTILINE,
)


# ── status model ──────────────────────────────────────────────────

OK = "ok"
STALE = "stale"
MODIFIED = "modified"
UNKNOWN = "unknown"
MISSING = "missing"

DRIFT_STATES = frozenset({STALE, MODIFIED, UNKNOWN})


@dataclass
class TargetStatus:
    target: str
    path: Path             # the SKILL.md path (file)
    status: str            # one of: ok / stale / modified / unknown / missing
    installed_version: str | None
    packaged_version: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["path"] = str(self.path)
        return d


# ── content helpers ───────────────────────────────────────────────

def stamp_skill(content: str, version: str) -> str:
    """Return ``content`` with a version-comment line injected right after
    the YAML frontmatter (or at the top if no frontmatter is present).

    Idempotent: if a version line is already present, it is replaced.
    """
    stamp = f"<!-- grafli skill version: {version} -->"
    # Replace any existing line first so we never end up with two.
    if _VERSION_LINE_RE.search(content):
        return _VERSION_LINE_RE.sub(stamp + "\n", content, count=1)

    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end != -1:
            head = content[: end + 5]
            body = content[end + 5:].lstrip("\n")
            return f"{head}{stamp}\n\n{body}"
    return f"{stamp}\n\n{content.lstrip()}"


def strip_version_line(content: str) -> str:
    """Remove the version-comment line so two files can be compared
    on canonical content alone.
    """
    return _VERSION_LINE_RE.sub("", content, count=1)


def extract_version(content: str) -> str | None:
    m = _VERSION_LINE_RE.search(content)
    return m.group(1) if m else None


def _canonical(content: str) -> str:
    """Normalize for comparison — strip version line and collapse the
    leading blank line that follows it.
    """
    out = strip_version_line(content)
    # Drop up to one leading blank line that the version-line removal
    # may have left behind so a freshly-stamped file canonicalizes back
    # to the packaged source.
    if out.startswith("\n"):
        out = out[1:]
    return out


def target_path(target: str) -> Path:
    """Return the SKILL.md file path for a target."""
    return TARGETS[target] / "SKILL.md"


# ── status detection ──────────────────────────────────────────────

def compute_status(
    target: str, packaged_content: str, packaged_version: str,
) -> TargetStatus:
    path = target_path(target)
    if not path.exists():
        return TargetStatus(
            target=target, path=path, status=MISSING,
            installed_version=None, packaged_version=packaged_version,
        )

    installed = path.read_text(encoding="utf-8")
    installed_ver = extract_version(installed)
    if _canonical(installed) == _canonical(packaged_content):
        status = OK
    elif installed_ver is None:
        status = UNKNOWN
    elif installed_ver == packaged_version:
        status = MODIFIED
    else:
        status = STALE
    return TargetStatus(
        target=target, path=path, status=status,
        installed_version=installed_ver, packaged_version=packaged_version,
    )


def compute_all(
    targets: Iterable[str], packaged_content: str, packaged_version: str,
) -> list[TargetStatus]:
    return [compute_status(t, packaged_content, packaged_version) for t in targets]


# ── write / remove primitives ─────────────────────────────────────

def write_skill(
    target: str, packaged_content: str, packaged_version: str,
) -> Path:
    """Write the stamped SKILL.md for ``target``. Creates parent dirs.
    Returns the written path.
    """
    path = target_path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = stamp_skill(packaged_content, packaged_version)
    path.write_text(stamped, encoding="utf-8")
    return path


def remove_skill(target: str) -> bool:
    """Remove ``target``'s SKILL.md and the enclosing ``grafli/`` dir.
    Returns True if anything was removed.
    """
    dir_path = TARGETS[target]
    if not dir_path.exists():
        return False
    if dir_path.is_symlink():
        dir_path.unlink()
        return True
    shutil.rmtree(dir_path)
    return True


def parent_dir_exists(target: str) -> bool:
    """True if the parent skills directory exists (e.g. ``~/.claude/skills``).
    Used to detect "tool isn't installed" so we can prompt before creating.
    """
    return TARGETS[target].parent.exists()
