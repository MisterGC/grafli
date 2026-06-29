"""Headless persistence + merge core — no PySide, no GUI, no I/O policy.

This module is the part of the concurrency story that a future hosted
server would reuse unchanged: it does not know *where* ``base`` / ``local``
/ ``remote`` come from (a file on disk today, a socket message tomorrow),
only how to combine them safely. The desktop app is a thin adapter that
supplies file contents and applies the result.

Three jobs:

* ``atomic_write`` — write a file so a reader (the watcher, another
  process) never observes a half-written file: write a sibling temp file
  then ``os.replace`` (atomic on POSIX and Windows).
* ``merge3_text`` — a 3-way line merge for markdown doc bodies. Clean
  when the two sides touched different regions; conflict-marked (never
  silently dropped) when they overlap.
* ``merge_boards`` — a 3-way, id-keyed, field-level merge of two parsed
  ``Board``s against their common ancestor. Always returns a valid board
  (no conflict markers in a ``.grafli``); a true field conflict is
  resolved deterministically and reported so the caller can surface it.

The merge inputs follow the usual three-way naming:

* ``base``   — the last content both sides agreed on (common ancestor).
* ``local``  — our in-memory state (e.g. the human's unsaved edits).
* ``remote`` — what is now on disk (e.g. the AI's external write).
"""

from __future__ import annotations

import copy
import dataclasses
import difflib
import os
from dataclasses import dataclass
from pathlib import Path

from grafli.format import Board


# ── Atomic write ────────────────────────────────────────────────

