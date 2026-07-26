"""Flow caption scales with the stage (#134).

The caption card is a fixed viewport-space overlay, so a hardcoded point
size read far too small on large windows and F5 fullscreen projectors.
`flow_caption_metrics` anchors the description on viewport height, floored
to the base 11pt (small windows unchanged) and capped at 28pt (never
dominates the stage); title, hint, and padding follow by the base ratio.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pytest import approx

from grafli.view.core import flow_caption_metrics

BASE_DESC = 11.0
BASE_TITLE = 14.0
BASE_HINT = 9.0


def test_small_window_keeps_the_base_sizes():
    # 0.018 * 600 = 10.8 -> floored to the base, so nothing regresses.
    m = flow_caption_metrics(800, 600)
    assert m["desc_pt"] == BASE_DESC
    assert m["title_pt"] == BASE_TITLE
    assert m["hint_pt"] == BASE_HINT
    assert m["pad"] == 12.0
    assert m["gap"] == 5.0


def test_typical_window_scales_up():
    m = flow_caption_metrics(1600, 1000)
    assert m["desc_pt"] == 18.0  # 0.018 * 1000
    assert m["desc_pt"] > BASE_DESC


def test_large_display_is_capped():
    m = flow_caption_metrics(3840, 2160)  # 0.018 * 2160 = 38.9 -> capped
    assert m["desc_pt"] == 28.0


def test_ratios_are_preserved_at_every_size():
    for vp_h in (600, 1000, 1440, 2160):
        m = flow_caption_metrics(1920, vp_h)
        assert m["title_pt"] / m["desc_pt"] == approx(BASE_TITLE / BASE_DESC)
        assert m["hint_pt"] / m["desc_pt"] == approx(BASE_HINT / BASE_DESC)
        assert m["pad"] / m["desc_pt"] == approx(12.0 / BASE_DESC)
        assert m["gap"] / m["desc_pt"] == approx(5.0 / BASE_DESC)


def test_description_is_monotonic_in_height_until_the_cap():
    sizes = [flow_caption_metrics(1920, h)["desc_pt"]
             for h in (500, 800, 1080, 1440, 2000, 3000)]
    assert sizes == sorted(sizes)
    assert sizes[0] == BASE_DESC   # floored
    assert sizes[-1] == 28.0       # capped


def test_max_width_grows_with_viewport_but_holds_640_on_small():
    # Small/typical widths keep the old 640 cap; wide screens get more room.
    assert flow_caption_metrics(1200, 1000)["max_w"] == 640.0
    assert flow_caption_metrics(3840, 2160)["max_w"] == 3840 * 0.4
    # Never wider than the viewport minus its margin.
    assert flow_caption_metrics(600, 800)["max_w"] == 600 - 40
