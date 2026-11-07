from decimal import Decimal

import pytest

from app.scheme_engine import (
    BuyXGetYScheme,
    QuantityDiscountScheme,
    calculate_line,
)


@pytest.mark.parametrize(
    ("quantity", "expected_free"),
    [(10, 1), (20, 2), (25, 2)],
)
def test_buy_x_get_y_repeats_for_complete_multiples(
    quantity: int,
    expected_free: int,
) -> None:
    calculation = calculate_line(
        quantity,
        Decimal("840.00"),
        BuyXGetYScheme(
            type="buy_x_get_y",
            buy_quantity=10,
            free_quantity=1,
        ),
    )

    assert calculation.paid_quantity == quantity
    assert calculation.free_quantity == expected_free
    assert calculation.delivered_quantity == quantity + expected_free
    assert calculation.total == Decimal("840.00") * quantity


@pytest.mark.parametrize(
    ("quantity", "expected_discount"),
    [(4, Decimal("0.00")), (5, Decimal("147.00"))],
)
def test_quantity_discount_applies_at_inclusive_threshold(
    quantity: int,
    expected_discount: Decimal,
) -> None:
    calculation = calculate_line(
        quantity,
        Decimal("980.00"),
        QuantityDiscountScheme(
            type="quantity_discount",
            minimum_quantity=5,
            discount_percent=Decimal("3"),
        ),
    )

    assert calculation.discount == expected_discount
    assert calculation.total == Decimal("980.00") * quantity - expected_discount


def test_line_without_scheme_keeps_ordered_quantity_and_price() -> None:
    calculation = calculate_line(2, Decimal("1200.00"), None)

    assert calculation.free_quantity == 0
    assert calculation.discount == Decimal("0.00")
    assert calculation.total == Decimal("2400.00")


def test_scheme_calculation_rejects_nonpositive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        calculate_line(0, Decimal("100.00"), None)