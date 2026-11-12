"""Stub source for examples/architecture.grafli, so its @path:line refs
resolve and `grafli diagnose` can check them."""

import pytest


USER = "ada"


@pytest.fixture
def shop():
    """A shop with stubbed inventory and payment."""
    raise NotImplementedError


def test_empty_cart_is_rejected(shop):
    """An order with no items fails."""
    raise NotImplementedError


def test_out_of_stock_is_rejected(shop):
    """Reserve fails, nothing is charged."""
    raise NotImplementedError


def test_declined_payment_releases_stock(shop):
    """A decline gives the items back."""
    raise NotImplementedError


def test_order_id_is_unique(shop):
    """Two orders never share an id."""
    raise NotImplementedError


def test_total_matches_items(shop):
    """The charged total is the items' sum."""
    raise NotImplementedError


def test_order_happy_path(shop):
    order_id = shop.place_order(user=USER, items=["book"], total=12)
    assert shop.audit.has("order.created", order_id)
