"""#294: a container without a colour draws a quiet plate and an outline,
and its title is bold and larger than its children's labels, a step smaller
each level down."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from grafli import theme
from grafli.constants import BOX_FONT_SIZES, CONTAINER_TITLE_PX
from grafli.format import parse

# The board from the issue: two uncoloured containers, an arrow into one.
TWO = ('#!grafli v4\n'
       '@ box api "Api" 40,40 520x200\n'
       '@ box gateway "Gateway" 70,100 200x80 >api\n'
       '@ box cache "Cache" 320,100 200x80 >api\n'
       '@ box db "DB" 720,40 300x200\n'
       '@ box users "Users" 770,100 200x80 >db\n'
       '@ arrow cache -> db\n')

DEEP = ('#!grafli v4\n'
        '@ box host "Host" 0,0 900x700\n'
        '@ box sw "Software" 20,40 860x620 >host\n'
        '@ box api "Api" 40,80 500x500 >sw\n'
        '@ box svc "Service" 60,140 440x400 >api\n'
        '@ box repo "Repository" 80,200 200x100 >svc\n'
        '@ box mon "Monitor" 950,0 200x100\n')


def _app():
    return QApplication.instance() or QApplication([])


def _view(text: str):
    from grafli.view import GrafliView
    _app()
    view = GrafliView()
    view.load_board(parse(text))
    return view


def _scene_image(view, rect: QRectF) -> QImage:
    """The scene inside *rect*, one pixel per scene unit."""
    img = QImage(int(rect.width()), int(rect.height()),
                 QImage.Format.Format_ARGB32)
    img.fill(theme.SCENE_BG)
    p = QPainter(img)
    view._scene.render(p, QRectF(0, 0, img.width(), img.height()), rect)
    p.end()
    return img


def _close(a: QColor, b: QColor, tol: int = 12) -> bool:
    return (abs(a.red() - b.red()) <= tol and abs(a.green() - b.green()) <= tol
            and abs(a.blue() - b.blue()) <= tol)


# ── Plate and outline ──

def test_an_uncoloured_container_has_an_outline_and_a_plate():
    view = _view(TWO)
    for bid in ("api", "db"):
        item = view._box_items[bid]
        assert item._container_look(), bid
        assert item.pen().style() == Qt.PenStyle.SolidLine, bid
        assert item.pen().color() == theme.BOX_OUTLINE, bid
        assert item.brush().style() != Qt.BrushStyle.NoBrush, bid
        # The plate reads as a shade off the canvas.
        assert item._fill_color() != theme.SCENE_BG, bid


def test_a_flat_uncoloured_container_gets_the_plate_too():
    view = _view(TWO.replace('"DB" 720,40 300x200',
                             '"DB" 720,40 300x200 !flat'))
    item = view._box_items["db"]
    assert item.pen().style() == Qt.PenStyle.SolidLine
    assert item._fill_color() != theme.SCENE_BG


def test_a_coloured_container_keeps_its_tint_without_an_outline():
    view = _view(TWO.replace('"DB" 720,40 300x200',
                             '"DB" 720,40 300x200 %teal'))
    item = view._box_items["db"]
    assert item.pen().style() == Qt.PenStyle.NoPen
    assert item.brush().color().alphaF() == pytest.approx(0.7, abs=0.01)


def test_a_leaf_box_keeps_its_light_plate():
    view = _view(TWO)
    item = view._box_items["cache"]
    assert item.brush().color() == theme.BOX_FILL
    assert item.pen().color() == theme.BOX_OUTLINE


def test_nested_plates_draw_a_shade_deeper_each_level():
    view = _view(DEEP)
    img = _scene_image(view, QRectF(0, 0, 900, 700))
    # Inside each container, clear of titles and children.
    shades = [QColor(img.pixel(x, y)) for x, y in
              ((5, 690), (25, 650), (45, 570), (65, 530))]
    lums = [c.lightnessF() for c in shades]
    assert lums == sorted(lums, reverse=True)
    assert len(set(round(v, 3) for v in lums)) == 4
    assert lums[0] < QColor(theme.SCENE_BG).lightnessF()


def test_dark_theme_plate_and_outline_show():
    theme.set_theme("dark")
    try:
        view = _view(TWO)
        img = _scene_image(view, QRectF(0, 0, 1060, 280))
        edge = QColor(img.pixel(720, 200))
        inside = QColor(img.pixel(740, 220))
        assert _close(edge, QColor(theme.BOX_OUTLINE))
        assert inside != QColor(theme.SCENE_BG)
    finally:
        theme.set_theme("light")


# ── Title by level ──

def test_a_container_title_is_bold_and_above_its_childrens_labels():
    view = _view(TWO)
    for bid, child in (("api", "cache"), ("db", "users")):
        title = view._box_items[bid]._label.font()
        label = view._box_items[child]._label.font()
        assert title.bold() and not label.bold(), bid
        assert title.pointSize() > label.pointSize(), bid


THREE = ('#!grafli v4\n'
         '@ box host "Host" 0,0 900x600\n'
         '@ box sw "Software" 20,40 860x540 >host\n'
         '@ box api "Api" 40,80 500x400 >sw\n'
         '@ box ctl "Controller" 60,140 200x100 >api\n')


def test_container_titles_step_down_by_level():
    view = _view(THREE)
    sizes = {bid: view._box_items[bid]._label.font().pointSize()
             for bid in ("host", "sw", "api", "ctl")}
    assert sizes == {"host": CONTAINER_TITLE_PX[0],
                     "sw": CONTAINER_TITLE_PX[1],
                     "api": CONTAINER_TITLE_PX[2],
                     "ctl": BOX_FONT_SIZES[""]}
    assert min(CONTAINER_TITLE_PX) > BOX_FONT_SIZES[""]


def test_a_set_title_size_is_honoured_and_stays_bold():
    view = _view(TWO.replace('"Api" 40,40 520x200', '"Api" 40,40 520x200 ~large'))
    font = view._box_items["api"]._label.font()
    assert font.pointSize() == BOX_FONT_SIZES["large"]
    assert font.bold()


def test_a_container_moved_into_another_takes_the_next_level_size():
    view = _view(TWO + '@ box zone "Zone" 680,-40 400x320\n')
    db = view._box_items["db"]
    # db sits inside zone's rect: loading nests it there.
    assert view._board.box_by_id("db").parent == "zone"
    assert db._label.font().pointSize() == CONTAINER_TITLE_PX[1]
    # Dropped where no box is, db leaves zone and is top level again.
    view._check_nesting(db, QPointF(3000, 3000))
    assert view._board.box_by_id("db").parent == ""
    assert db._label.font().pointSize() == CONTAINER_TITLE_PX[0]
    # Dropped back over zone (now shrunk to fit its own label), it steps
    # down a level.
    zone = view._board.box_by_id("zone")
    view._check_nesting(db, QPointF(zone.x + zone.w / 2, zone.y + zone.h / 2))
    assert view._board.box_by_id("db").parent == "zone"
    assert db._label.font().pointSize() == CONTAINER_TITLE_PX[1]


def test_the_largest_title_clears_children_at_the_layout_margin():
    """Children of a container with an unset size are laid out 40 px below
    its top edge; a top-level title's ink ends above that."""
    from grafli.board_info import top_margin
    board = ('#!grafli v4\n'
             '@ box c "Api gateway" 0,0 400x200\n'
             f'@ box k "Kid" 300,{int(top_margin(""))} 80x80 >c\n')
    view = _view(board)
    label = view._box_items["c"]._label
    rect = label.mapRectToScene(label.boundingRect())
    img = _scene_image(view, QRectF(0, 0, 400, 200))
    plate = QColor(img.pixel(250, 20))
    # The title's columns, left of the child.
    ink_rows = [y for y in range(int(rect.top()), int(rect.bottom()))
                if any(not _close(QColor(img.pixel(x, y)), plate, 40)
                       for x in range(int(rect.left()) + 4, 280))]
    assert ink_rows, "the title drew no ink"
    assert max(ink_rows) < top_margin("")


