# Customer pricing rules

All prices are EUR. Use Decimal values constructed from strings, never floats.
For each line, multiply unit price by quantity, then round to cents with
ROUND_HALF_UP. Add these rounded line totals to get subtotal. Calculate the
discount amount on subtotal and round this amount to cents with ROUND_HALF_UP.
Subtract it from subtotal to get discounted goods. Shipping is free when
DISCOUNTED GOODS are at least EUR 100.00; otherwise shipping is EUR 5.00.
Shipping is never discounted. Total is discounted goods plus shipping.

Keep the quote input and output interface unchanged: lines contain unit_price
and quantity; the result contains subtotal, shipping, total, all Decimal values.
Keep input validation, persistence, and duplicate protection working.
Do not edit orders/validation.py or tests/test_acceptance.py.
Add your own regression test in tests/test_student.py.

Read https://docs.python.org/3/library/decimal.html for Decimal and ROUND_HALF_UP.
A local copy of the needed concepts is supplied for offline practice.
