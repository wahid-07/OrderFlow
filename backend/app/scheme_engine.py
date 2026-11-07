from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, Field

MONEY = Decimal("0.01")


class BuyXGetYScheme(BaseModel):
    type: Literal["buy_x_get_y"]
    buy_quantity: int = Field(gt=0)
    free_quantity: int = Field(gt=0)


class QuantityDiscountScheme(BaseModel):
    type: Literal["quantity_discount"]
    minimum_quantity: int = Field(gt=0)
    discount_percent: Decimal = Field(gt=0, le=100)


SchemeRule = BuyXGetYScheme | QuantityDiscountScheme


@dataclass(frozen=True)
class LineCalculation:
    requested_quantity: int
    paid_quantity: int
    free_quantity: int
    delivered_quantity: int
    unit_price: Decimal
    subtotal: Decimal
    discount: Decimal
    free_value: Decimal
    total: Decimal


def calculate_line(
    quantity: int,
    unit_price: Decimal,
    rule: SchemeRule | None,
) -> LineCalculation:
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    if unit_price < 0:
        raise ValueError("unit_price cannot be negative")

    subtotal = (unit_price * quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
    free_quantity = 0
    discount = Decimal("0.00")

    if isinstance(rule, BuyXGetYScheme):
        free_quantity = quantity // rule.buy_quantity * rule.free_quantity
    elif isinstance(rule, QuantityDiscountScheme) and quantity >= rule.minimum_quantity:
        discount = (subtotal * rule.discount_percent / Decimal("100")).quantize(
            MONEY,
            rounding=ROUND_HALF_UP,
        )

    free_value = (unit_price * free_quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
    return LineCalculation(
        requested_quantity=quantity,
        paid_quantity=quantity,
        free_quantity=free_quantity,
        delivered_quantity=quantity + free_quantity,
        unit_price=unit_price,
        subtotal=subtotal,
        discount=discount,
        free_value=free_value,
        total=subtotal - discount,
    )