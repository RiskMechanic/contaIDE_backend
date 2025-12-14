# core/utils.py
from decimal import Decimal, ROUND_HALF_UP

def q2(value: Decimal | None) -> Decimal:
    return (value or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
