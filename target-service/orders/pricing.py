"""Pricing calculation. Support has reported incorrect customer totals."""
from decimal import ROUND_HALF_UP, Decimal
from .validation import validate_order


def quote(lines, discount=Decimal("0")):
    validate_order(lines, discount)
    subtotal = sum(((Decimal(str(line["unit_price"])) * Decimal(str(line["quantity"]))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for line in lines), Decimal("0.00"))
    discount_amount = (subtotal * Decimal(str(discount))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    discounted_goods = subtotal - discount_amount
    shipping = Decimal("0.00") if discounted_goods >= Decimal("100.00") else Decimal("5.00")
    total = (discounted_goods + shipping).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"subtotal": subtotal, "shipping": shipping, "total": total}
