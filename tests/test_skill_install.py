"""Tests for grafli.skill_install — install / check / uninstall logic."""

from pathlib import Path

import pytest

from grafli import skill_install
from grafli.skill_install import (
    MISSING,
    MODIFIED,
    OK,
    STALE,
    UNKNOWN,
    compute_status,
    extract_version,
    remove_skill,
    stamp_skill,
    strip_version_line,
    write_skill,
)


SAMPLE = """\
---
name: grafli
description: short
---

# Body

Hello.
"""


# ── stamping helpers ──────────────────────────────────────────────


def test_stamp_inserts_after_frontmatter():
    stamped = stamp_skill(SAMPLE, "1.2.3")
    assert "<!-- grafli skill version: 1.2.3 -->" in stamped
    # Must follow the frontmatter and precede the body.
    fm_end = stamped.index("---", 4)
    body_start = stamped.index("# Body")
    stamp_pos = stamped.index("<!-- grafli skill version:")
    assert fm_end < stamp_pos < body_start


def test_stamp_replaces_existing_version_line():
    once = stamp_skill(SAMPLE, "1.0.0")
    twice = stamp_skill(once, "2.0.0")
    assert "1.0.0" not in twice
    assert "<!-- grafli skill version: 2.0.0 -->" in twice
    # And exactly one line — never two.
    assert twice.count("grafli skill version:") == 1


def test_stamp_handles_no_frontmatter():
    bare = "# Just a heading\n\nbody"
    stamped = stamp_skill(bare, "0.1.0")
    assert stamped.startswith("<!-- grafli skill version: 0.1.0 -->")
    assert "# Just a heading" in stamped


def test_strip_returns_canonical():
    stamped = stamp_skill(SAMPLE, "1.2.3")
    assert strip_version_line(stamped) != stamped
    # Stripping then re-stamping must round-trip to the same content.
    re_stamped = stamp_skill(strip_version_line(stamped), "1.2.3")
    assert re_stamped == stamped


def test_extract_version_roundtrip():
    stamped = stamp_skill(SAMPLE, "0.4.0")
    assert extract_version(stamped) == "0.4.0"
    assert extract_version(SAMPLE) is None


# ── target redirection fixture ────────────────────────────────────


@pytest.fixture
def isolated_targets(tmp_path, monkeypatch):
    """Redirect skill_install.TARGETS at the per-test tmp_path so we
    never touch the developer's real ~/.claude, ~/.agents, etc."""
    targets = {
        "claude": tmp_path / "claude/skills/grafli",
        "codex": tmp_path / "agents/skills/grafli",
        "opencode": tmp_path / "opencode/skills/grafli",
    }
    monkeypatch.setattr(skill_install, "TARGETS", targets)
    return targets


# ── compute_status across all 5 states ────────────────────────────


def test_status_missing(isolated_targets):
    st = compute_status("claude", SAMPLE, "0.4.0")
    assert st.status == MISSING
    assert st.installed_version is None
    assert st.packaged_version == "0.4.0"


def test_status_ok_matches_packaged(isolated_targets):
    write_skill("claude", SAMPLE, "0.4.0")
    st = compute_status("claude", SAMPLE, "0.4.0")
    assert st.status == OK
    assert st.installed_version == "0.4.0"


def test_status_stale_when_version_older(isolated_targets):
    write_skill("claude", SAMPLE, "0.3.0")
    new_packaged = SAMPLE + "\n## New section\n"
    st = compute_status("claude", new_packaged, "0.4.0")
    assert st.status == STALE
    assert st.installed_version == "0.3.0"


def test_status_modified_when_version_matches_but_content_differs(isolated_targets):
    write_skill("claude", SAMPLE, "0.4.0")
    # Manually edit the installed file (user added a note).
    path = isolated_targets["claude"] / "SKILL.md"
    text = path.read_text() + "\n\n<!-- user added -->\n"
    path.write_text(text)
    st = compute_status("claude", SAMPLE, "0.4.0")
    assert st.status == MODIFIED
    assert st.installed_version == "0.4.0"


def test_status_unknown_when_no_version_marker(isolated_targets):
    # File exists but was hand-installed without the version comment.
    path = isolated_targets["claude"] / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Old hand-installed body\n\nstuff that differs.")
    st = compute_status("claude", SAMPLE, "0.4.0")
    assert st.status == UNKNOWN
    assert st.installed_version is None


