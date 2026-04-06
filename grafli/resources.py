"""Resource directory helpers and migration logic for .grafli files.

Each .grafli file can have an associated <stem>-res/ directory that stores
markdown annotations, sub-graflis, and pasted images.  This module provides
helpers for creating that directory and migrating from the legacy
<stem>-images/ layout and inline # annotations.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from grafli.format import Board


def res_dir(grafli_path: Path) -> Path:
    """Return the resource directory path for a .grafli file."""
    return grafli_path.parent / f"{grafli_path.stem}-res"


def ensure_res_dir(grafli_path: Path) -> Path:
    """Create and return the resource directory for a .grafli file."""
    d = res_dir(grafli_path)
    d.mkdir(exist_ok=True)
    return d


def migrate_images_dir(grafli_path: Path, board: Board) -> bool:
    """Rename <stem>-images/ to <stem>-res/ and rewrite image paths.

    Returns True if migration happened.
    """
    old_dir = grafli_path.parent / f"{grafli_path.stem}-images"
    if not old_dir.is_dir():
        return False

    new_dir = res_dir(grafli_path)
    if new_dir.exists():
        # Target already exists — move contents individually
        for item in old_dir.iterdir():
            dest = new_dir / item.name
            if not dest.exists():
                shutil.move(str(item), str(dest))
        # Remove old dir if now empty
        try:
            old_dir.rmdir()
        except OSError:
            pass
    else:
        old_dir.rename(new_dir)

    old_prefix = f"{grafli_path.stem}-images/"
    new_prefix = f"{new_dir.name}/"
    for image in board.images:
        if image.image_path.startswith(old_prefix):
            image.image_path = new_prefix + image.image_path[len(old_prefix):]

    return True


def migrate_annotations(grafli_path: Path, board: Board) -> bool:
    """Convert inline annotations to .md files in <stem>-res/.

    For each element with a non-empty annotation and no url, creates a
    markdown file and sets the element's url to its relative path.

    Returns True if any migration happened.
    """
    changed = False

    elements: list[tuple[str, object]] = []
    for box in board.boxes:
        if box.annotation and not box.url:
            elements.append((box.id, box))
    for note in board.notes:
        if note.annotation and not note.url:
            elements.append((note.id, note))
    for image in board.images:
        if image.annotation and not image.url:
            elements.append((image.id, image))
    for arrow in board.arrows:
        if arrow.annotation and not arrow.url:
            aid = f"{arrow.from_id}--{arrow.to_id}"
            elements.append((aid, arrow))

    if not elements:
        return False

    rd = ensure_res_dir(grafli_path)
    for element_id, element in elements:
        md_path = rd / f"{element_id}.md"
        if not md_path.exists():
            md_path.write_text(element.annotation, encoding="utf-8")
        rel = f"{rd.name}/{md_path.name}"
        element.url = rel
        element.annotation = ""
        changed = True

    return changed


def migrate_all(grafli_path: Path, board: Board) -> bool:
    """Run all migrations. Returns True if anything changed."""
    changed = migrate_images_dir(grafli_path, board)
    changed = migrate_annotations(grafli_path, board) or changed
    return changed