# ── The arrow ends at the container's edge ──

def test_an_arrow_into_a_container_ends_at_its_visible_edge():
    view = _view(TWO)
    img = _scene_image(view, QRectF(0, 0, 1060, 280))
    y = 140   # the arrow's row: Cache's middle
    arrow = QColor(theme.ARROW_COLOR)
    outline = QColor(theme.BOX_OUTLINE)
    tip = max(x for x in range(520, 720)
              if _close(QColor(img.pixel(x, y)), arrow, 30))
    edge = min(x for x in range(700, 760)
               if _close(QColor(img.pixel(x, y - 40)), outline))
    # The outline is drawn where the arrowhead stops.
    assert abs(tip - edge) <= 3, (tip, edge)
    assert _close(QColor(img.pixel(edge, y - 40)), outline)


def test_the_live_tab_draws_the_plate_and_outline(tmp_path):
    """The live tab shows the SVG the render worker draws."""
    pytest.importorskip("starlette")
    import asyncio

    from PySide6.QtSvg import QSvgRenderer

    from grafli.serve.render import RenderWorker
    path = tmp_path / "two.grafli"
    path.write_text(TWO)

    async def go():
        worker = RenderWorker()
        try:
            await worker.shell()
            return await worker.render(path, TWO, tmp_path)
        finally:
            await worker.close()

    frame = asyncio.run(go())
    bx, by, bw, bh = frame["board"]["bounds"]
    svg = QSvgRenderer(QByteArray(frame["svgs"]["b0-0"].encode()))
    _app()
    img = QImage(int(bw), int(bh), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    p = QPainter(img)
    svg.render(p, QRectF(0, 0, bw, bh))
    p.end()

    def at(x, y):
        return QColor(img.pixel(int(x - bx), int(y - by)))

    for left, top in ((40, 40), (720, 40)):
        assert _close(at(left, top + 160), QColor(theme.BOX_OUTLINE)), left
        inside = at(left + 20, top + 180)
        assert inside != QColor(theme.SCENE_BG), left
        assert not _close(inside, QColor(theme.BOX_FILL), 4), left