# ── write / remove primitives ─────────────────────────────────────


def test_write_creates_parents_and_stamps(isolated_targets):
    path = write_skill("codex", SAMPLE, "0.4.0")
    assert path.exists()
    assert "<!-- grafli skill version: 0.4.0 -->" in path.read_text()
    assert path == isolated_targets["codex"] / "SKILL.md"


def test_remove_deletes_skill_directory(isolated_targets):
    write_skill("claude", SAMPLE, "0.4.0")
    assert isolated_targets["claude"].exists()
    assert remove_skill("claude") is True
    assert not isolated_targets["claude"].exists()


def test_remove_when_already_missing_returns_false(isolated_targets):
    assert remove_skill("claude") is False


# ── multi-file skill (SKILL.md + references/) ─────────────────────


REFS = {
    "format.md": "# Format reference\n\nTables.\n",
    "design.md": "# Design reference\n\nPrinciples.\n",
}


def test_write_installs_references(isolated_targets):
    path = write_skill("claude", SAMPLE, "0.5.0", REFS)
    ref_dir = path.parent / "references"
    assert sorted(p.name for p in ref_dir.glob("*.md")) == sorted(REFS)
    assert (ref_dir / "format.md").read_text() == REFS["format.md"]


def test_write_replaces_stale_references(isolated_targets):
    write_skill("claude", SAMPLE, "0.4.0", {"old.md": "gone soon\n"})
    path = write_skill("claude", SAMPLE, "0.5.0", REFS)
    names = {p.name for p in (path.parent / "references").glob("*.md")}
    assert names == set(REFS)


def test_status_ok_with_matching_references(isolated_targets):
    write_skill("claude", SAMPLE, "0.5.0", REFS)
    st = compute_status("claude", SAMPLE, "0.5.0", REFS)
    assert st.status == OK


def test_status_modified_when_reference_edited(isolated_targets):
    write_skill("claude", SAMPLE, "0.5.0", REFS)
    ref = isolated_targets["claude"] / "references/format.md"
    ref.write_text(ref.read_text() + "\nlocal tweak\n")
    st = compute_status("claude", SAMPLE, "0.5.0", REFS)
    assert st.status == MODIFIED


def test_status_stale_for_old_single_file_install(isolated_targets):
    # A pre-multi-file install (no references dir) with an older version.
    write_skill("claude", SAMPLE, "0.4.0")
    st = compute_status("claude", SAMPLE, "0.5.0", REFS)
    assert st.status == STALE


def test_status_ok_without_references_stays_compatible(isolated_targets):
    # Single-file callers (no references) keep the old behaviour.
    write_skill("claude", SAMPLE, "0.4.0")
    st = compute_status("claude", SAMPLE, "0.4.0")
    assert st.status == OK


# ── bundled skill integrity ───────────────────────────────────────


def _bundled_dir() -> Path:
    from importlib.resources import files
    return Path(str(files("grafli.skills.grafli")))


def test_bundled_core_references_exist():
    """Every references/<name>.md the core mentions must be bundled."""
    import re
    root = _bundled_dir()
    core = (root / "SKILL.md").read_text(encoding="utf-8")
    names = set(re.findall(r"references/([a-z-]+\.md)", core))
    assert names, "the lean core must point at its reference files"
    for name in names:
        assert (root / "references" / name).is_file(), name


def test_bundled_skill_install_roundtrip(isolated_targets):
    """Installing the real bundled skill lands every referenced path."""
    import re
    root = _bundled_dir()
    core = (root / "SKILL.md").read_text(encoding="utf-8")
    refs = {
        p.name: p.read_text(encoding="utf-8")
        for p in (root / "references").glob("*.md")
    }
    path = write_skill("claude", core, "9.9.9", refs)
    for name in set(re.findall(r"references/([a-z-]+\.md)", core)):
        assert (path.parent / "references" / name).is_file(), name
    assert compute_status("claude", core, "9.9.9", refs).status == OK


def test_bundled_concat_inlines_all_references():
    from grafli.app import _skill_concat, _skill_references
    concat = _skill_concat()
    refs = _skill_references()
    assert refs, "bundled skill must carry reference files"
    for name in refs:
        assert f"<!-- inlined from references/{name} -->" in concat
