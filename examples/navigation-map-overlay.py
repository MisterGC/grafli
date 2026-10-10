"""Write the "Tests" overlay of navigation-map.grafli.

For each part on the map's top level, count the test files under tests/
that name one of the part's symbols, and write the result as an overlay
file beside the board: navigation-map-res/tests.overlay.json. Run it from
anywhere; rerun it after the code or the tests change — the file is
derived data, never edited by hand.

    python examples/navigation-map-overlay.py
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUT = HERE / "navigation-map-res" / "tests.overlay.json"

# Each top-level box id and the symbols that part is made of.
PARTS = {
    "keys": ["_go_down", "_go_up", "_peek_doc", "_tours_through_selection"],
    "parse": ["split_attach", "split_board_fragment", "split_step_ref"],
    "open": ["_open_attachment", "_open_url_string", "_enter_board"],
    "stack": ["push_frame", "pop_frame", "BoardFrame"],
    "tours": ["play_flow", "resume_flow", "tour_position"],
    "peek": ["doc_first_sentence", "_peek_doc"],
    "export": ["export_html", "reachable_boards"],
}


def first_hits(symbols: list[str]) -> dict[str, int]:
    """Each test file naming one of *symbols*, with the line it first does."""
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, symbols)) + r")\b")
    hits = {}
    for path in sorted((REPO / "tests").glob("test_*.py")):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits[path.relative_to(REPO).as_posix()] = no
                break
    return hits


def category(count: int) -> str:
    if count >= 3:
        return "tested"
    return "thin" if count else "none"


def main() -> None:
    revision = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    entries = {}
    for part, symbols in PARTS.items():
        hits = first_hits(symbols)
        entries[part] = {
            "category": category(len(hits)),
            "note": f"{len(hits)} test files name {', '.join(symbols)}",
            "refs": [f"@{path}:{no}" for path, no in list(hits.items())[:3]],
        }
    overlay = {
        "title": "Tests",
        "producer": "examples/navigation-map-overlay.py (grep over tests/)",
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": {"repo": "..", "revision": revision},
        "kind": "category",
        "categories": [
            {"id": "tested", "label": "3+ test files", "color": "%forest"},
            {"id": "thin", "label": "1–2 test files", "color": "%clay"},
            {"id": "none", "label": "No test names it", "color": "%rose"},
        ],
        "entries": entries,
    }
    OUT.write_text(json.dumps(overlay, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
