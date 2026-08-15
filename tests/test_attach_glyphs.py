"""Attachment indicators show their kind (#148).

The chooser is pure logic; the painters are pixels. These tests pin the
chooser — which glyph an element's attachment gets — including the legacy
untyped-url case and the bare `&doc` that used to show nothing at all.
"""

from __future__ import annotations

from grafli.format import Box, Image, Note
from grafli.items import _attach_glyph_kind


def _box(**kw) -> Box:
    return Box(id="b", label="B", x=0, y=0, w=100, h=60, **kw)


def test_typed_attachments_get_their_kind():
    assert _attach_glyph_kind(_box(attach_kind="doc", url="notes")) == "doc"
    assert _attach_glyph_kind(_box(attach_kind="graph", url="sub")) == "graph"
    assert _attach_glyph_kind(
        _box(attach_kind="link", url="https://x.y")) == "link"


def test_bare_doc_attachment_gets_the_doc_glyph():
    # `&doc` with no name: url is empty, the kind alone carries it.
    assert _attach_glyph_kind(_box(attach_kind="doc")) == "doc"


def test_legacy_untyped_url_reads_as_link():
    assert _attach_glyph_kind(_box(url="https://x.y")) == "link"


def test_no_attachment_no_glyph():
    assert _attach_glyph_kind(_box()) == ""
    assert _attach_glyph_kind(Image(id="i", image_path="a.svg",
                                    x=0, y=0, w=10, h=10)) == ""
    assert _attach_glyph_kind(Note(id="n", x=0, y=0, text="t")) == ""
