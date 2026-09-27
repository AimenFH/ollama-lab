"""Pricing calculation. Support has reported incorrect customer totals."""
from decimal import Decimal
from .validation import validate_order


def quote(lines, discount=Decimal("0")):
    validate_order(lines, discount)
    subtotal = sum((line["unit_price"] * line["quantity"] for line in lines), Decimal("0"))
    shipping = Decimal("0") if subtotal >= Decimal("100") else Decimal("5")
    total = ((subtotal + shipping) * (1 - discount)).quantize(Decimal("0.01"))
    return {"subtotal": subtotal, "shipping": shipping, "total": total}
