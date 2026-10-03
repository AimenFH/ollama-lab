import unittest
from decimal import Decimal as D
from orders.pricing import quote


def lines(price, quantity=1):
    return [{"unit_price": D(price), "quantity": quantity}]


class PricingStudent(unittest.TestCase):
    def test_three_decimal_unit_price_with_quantity_greater_than_1(self):
        result = quote(lines("0.335", 3))
        self.assertEqual(result["subtotal"], D("1.01"))
        self.assertEqual(result["total"], D("6.01"))

if __name__ == "__main__":
    unittest.main()