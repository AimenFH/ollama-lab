"""Application service coordinates pricing and persistence."""
from decimal import Decimal
from .pricing import quote


def place_order(store, order_id, lines, discount=Decimal("0")):
    result = quote(lines, discount)
    store.save(order_id, result)
    return result
