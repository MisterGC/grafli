"""Stub source for examples/architecture.grafli."""


def test_order_happy_path(shop):
    order_id = shop.place_order(user="ada", items=["book"], total=12)
    assert shop.audit.has("order.created", order_id)
