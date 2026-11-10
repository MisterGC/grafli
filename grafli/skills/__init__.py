"""The grafli skill as it ships in the package: ``grafli/SKILL.md`` plus its
``references/`` files. ``grafli skill`` prints and installs it; the
``grafli agent`` bridge hands it to a connected session. No Qt."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

# Concat / inline order for the reference files; unknown names sort after.
REFERENCE_ORDER = ("format.md", "design.md", "presenting.md", "thinking.md")


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
