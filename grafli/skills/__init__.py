"""The grafli skill as it ships in the package: ``grafli/SKILL.md``, its
``references/`` files and the example boards they name. ``grafli skill``
prints and installs it; the ``grafli agent`` bridge hands it to a connected
session. No Qt.

An example the skill names as ``examples/<name>.grafli`` ships with it, with
its ``<name>-res/`` vault. The boards live once, in the repository's
``examples/``; the wheel bundles the named ones into the skill directory
(``pyproject.toml``, ``force-include``), and an editable install reads them
from the repository."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

# Concat / inline order for the reference files; unknown names sort after.
REFERENCE_ORDER = ("format.md", "design.md", "presenting.md", "thinking.md")

# How the skill's text names an example board.
EXAMPLE_RE = re.compile(r"\bexamples/([a-z0-9][a-z0-9-]*)\.grafli\b")


def skill_dir() -> Path:
    """The bundled skill directory."""
    return Path(str(files("grafli.skills.grafli")))


def skill_path() -> Path:
    """The bundled SKILL.md."""
    return skill_dir() / "SKILL.md"


def skill_references() -> dict[str, str]:
    """The bundled reference files as ``{name: content}``, in the
    canonical inline order."""
    ref_dir = skill_dir() / "references"
    if not ref_dir.is_dir():
        return {}

    def order(p: Path) -> tuple[int, str]:
        try:
            return (REFERENCE_ORDER.index(p.name), p.name)
        except ValueError:
            return (len(REFERENCE_ORDER), p.name)
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(ref_dir.glob("*.md"), key=order)
    }


def skill_concat() -> str:
    """The single-file build: SKILL.md with every reference inlined."""
    parts = [skill_path().read_text(encoding="utf-8")]
    for name, content in skill_references().items():
        parts.append(
            f"\n\n---\n\n<!-- inlined from references/{name} -->\n\n{content}"
        )
    return "".join(parts)


def named_examples() -> list[str]:
    """The stems of the example boards the skill's text names, sorted."""
    texts = [skill_path().read_text(encoding="utf-8"),
             *skill_references().values()]
    return sorted({m for t in texts for m in EXAMPLE_RE.findall(t)})


def examples_dir() -> Path:
    """Where the named example boards are: bundled into the skill directory
    in a built wheel, else the repository's ``examples/`` (an editable
    install)."""
    bundled = skill_dir() / "examples"
    if bundled.is_dir():
        return bundled
    return skill_dir().parents[2] / "examples"


def skill_examples() -> dict[str, bytes]:
    """The example boards the skill names, as ``{relative path: bytes}``:
    each ``<name>.grafli`` and every file of its ``<name>-res/`` vault. A
    named board that is missing is left out (a test keeps the set whole)."""
    root = examples_dir()
    out: dict[str, bytes] = {}
    for stem in named_examples():
        board = root / f"{stem}.grafli"
        if not board.is_file():
            continue
        out[board.name] = board.read_bytes()
        vault = root / f"{stem}-res"
        if vault.is_dir():
            for p in sorted(vault.rglob("*")):
                rel = p.relative_to(root)
                if p.is_file() and not any(part.startswith((".", "__"))
                                           for part in rel.parts):
                    out[rel.as_posix()] = p.read_bytes()
    return out