def atomic_write(path: str | Path, text: str, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically (temp sibling + ``os.replace``).

    A watcher polling mtime/size, or a second writer, never sees a
    partial file: either the old contents or the complete new contents.
    The temp file is created in the same directory so the replace stays
    on one filesystem (a cross-device ``os.replace`` would fail).
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(text, encoding=encoding)
        os.replace(tmp, path)
    finally:
        # On a successful replace the temp is gone; this only fires if the
        # write or replace raised, so we never leave a stray .tmp behind.
        try:
            tmp.unlink()
        except OSError:
            pass


# ── 3-way text merge (doc bodies) ───────────────────────────────

_CONFLICT_BEGIN = "<<<<<<< local"
_CONFLICT_SEP = "======="
_CONFLICT_END = ">>>>>>> remote"


def _match_map(base: list[str], other: list[str]) -> dict[int, int]:
    """Map base-line index → other-line index for lines that match,
    using difflib's matching blocks (monotonic in both sequences)."""
    out: dict[int, int] = {}
    sm = difflib.SequenceMatcher(None, base, other, autojunk=False)
    for bi, oi, n in sm.get_matching_blocks():
        for k in range(n):
            out[bi + k] = oi + k
    return out


def merge3_lines(
    base: list[str], local: list[str], remote: list[str]
) -> tuple[list[str], bool]:
    """3-way merge of line lists. Returns ``(merged_lines, had_conflict)``.

    Lines common to all three act as sync anchors; the spans between
    anchors are resolved independently: if one side left a span untouched
    the other side's version wins cleanly, otherwise the span is emitted
    between conflict markers. Two edits with no common line between them
    conflict conservatively rather than risk a wrong silent merge — safe,
    never lossy.
    """
    if local == base:
        return list(remote), False
    if remote == base:
        return list(local), False
    if local == remote:
        return list(local), False

    ml = _match_map(base, local)
    mr = _match_map(base, remote)
    # Anchors: base lines present (unchanged) in BOTH sides, kept monotone
    # in local and remote coordinates so spans never cross.
    anchors: list[int] = []
    last_l = last_r = -1
    for bi in range(len(base)):
        if bi in ml and bi in mr and ml[bi] > last_l and mr[bi] > last_r:
            anchors.append(bi)
            last_l, last_r = ml[bi], mr[bi]

    out: list[str] = []
    conflict = False
    prev_b = prev_l = prev_r = -1
    for bi in anchors + [len(base)]:
        li = ml[bi] if bi < len(base) else len(local)
        ri = mr[bi] if bi < len(base) else len(remote)
        bc = base[prev_b + 1:bi]
        lc = local[prev_l + 1:li]
        rc = remote[prev_r + 1:ri]
        if lc == bc:
            out.extend(rc)
        elif rc == bc:
            out.extend(lc)
        elif lc == rc:
            out.extend(lc)
        else:
            conflict = True
            out.append(_CONFLICT_BEGIN)
            out.extend(lc)
            out.append(_CONFLICT_SEP)
            out.extend(rc)
            out.append(_CONFLICT_END)
        if bi < len(base):
            out.append(base[bi])
        prev_b, prev_l, prev_r = bi, li, ri
    return out, conflict


def merge3_text(base: str, local: str, remote: str) -> tuple[str, bool]:
    """3-way merge of text bodies. Returns ``(merged_text, had_conflict)``.

    Splits on ``\\n`` (so a trailing newline round-trips) and re-joins, so
    the merge is line-granular like git's.
    """
    merged, conflict = merge3_lines(
        base.split("\n"), local.split("\n"), remote.split("\n")
    )
    return "\n".join(merged), conflict


# ── 3-way board merge ───────────────────────────────────────────

@dataclass
class Conflict:
    """A field- or element-level merge conflict, for caller-side reporting.

    ``kind`` is the element kind ('box', 'note', 'arrow', 'image',
    'bookmark', 'flow'); ``key`` identifies the element; ``detail`` names
    the field that diverged or the structural clash ('modify/delete').
    """
    kind: str
    key: str
    detail: str


# (list attribute on Board, element kind label, key function)
_ELEMENT_LISTS = [
    ("boxes", "box", lambda e: e.id),
    ("notes", "note", lambda e: e.id),
    ("arrows", "arrow", lambda e: (e.from_id, e.to_id)),
    ("images", "image", lambda e: e.id),
    ("bookmarks", "bookmark", lambda e: e.id),
    ("flows", "flow", lambda e: e.id),
]


def _key_str(key) -> str:
    return key if isinstance(key, str) else "->".join(key)


def _merge_fields(base_el, local_el, remote_el, kind, key, prefer, conflicts):
    """3-way field merge onto a copy of *remote_el* (mutated in place).

    Per field: a side that left the field at its base value yields to the
    other; equal changes coalesce; a true divergence is resolved by
    *prefer* ('remote' by default — converge on the shared disk state) and
    recorded as a Conflict.
    """
    for f in dataclasses.fields(remote_el):
        name = f.name
        if name.startswith("_"):
            continue
        b = getattr(base_el, name)
        l = getattr(local_el, name)
        r = getattr(remote_el, name)
        if l == b:
            val = r
        elif r == b:
            val = l
        elif l == r:
            val = l
        else:
            val = r if prefer == "remote" else l
            conflicts.append(Conflict(kind, _key_str(key), name))
        setattr(remote_el, name, val)


def _drop_from_lines(board: Board, element) -> None:
    board._lines = [(k, o) for (k, o) in board._lines if o is not element]


def merge_boards(
    base: Board | None,
    local: Board,
    remote: Board,
    prefer: str = "remote",
) -> tuple[Board, list[Conflict]]:
    """3-way merge of two boards against common ancestor *base*.

    Returns ``(merged_board, conflicts)``. The result starts from *remote*
    (the latest disk state, so its line order — the smallest diff against
    what is about to be reconciled — is preserved) and is patched:

    * elements in both sides     → field-merged (see ``_merge_fields``);
    * added only in *local*       → appended;
    * deleted in *remote*, untouched in *local* → stay deleted;
    * deleted on one side but modified on the other → modify wins, recorded
      as a 'modify/delete' conflict (never silently lost).

    When *base* is None (no known ancestor) every difference is treated as
    a concurrent add/change and resolved by *prefer* — a safe degenerate
    case, not the normal path.
    """
    merged = copy.deepcopy(remote)
    conflicts: list[Conflict] = []
    base = base if base is not None else Board()

    for attr, kind, keyfn in _ELEMENT_LISTS:
        base_map = {keyfn(e): e for e in getattr(base, attr)}
        local_map = {keyfn(e): e for e in getattr(local, attr)}
        merged_list = getattr(merged, attr)
        merged_map = {keyfn(e): e for e in merged_list}

        # Elements present on the remote side (our starting point).
        for key, rem_el in list(merged_map.items()):
            in_base = key in base_map
            in_local = key in local_map
            if in_local and in_base:
                _merge_fields(base_map[key], local_map[key], rem_el,
                              kind, key, prefer, conflicts)
            elif in_local and not in_base:
                # Added on both sides with the same key — keep remote's,
                # flag only if the content actually differs.
                if local_map[key] != rem_el:
                    conflicts.append(Conflict(kind, _key_str(key), "add/add"))
            elif not in_local and in_base:
                # Deleted on the local side. Honour the delete only if the
                # remote side left it at its base value; otherwise the
                # remote modification wins (modify/delete).
                if rem_el == base_map[key]:
                    getattr(merged, attr).remove(rem_el)
                    _drop_from_lines(merged, rem_el)
                else:
                    conflicts.append(Conflict(kind, _key_str(key),
                                              "modify/delete"))
            # not in_local and not in_base → added only on remote: keep.

        # Elements only on the local side (not in remote).
        for key, loc_el in local_map.items():
            if key in merged_map:
                continue
            if key in base_map:
                # Deleted on the remote side. Keep it only if the local
                # side modified it (modify/delete); else honour the delete.
                if loc_el != base_map[key]:
                    new_el = copy.deepcopy(loc_el)
                    getattr(merged, attr).append(new_el)
                    merged._lines.append((kind, new_el))
                    conflicts.append(Conflict(kind, _key_str(key),
                                              "modify/delete"))
            else:
                # Added only on the local side → carry it in.
                new_el = copy.deepcopy(loc_el)
                getattr(merged, attr).append(new_el)
                merged._lines.append((kind, new_el))

    return merged, conflicts
