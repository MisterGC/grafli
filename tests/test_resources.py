"""Tests for grafli.resources — resource directory helpers and migration."""

from pathlib import Path

from grafli.format import Arrow, Board, Box, Image, Note
from grafli.resources import (
    ensure_res_dir,
    migrate_all,
    migrate_annotations,
    migrate_images_dir,
    res_dir,
)


def test_res_dir(tmp_path: Path):
    grafli = tmp_path / "diagram.grafli"
    assert res_dir(grafli) == tmp_path / "diagram-res"


def test_ensure_res_dir(tmp_path: Path):
    grafli = tmp_path / "diagram.grafli"
    rd = ensure_res_dir(grafli)
    assert rd.is_dir()
    assert rd.name == "diagram-res"


def test_migrate_images_dir(tmp_path: Path):
    grafli = tmp_path / "demo.grafli"
    grafli.touch()
    old = tmp_path / "demo-images"
    old.mkdir()
    (old / "img-001.png").write_bytes(b"PNG")

    board = Board()
    img = Image(id="i1", image_path="demo-images/img-001.png",
                x=0, y=0, w=100, h=80)
    board.add_image(img)

    assert migrate_images_dir(grafli, board) is True
    assert not old.exists()
    assert (tmp_path / "demo-res" / "img-001.png").exists()
    assert board.images[0].image_path == "demo-res/img-001.png"


def test_migrate_images_dir_noop(tmp_path: Path):
    grafli = tmp_path / "demo.grafli"
    grafli.touch()
    board = Board()
    assert migrate_images_dir(grafli, board) is False


def test_migrate_images_dir_target_exists(tmp_path: Path):
    """When -res/ already exists, merge contents from -images/."""
    grafli = tmp_path / "demo.grafli"
    grafli.touch()
    old = tmp_path / "demo-images"
    old.mkdir()
    (old / "img-001.png").write_bytes(b"PNG")
    new = tmp_path / "demo-res"
    new.mkdir()
    (new / "existing.md").write_text("hello")

    board = Board()
    img = Image(id="i1", image_path="demo-images/img-001.png",
                x=0, y=0, w=100, h=80)
    board.add_image(img)

    assert migrate_images_dir(grafli, board) is True
    assert (new / "img-001.png").exists()
    assert (new / "existing.md").exists()
    assert board.images[0].image_path == "demo-res/img-001.png"


def test_migrate_annotations_box(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    box = Box(id="api", label="API", x=0, y=0, w=100, h=50,
              annotation="rate limiting here?")
    board.add_box(box)

    assert migrate_annotations(grafli, board) is True
    md = tmp_path / "test-res" / "api.md"
    assert md.exists()
    assert md.read_text() == "rate limiting here?"
    assert box.url == "test-res/api.md"
    assert box.annotation == ""


def test_migrate_annotations_note(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    note = Note(id="n1", x=0, y=0, text="TODO", annotation="move this")
    board.add_note(note)

    assert migrate_annotations(grafli, board) is True
    md = tmp_path / "test-res" / "n1.md"
    assert md.exists()
    assert note.url == "test-res/n1.md"
    assert note.annotation == ""


def test_migrate_annotations_arrow(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    arrow = Arrow(from_id="a", to_id="b", label="calls",
                  annotation="review direction")
    board.add_arrow(arrow)

    assert migrate_annotations(grafli, board) is True
    md = tmp_path / "test-res" / "a--b.md"
    assert md.exists()
    assert md.read_text() == "review direction"
    assert arrow.url == "test-res/a--b.md"
    assert arrow.annotation == ""


def test_migrate_annotations_image(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    img = Image(id="pic1", image_path="pic.png", x=0, y=0, w=100, h=80,
                annotation="screenshot of bug")
    board.add_image(img)

    assert migrate_annotations(grafli, board) is True
    md = tmp_path / "test-res" / "pic1.md"
    assert md.exists()
    assert img.url == "test-res/pic1.md"
    assert img.annotation == ""


def test_migrate_annotations_skips_existing_url(tmp_path: Path):
    """Elements with a url already set should not be migrated."""
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    box = Box(id="api", label="API", x=0, y=0, w=100, h=50,
              annotation="old note", url="docs/spec.md")
    board.add_box(box)

    assert migrate_annotations(grafli, board) is False
    assert box.url == "docs/spec.md"
    assert box.annotation == "old note"


def test_migrate_annotations_noop(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    box = Box(id="api", label="API", x=0, y=0, w=100, h=50)
    board.add_box(box)
    assert migrate_annotations(grafli, board) is False


def test_migrate_idempotent(tmp_path: Path):
    grafli = tmp_path / "test.grafli"
    grafli.touch()
    board = Board()
    box = Box(id="api", label="API", x=0, y=0, w=100, h=50,
              annotation="note text")
    board.add_box(box)

    migrate_annotations(grafli, board)
    md = tmp_path / "test-res" / "api.md"
    assert md.exists()

    # Running again should not change anything
    assert migrate_annotations(grafli, board) is False


def test_migrate_all(tmp_path: Path):
    grafli = tmp_path / "demo.grafli"
    grafli.touch()
    old = tmp_path / "demo-images"
    old.mkdir()
    (old / "img.png").write_bytes(b"PNG")

    board = Board()
    img = Image(id="i1", image_path="demo-images/img.png",
                x=0, y=0, w=100, h=80)
    board.add_image(img)
    box = Box(id="api", label="API", x=0, y=0, w=100, h=50,
              annotation="check this")
    board.add_box(box)

    assert migrate_all(grafli, board) is True
    assert img.image_path == "demo-res/img.png"
    assert box.url == "demo-res/api.md"
    assert box.annotation == ""
    assert (tmp_path / "demo-res" / "api.md").exists()
    assert (tmp_path / "demo-res" / "img.png").exists()
