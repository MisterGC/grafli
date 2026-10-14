"""Heat providers: what the heatmap renderer colours a board by.

A provider reads a board and returns a ``HeatReading`` — a heat per element
id (0.0 cold .. 1.0 hot) plus the legend that explains it. The renderer in
``grafli/view/complexity.py`` only paints readings; it never measures. The
degree count is the first provider; overlay files plug in beside it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from grafli.constants import HEATMAP_EQUAL_HEAT
from grafli.format import Arrow, Board


@dataclass
class HeatLegend:
    """What the legend above the minimap says about a reading."""
    title: str
    low: str = "Low"
    high: str = "High"


@dataclass
class HeatReading:
    """Heat per element id, 0.0-1.0, and the legend for it."""
    values: dict[str, float] = field(default_factory=dict)
    legend: HeatLegend = field(default_factory=lambda: HeatLegend(""))


class HeatProvider(Protocol):
    def analysable(self, board: Board) -> bool:
        """Whether a reading of ``board`` would say anything."""
        ...

    def read(self, board: Board) -> HeatReading:
        ...


class DegreeProvider:
    """Degree centrality per box: the arrow ends touching it, normalized.

    ``counts`` decides which arrows are counted — the view passes its graph
    edge resolver so annotation arrows (box→note, note→box) don't heat a box.
    """

    TITLE = "Connectivity"

    def __init__(self, counts: Callable[[Arrow], bool] = lambda a: True):
        self._counts = counts

    def analysable(self, board: Board) -> bool:
        # Without boxes there is nothing to paint, and without counted arrows
        # every box is equally cold — a picture that carries no reading.
        return bool(board.boxes
                    and any(self._counts(a) for a in board.arrows))

    def read(self, board: Board) -> HeatReading:
        legend = HeatLegend(self.TITLE)
        if not board.boxes:
            return HeatReading({}, legend)

        degree: dict[str, int] = {b.id: 0 for b in board.boxes}
        for arrow in board.arrows:
            if not self._counts(arrow):
                continue
            if arrow.from_id in degree:
                degree[arrow.from_id] += 1
            if arrow.to_id in degree:
                degree[arrow.to_id] += 1

        max_deg = max(degree.values())
        if max_deg == 0:
            return HeatReading({bid: 0.0 for bid in degree}, legend)
        # All-equal case
        if min(degree.values()) == max_deg:
            return HeatReading({bid: HEATMAP_EQUAL_HEAT for bid in degree},
                               legend)
        return HeatReading({bid: d / max_deg for bid, d in degree.items()},
                           legend)
