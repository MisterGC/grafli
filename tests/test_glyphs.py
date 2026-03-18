"""Tests for GlyphIndex search functionality."""

from grafli.glyphs import GlyphIndex, ensure_text_presentation


def test_search_single_word():
    idx = GlyphIndex.get()
    results = idx.search("ARROW")
    assert len(results) > 0
    for ch, name in results:
        assert "ARROW" in name


def test_search_multi_word():
    idx = GlyphIndex.get()
    all_arrows = idx.search("ARROW", limit=500)
    right_arrows = idx.search("RIGHT ARROW", limit=500)
    assert len(right_arrows) > 0
    assert len(right_arrows) < len(all_arrows)
    for ch, name in right_arrows:
        assert "RIGHT" in name and "ARROW" in name


def test_search_case_insensitive():
    idx = GlyphIndex.get()
    results = idx.search("star")
    assert len(results) > 0
    found_black_star = any("BLACK STAR" in name for _, name in results)
    assert found_black_star


def test_search_limit():
    idx = GlyphIndex.get()
    results = idx.search("ARROW", limit=60)
    assert len(results) <= 60


def test_search_empty_returns_all_category():
    idx = GlyphIndex.get()
    results = idx.search("")
    assert len(results) > 0


def test_search_whitespace_returns_all_category():
    idx = GlyphIndex.get()
    results = idx.search("   ")
    assert len(results) > 0


def test_categories_list():
    idx = GlyphIndex.get()
    cats = idx.categories()
    assert "Arrows" in cats
    assert "Math" in cats
    assert "Geometric" in cats
    assert len(cats) == 7


def test_get_category():
    idx = GlyphIndex.get()
    arrows = idx.get_category("Arrows")
    assert len(arrows) > 0
    for ch, name in arrows:
        assert any(
            start <= ord(ch) <= end
            for start, end in [(0x2190, 0x21FF), (0x2900, 0x297F), (0x2B00, 0x2BFF)]
        )


def test_get_category_none_returns_all():
    idx = GlyphIndex.get()
    all_glyphs = idx.get_category(None, limit=5000)
    arrows = idx.get_category("Arrows", limit=5000)
    assert len(all_glyphs) > len(arrows)


def test_search_within_category():
    idx = GlyphIndex.get()
    all_results = idx.search("RIGHT", limit=500)
    arrow_results = idx.search("RIGHT", category="Arrows", limit=500)
    assert len(arrow_results) > 0
    assert len(arrow_results) <= len(all_results)


# ── ensure_text_presentation ─────────────────────────────────


def test_ensure_text_presentation_appends_fe0e():
    # U+2603 SNOWMAN is in Symbols range (0x2600-0x26FF)
    result = ensure_text_presentation("\u2603")
    assert result == "\u2603\uFE0E"


def test_ensure_text_presentation_skips_plain_text():
    result = ensure_text_presentation("hello")
    assert result == "hello"


def test_ensure_text_presentation_preserves_existing_fe0e():
    result = ensure_text_presentation("\u2603\uFE0E")
    assert result == "\u2603\uFE0E"


def test_ensure_text_presentation_preserves_existing_fe0f():
    result = ensure_text_presentation("\u2603\uFE0F")
    assert result == "\u2603\uFE0F"


def test_ensure_text_presentation_mixed_text():
    result = ensure_text_presentation("A\u2603B")
    assert result == "A\u2603\uFE0EB"


def test_ensure_text_presentation_empty():
    assert ensure_text_presentation("") == ""
