"""Input validation is independent of pricing and must stay enabled."""
from decimal import Decimal


def validate_order(lines, discount):
    if not lines:
        raise ValueError("an order needs at least one line")
    if not isinstance(discount, Decimal) or not discount.is_finite():
        raise ValueError("discount must be a finite Decimal")
    if not Decimal("0") <= discount <= Decimal("0.30"):
        raise ValueError("discount must be between 0 and 0.30")
    for line in lines:
        price, quantity = line["unit_price"], line["quantity"]
        if not isinstance(price, Decimal) or not price.is_finite() or price < 0:
            raise ValueError("unit price must be a finite non-negative Decimal")
        if type(quantity) is not int or quantity <= 0:
            raise ValueError("quantity must be a positive integer")
