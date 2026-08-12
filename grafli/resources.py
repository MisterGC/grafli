"""Resource directory ("vault") helpers and migration logic for .grafli files.

Each .grafli file can have an associated <stem>-res/ directory — its vault —
that stores markdown documents, sub-graflis, and pasted images. Content
attachments (``&doc:`` / ``&graph:``) live only here, so a board plus its
vault is the complete, copyable unit; ``&link:`` is the explicit pointer to
the outside world. This module provides the path conventions, the typed-
attachment classification/normalization of legacy ``&url`` values, loading/
saving of doc-bodied note texts, and migrations from older layouts.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from grafli.format import Board, Note, doc_name
from grafli.md_note import is_md_note, md_body
from grafli.sync import atomic_write, merge3_text


# Per-note merge base for a doc body: the disk content we last synced this
# note against (common ancestor for a 3-way merge). Stored as a dynamic
# attribute, not a dataclass field, so it never affects Note equality (the
# board merge compares fields) yet rides along through deepcopy.
_DOC_BASE_ATTR = "_doc_base"


def res_dir(grafli_path: Path) -> Path:
    """Return the resource directory path for a .grafli file."""
    return grafli_path.parent / f"{grafli_path.stem}-res"


def ensure_res_dir(grafli_path: Path) -> Path:
    """Create and return the resource directory for a .grafli file."""
    d = res_dir(grafli_path)
    d.mkdir(exist_ok=True)
    return d


def resolve_image_path(base_dir: str, image_path: str) -> str:
    """Absolute, normalized filesystem path of an image reference.

    A relative reference resolves against ``base_dir`` (the .grafli file's
    directory); an absolute one passes through. Without a base directory the
    reference is only normalized — there is nothing to resolve it against.
    """
    if not base_dir or os.path.isabs(image_path):
        return os.path.normpath(image_path)
    return os.path.normpath(os.path.join(base_dir, image_path))


def image_ref(grafli_path: Path, source: Path) -> str:
    """The reference an ``@ image`` line stores for a dropped image file.

    A file that already lives inside the board's directory tree is referenced
    in place: the user keeps their SVGs where they edit them, and an external
    edit shows up in the board. A file from outside is copied into the vault
    instead, so the board plus its vault stays the complete, copyable unit.
    """
    src = Path(source).resolve()
    root = grafli_path.parent.resolve()
    try:
        return src.relative_to(root).as_posix()
    except ValueError:
        pass
    dest_dir = ensure_res_dir(grafli_path)
    return f"{dest_dir.name}/{_copy_into_vault(dest_dir, src).name}"


def _copy_into_vault(dest_dir: Path, src: Path) -> Path:
    """Copy *src* into *dest_dir*, resolving name collisions.

    An existing file with identical bytes is the same picture, so it is
    reused rather than duplicated; a different one gets ``-1``, ``-2``, ...
    appended to the stem.
    """
    data = src.read_bytes()
    dest = dest_dir / src.name
    n = 0
    while dest.exists():
        try:
            if dest.read_bytes() == data:
                return dest
        except OSError:
            pass
        n += 1
        dest = dest_dir / f"{src.stem}-{n}{src.suffix}"
    dest.write_bytes(data)
    return dest


def doc_path(grafli_path: Path, name: str) -> Path:
    """The vault path of a markdown document attachment."""
    return res_dir(grafli_path) / f"{name}.md"


def graph_path(grafli_path: Path, name: str) -> Path:
    """The vault path of a sub-board attachment."""
    return res_dir(grafli_path) / f"{name}.grafli"


def _attachables(board: Board):
    yield from board.boxes
    yield from board.notes
    yield from board.images
    yield from board.arrows


def classify_attachments(grafli_path: Path, board: Board) -> bool:
    """Assign kinds to legacy untyped ``&url`` attachments. In-memory only —
    the file normalizes on the next save. Returns True when anything changed.

    Vault ``.md`` → doc and vault ``.grafli`` → graph for boxes/images/arrows;
    everything else → link. Note attachments always classify as link: a legacy
    note's ``&`` was a clickable reference next to its inline text, and
    promoting it to doc would silently replace that text with the file body.
    Notes become doc-bodied only via ``externalize_md_notes`` or explicitly.
    """
    rd = res_dir(grafli_path).name
    changed = False
    for el in _attachables(board):
        if el.attach_kind or not el.url:
            continue
        raw = el.url.replace("\\", "/")
        if not isinstance(el, Note) and raw.startswith(rd + "/"):
            name = raw[len(rd) + 1:]
            if name.endswith(".md") and "/" not in name[:-3]:
                el.attach_kind, el.url = "doc", name[:-3]
                changed = True
                continue
            if name.endswith(".grafli") and "/" not in name[:-7]:
                el.attach_kind, el.url = "graph", name[:-7]
                changed = True
                continue
        el.attach_kind = "link"
        changed = True
    return changed


def load_docs(grafli_path: Path, board: Board) -> list[str]:
    """Read vault doc bodies into doc-bodied notes' ``text``.

    Returns the names of missing docs. A missing doc loads as empty text —
    typing into the note and saving recreates the file (self-healing), and
    ``save_docs``'s lazy-create rule means an untouched empty note never
    spawns one.

    On a *reload* (the note already carries a merge base from an earlier
    load) an external change to the ``.md`` is 3-way merged with any
    unsaved in-memory edit, so a concurrent zen-editor edit and an AI ``.md``
    edit don't clobber each other — the symmetric twin of ``save_docs``.
    """
    missing: list[str] = []
    for note in board.notes:
        if note.attach_kind != "doc":
            continue
        name = doc_name(note)
        p = doc_path(grafli_path, name)
        try:
            disk = p.read_text(encoding="utf-8")
        except OSError:
            note.text = ""
            setattr(note, _DOC_BASE_ATTR, None)
            missing.append(name)
            continue
        base = getattr(note, _DOC_BASE_ATTR, None)
        local = note.text
        if base is not None and local != base and disk != base and local != disk:
            note.text, _ = merge3_text(base, local, disk)   # both moved → merge
        elif base is None or disk != base:
            note.text = disk                                # external change, no local edit
        # else disk == base: no external change — keep the unsaved local edit.
        setattr(note, _DOC_BASE_ATTR, disk)
    return missing


def save_docs(grafli_path: Path, board: Board) -> list[str]:
    """Write doc-bodied note texts to their vault files. Returns written names.

    Shared docs (several notes naming the same doc — transclusion) are
    reconciled first: an in-memory text that differs from the file is the
    edited one and wins; the others are synced to it, so a stale sibling
    can never flip the file back.

    If the file also changed on disk since we last synced this note (an
    external/AI ``.md`` edit), the in-memory body and the disk body are
    3-way merged against the note's stored base instead of one clobbering
    the other. Writes are atomic (temp + replace); files are created
    lazily — an empty body never creates a file, and an existing file is
    only touched when the body actually changed.
    """
    groups: dict[str, list] = {}
    for note in board.notes:
        if note.attach_kind == "doc":
            groups.setdefault(doc_name(note), []).append(note)
    written: list[str] = []
    for name, notes in groups.items():
        p = doc_path(grafli_path, name)
        try:
            on_disk = p.read_text(encoding="utf-8")
        except OSError:
            on_disk = None
        edited = [n.text for n in notes if n.text != on_disk]
        body = edited[0] if edited else on_disk
        if body is None:
            body = notes[0].text
        # 3-way merge if the disk moved out from under our base while we
        # were holding an edit — otherwise we'd overwrite the external edit.
        base = getattr(notes[0], _DOC_BASE_ATTR, None)
        if (on_disk is not None and base is not None
                and base != on_disk and body != on_disk):
            body, _ = merge3_text(base, body, on_disk)
        for n in notes:
            n.text = body
            setattr(n, _DOC_BASE_ATTR, body if body is not None else on_disk)
        if body == on_disk:
            continue
        if on_disk is None and not body.strip():
            continue   # lazy: an empty new note creates no file
        ensure_res_dir(grafli_path)
        atomic_write(p, body)
        written.append(name)
    return written


def externalize_md_notes(board: Board) -> int:
    """Convert inline ``md:`` notes to doc-bodied ones (in memory).

    The body (prefix stripped) stays in ``note.text``; the caller's next
    ``save_docs`` writes the vault file. Notes that already carry an
    attachment keep their inline text — the one-slot rule. Returns the
    number of notes converted.
    """
    n = 0
    for note in board.notes:
        if note.attach_kind or note.url or not is_md_note(note.text):
            continue
        note.text = md_body(note.text)
        note.attach_kind = "doc"
        note.block_text = False
        n += 1
    return n


def vault_docs(grafli_path: Path, board: Board) -> dict[str, list[str]]:
    """Inventory of the vault's markdown docs.

    Returns {"referenced": [...], "missing": [...], "unreferenced": [...]} —
    referenced docs that exist, referenced docs whose file is gone, and vault
    ``.md`` files no element points to (a legitimate state; cleaning them is
    an explicit command, never automatic).
    """
    referenced: set[str] = set()
    for el in _attachables(board):
        if el.attach_kind == "doc":
            referenced.add(doc_name(el))
    rd = res_dir(grafli_path)
    on_disk = {p.stem for p in rd.glob("*.md")} if rd.is_dir() else set()
    return {
        "referenced": sorted(referenced & on_disk),
        "missing": sorted(referenced - on_disk),
        "unreferenced": sorted(on_disk - referenced),
    }


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
