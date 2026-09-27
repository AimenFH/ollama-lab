"""In-memory storage boundary; no database setup is needed for the lab."""
from copy import deepcopy


class OrderStore:
    def __init__(self):
        self._orders = {}

    def save(self, order_id, quote):
        if order_id in self._orders:
            raise ValueError("duplicate order")
        self._orders[order_id] = deepcopy(quote)

    def get(self, order_id):
        return deepcopy(self._orders[order_id])
