"""Business requirements owned by the customer. Do not edit these tests."""
import unittest
from decimal import Decimal as D
from orders.pricing import quote
from orders.service import place_order
from orders.storage import OrderStore


def lines(price, quantity=1):
    return [{"unit_price": D(price), "quantity": quantity}]


class PricingAcceptance(unittest.TestCase):
    def test_shipping_is_not_discounted(self):
        self.assertEqual(quote(lines("50"), D("0.10"))["total"], D("50.00"))

    def test_shipping_threshold_uses_discounted_goods(self):
        result = quote(lines("100"), D("0.10"))
        self.assertEqual(result["shipping"], D("5.00"))
        self.assertEqual(result["total"], D("95.00"))

    def test_round_half_up(self):
        self.assertEqual(quote(lines("10.005"))["total"], D("15.01"))

    def test_round_each_line_before_summing(self):
        result = quote(lines("0.335") + lines("0.335"))
        self.assertEqual(result["subtotal"], D("0.68"))
        self.assertEqual(result["total"], D("5.68"))

    def test_discount_amount_rounded_before_subtraction(self):
        self.assertEqual(quote(lines("10.05"), D("0.10"))["total"], D("14.04"))

    def test_free_shipping_at_exact_threshold(self):
        self.assertEqual(quote(lines("125"), D("0.20"))["total"], D("100.00"))

    def test_no_discount_regression(self):
        self.assertEqual(quote(lines("20", 2))["total"], D("45.00"))

    def test_invalid_inputs_rejected(self):
        for items, discount in [([], D("0")), (lines("-1"), D("0")),
                                (lines("10", 0), D("0")), (lines("10", True), D("0")),
                                (lines("10"), D("0.31")), (lines("NaN"), D("0"))]:
            with self.subTest(items=items, discount=discount), self.assertRaises(ValueError):
                quote(items, discount)

    def test_persistence_and_duplicate_protection(self):
        store = OrderStore()
        expected = place_order(store, "O-001", lines("20"))
        self.assertEqual(store.get("O-001"), expected)
        expected["total"] = D("999")
        self.assertEqual(store.get("O-001")["total"], D("25.00"))
        with self.assertRaises(ValueError):
            place_order(store, "O-001", lines("20"))
