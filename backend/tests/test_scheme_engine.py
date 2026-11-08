from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.scheme_engine import (
    BuyXGetYScheme,
    QuantityDiscountScheme,
    SlabDiscountScheme,
    SlabTier,
    calculate_line,
    evaluate_line_schemes,
    find_eligible_slab_tier,
)


# =====================================================================
# 1. Existing Tests (Preserved 100% for Backward Compatibility)
# =====================================================================

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

    with pytest.raises(ValueError, match="quantity must be greater than zero"):
        calculate_line(-5, Decimal("100.00"), None)


def test_scheme_calculation_rejects_negative_unit_price() -> None:
    with pytest.raises(ValueError, match="unit_price cannot be negative"):
        calculate_line(5, Decimal("-10.00"), None)


# =====================================================================
# 2. Buy X Get Y Free Boundary Conditions
# =====================================================================

@pytest.mark.parametrize(
    ("quantity", "expected_free", "expected_delivered"),
    [
        (1, 0, 1),
        (9, 0, 9),
        (10, 1, 11),
        (19, 1, 20),
        (20, 2, 22),
        (29, 2, 31),
        (30, 3, 33),
        (39, 3, 42),
    ],
)
def test_buy_x_get_y_boundary_conditions(
    quantity: int,
    expected_free: int,
    expected_delivered: int,
) -> None:
    unit_price = Decimal("777.60")
    scheme = BuyXGetYScheme(buy_quantity=10, free_quantity=1)
    calc = calculate_line(quantity, unit_price, scheme)

    assert calc.requested_quantity == quantity
    assert calc.paid_quantity == quantity
    assert calc.free_quantity == expected_free
    assert calc.delivered_quantity == expected_delivered
    assert calc.subtotal == unit_price * quantity
    assert calc.discount == Decimal("0.00")
    assert calc.free_value == unit_price * expected_free
    assert calc.total == unit_price * quantity
    if expected_free > 0:
        assert calc.scheme_label == "10+ cases → 1 free"
    else:
        assert calc.scheme_label is None


# =====================================================================
# 3. Quantity Discount Thresholds & Precision
# =====================================================================

@pytest.mark.parametrize(
    ("quantity", "expected_discount", "expected_total"),
    [
        (1, Decimal("0.00"), Decimal("2030.00")),
        (4, Decimal("0.00"), Decimal("8120.00")),
        (5, Decimal("304.50"), Decimal("9845.50")),
        (6, Decimal("365.40"), Decimal("11814.60")),
    ],
)
def test_quantity_discount_threshold_and_precision(
    quantity: int,
    expected_discount: Decimal,
    expected_total: Decimal,
) -> None:
    unit_price = Decimal("2030.00")
    scheme = QuantityDiscountScheme(
        minimum_quantity=5,
        discount_percent=Decimal("3.00"),
    )
    calc = calculate_line(quantity, unit_price, scheme)

    assert calc.paid_quantity == quantity
    assert calc.free_quantity == 0
    assert calc.subtotal == unit_price * quantity
    assert calc.discount == expected_discount
    assert calc.total == expected_total


# =====================================================================
# 4. Slab Discount Scheme Calculations
# =====================================================================

@pytest.fixture
def standard_slab_scheme() -> SlabDiscountScheme:
    """Configurable FMCG slab: 10-24: 3%, 25-49: 5%, 50+: 7%."""
    return SlabDiscountScheme(
        name="Tiered Volume Discount",
        tiers=[
            SlabTier(min_quantity=10, max_quantity=24, discount_percent=Decimal("3.0")),
            SlabTier(min_quantity=25, max_quantity=49, discount_percent=Decimal("5.0")),
            SlabTier(min_quantity=50, max_quantity=None, discount_percent=Decimal("7.0")),
        ],
    )


@pytest.mark.parametrize(
    ("quantity", "expected_pct", "expected_discount", "expected_total"),
    [
        # Below tier 1: 0%
        (1, Decimal("0.00"), Decimal("0.00"), Decimal("1000.00")),
        (9, Decimal("0.00"), Decimal("0.00"), Decimal("9000.00")),
        # Tier 1 exact lower bound: 10 cases @ 3%
        (10, Decimal("3.00"), Decimal("300.00"), Decimal("9700.00")),
        # Tier 1 exact upper bound: 24 cases @ 3%
        (24, Decimal("3.00"), Decimal("720.00"), Decimal("23280.00")),
        # Tier 2 exact lower bound: 25 cases @ 5%
        (25, Decimal("5.00"), Decimal("1250.00"), Decimal("23750.00")),
        # Tier 2 exact upper bound: 49 cases @ 5%
        (49, Decimal("5.00"), Decimal("2450.00"), Decimal("46550.00")),
        # Tier 3 exact lower bound: 50 cases @ 7%
        (50, Decimal("7.00"), Decimal("3500.00"), Decimal("46500.00")),
        # Tier 3 open-ended: 100 cases @ 7%
        (100, Decimal("7.00"), Decimal("7000.00"), Decimal("93000.00")),
    ],
)
def test_slab_discount_threshold_boundaries(
    standard_slab_scheme: SlabDiscountScheme,
    quantity: int,
    expected_pct: Decimal,
    expected_discount: Decimal,
    expected_total: Decimal,
) -> None:
    unit_price = Decimal("1000.00")
    calc = calculate_line(quantity, unit_price, standard_slab_scheme)

    assert calc.subtotal == unit_price * quantity
    assert calc.discount == expected_discount
    assert calc.total == expected_total
    assert calc.discount_percent == expected_pct
    assert calc.free_quantity == 0


def test_slab_tier_finder(standard_slab_scheme: SlabDiscountScheme) -> None:
    assert find_eligible_slab_tier(standard_slab_scheme, 5) is None
    t1 = find_eligible_slab_tier(standard_slab_scheme, 10)
    assert t1 is not None and t1.discount_percent == Decimal("3.0")
    t2 = find_eligible_slab_tier(standard_slab_scheme, 30)
    assert t2 is not None and t2.discount_percent == Decimal("5.0")
    t3 = find_eligible_slab_tier(standard_slab_scheme, 75)
    assert t3 is not None and t3.discount_percent == Decimal("7.0")


# =====================================================================
# 5. Invalid Slab Configuration Validations
# =====================================================================

def test_slab_tier_rejects_max_less_than_min() -> None:
    with pytest.raises(ValueError, match="must be greater than or equal to min_quantity"):
        SlabTier(min_quantity=20, max_quantity=10, discount_percent=Decimal("5"))


def test_slab_scheme_rejects_overlapping_tiers() -> None:
    with pytest.raises(ValueError, match="Overlapping slab tiers detected"):
        SlabDiscountScheme(
            tiers=[
                SlabTier(min_quantity=10, max_quantity=25, discount_percent=Decimal("3")),
                SlabTier(min_quantity=20, max_quantity=40, discount_percent=Decimal("5")),
            ]
        )


def test_slab_scheme_rejects_open_ended_tier_not_at_end() -> None:
    with pytest.raises(ValueError, match="has no upper bound but is followed by another tier"):
        SlabDiscountScheme(
            tiers=[
                SlabTier(min_quantity=10, max_quantity=None, discount_percent=Decimal("3")),
                SlabTier(min_quantity=25, max_quantity=50, discount_percent=Decimal("5")),
            ]
        )


def test_slab_scheme_rejects_invalid_discount_percent() -> None:
    with pytest.raises(ValidationError):
        SlabTier(min_quantity=10, max_quantity=20, discount_percent=Decimal("105"))

    with pytest.raises(ValidationError):
        SlabTier(min_quantity=10, max_quantity=20, discount_percent=Decimal("-5"))


def test_slab_scheme_rejects_empty_tiers() -> None:
    with pytest.raises(ValidationError):
        SlabDiscountScheme(tiers=[])


# =====================================================================
# 6. Scheme Priority and Stacking Policy
# =====================================================================

def test_scheme_priority_selects_higher_priority_scheme() -> None:
    """Scheme with explicit priority wins even if economic benefit is lower."""
    unit_price = Decimal("777.60")
    quantity = 10

    # Rule A: Buy 10 Get 1 Free (benefit = 1 * 777.60 = 777.60, priority=0)
    rule_a = BuyXGetYScheme(
        name="BOGO Scheme",
        buy_quantity=10,
        free_quantity=1,
        priority=0,
    )

    # Rule B: 5+ Cases 3% Off (benefit = 10 * 777.60 * 3% = 233.28, priority=10)
    rule_b = QuantityDiscountScheme(
        name="High Priority Cash Discount",
        minimum_quantity=5,
        discount_percent=Decimal("3"),
        priority=10,
    )

    calc = evaluate_line_schemes(quantity, unit_price, [rule_a, rule_b])

    # Rule B should win because priority 10 > priority 0
    assert calc.free_quantity == 0
    assert calc.discount == Decimal("233.28")
    assert calc.total == (Decimal("7776.00") - Decimal("233.28"))


def test_best_benefit_wins_when_priority_equal_and_non_stackable() -> None:
    """When priority is equal and non-stackable, the higher economic value wins."""
    unit_price = Decimal("777.60")
    quantity = 10

    # Rule A: Buy 10 Get 1 Free (benefit = ₹777.60 free goods)
    rule_a = BuyXGetYScheme(
        name="Free Case",
        buy_quantity=10,
        free_quantity=1,
        priority=0,
        is_stackable=False,
    )

    # Rule B: 5+ cases 3% off (benefit = ₹233.28 discount)
    rule_b = QuantityDiscountScheme(
        name="Volume Discount",
        minimum_quantity=5,
        discount_percent=Decimal("3"),
        priority=0,
        is_stackable=False,
    )

    calc = evaluate_line_schemes(quantity, unit_price, [rule_a, rule_b])

    # ₹777.60 > ₹233.28, so Rule A wins
    assert calc.free_quantity == 1
    assert calc.discount == Decimal("0.00")
    assert calc.delivered_quantity == 11
    assert calc.free_value == Decimal("777.60")


def test_stackable_schemes_combine_benefits_safely() -> None:
    """When both schemes are explicitly stackable, both benefits apply.

    Discount must be applied only to the paid quantity, never to free goods.
    """
    unit_price = Decimal("777.60")
    quantity = 10

    rule_bogo = BuyXGetYScheme(
        name="Stackable BOGO",
        buy_quantity=10,
        free_quantity=1,
        is_stackable=True,
    )
    rule_discount = QuantityDiscountScheme(
        name="Stackable 3% Off",
        minimum_quantity=5,
        discount_percent=Decimal("3.00"),
        is_stackable=True,
    )

    calc = evaluate_line_schemes(quantity, unit_price, [rule_bogo, rule_discount])

    assert calc.paid_quantity == 10
    assert calc.free_quantity == 1
    assert calc.delivered_quantity == 11
    assert calc.subtotal == Decimal("7776.00")
    # Discount applies to paid subtotal (₹7776.00 * 3% = ₹233.28)
    assert calc.discount == Decimal("233.28")
    assert calc.total == Decimal("7542.72")
    assert calc.free_value == Decimal("777.60")


def test_mixed_stackable_and_non_stackable_prevents_accidental_double_benefit() -> None:
    """If one scheme is non-stackable, safe policy picks the best single scheme."""
    unit_price = Decimal("1000.00")
    quantity = 10

    # Rule 1 is stackable, but Rule 2 is NOT
    rule_1 = BuyXGetYScheme(buy_quantity=10, free_quantity=1, is_stackable=True)
    rule_2 = QuantityDiscountScheme(
        minimum_quantity=5,
        discount_percent=Decimal("2.00"),
        is_stackable=False,
    )

    calc = evaluate_line_schemes(quantity, unit_price, [rule_1, rule_2])

    # Rule 1 gives ₹1000 benefit vs Rule 2 gives ₹200 discount
    # They cannot stack because Rule 2 is not stackable. Rule 1 wins!
    assert calc.free_quantity == 1
    assert calc.discount == Decimal("0.00")


# =====================================================================
# 7. Compound / Successive Stacking Tests
# =====================================================================

def test_compound_discount_stacking_sixty_and_fifty_percent() -> None:
    """60% + 50% compound stacking = 80% effective discount.

    For subtotal ₹1,000, payable amount must be ₹200.
    """
    unit_price = Decimal("100.00")
    quantity = 10  # Subtotal = 10 * 100 = 1,000.00
    rule1 = QuantityDiscountScheme(
        name="60% clearance",
        minimum_quantity=1,
        discount_percent=Decimal("60.00"),
        is_stackable=True,
    )
    rule2 = QuantityDiscountScheme(
        name="50% distributor promo",
        minimum_quantity=1,
        discount_percent=Decimal("50.00"),
        is_stackable=True,
    )
    calc = evaluate_line_schemes(quantity, unit_price, [rule1, rule2])

    assert calc.subtotal == Decimal("1000.00")
    assert calc.discount_percent == Decimal("80.00")
    assert calc.discount == Decimal("800.00")
    assert calc.total == Decimal("200.00")
    assert calc.free_quantity == 0


def test_compound_discount_stacking_ten_and_twenty_percent() -> None:
    """10% + 20% compound stacking = 28% effective discount.

    For subtotal ₹1,000, payable amount must be ₹720.
    """
    unit_price = Decimal("100.00")
    quantity = 10  # Subtotal = 1,000.00
    rule1 = QuantityDiscountScheme(
        name="10% volume",
        minimum_quantity=1,
        discount_percent=Decimal("10.00"),
        is_stackable=True,
    )
    rule2 = QuantityDiscountScheme(
        name="20% seasonal",
        minimum_quantity=1,
        discount_percent=Decimal("20.00"),
        is_stackable=True,
    )
    calc = evaluate_line_schemes(quantity, unit_price, [rule1, rule2])

    assert calc.subtotal == Decimal("1000.00")
    assert calc.discount_percent == Decimal("28.00")
    assert calc.discount == Decimal("280.00")
    assert calc.total == Decimal("720.00")


def test_single_stackable_discount_remains_unchanged() -> None:
    """A single stackable discount of 15% should yield exactly 15% discount."""
    unit_price = Decimal("200.00")
    quantity = 5  # Subtotal = 1,000.00
    rule = QuantityDiscountScheme(
        name="15% discount",
        minimum_quantity=5,
        discount_percent=Decimal("15.00"),
        is_stackable=True,
    )
    calc = evaluate_line_schemes(quantity, unit_price, [rule])

    assert calc.subtotal == Decimal("1000.00")
    assert calc.discount_percent == Decimal("15.00")
    assert calc.discount == Decimal("150.00")
    assert calc.total == Decimal("850.00")


def test_zero_percent_discount_stacking() -> None:
    """A 0% tier combined with a 20% stackable discount yields 20% effective discount."""
    unit_price = Decimal("100.00")
    quantity = 5  # Subtotal = 500.00
    rule_slab_zero = SlabDiscountScheme(
        name="Zero tier slab",
        tiers=[
            SlabTier(min_quantity=1, max_quantity=9, discount_percent=Decimal("0.00")),
            SlabTier(min_quantity=10, max_quantity=None, discount_percent=Decimal("5.00")),
        ],
        is_stackable=True,
    )
    rule_twenty = QuantityDiscountScheme(
        name="20% flat promo",
        minimum_quantity=1,
        discount_percent=Decimal("20.00"),
        is_stackable=True,
    )
    calc = evaluate_line_schemes(quantity, unit_price, [rule_slab_zero, rule_twenty])

    assert calc.subtotal == Decimal("500.00")
    assert calc.discount_percent == Decimal("20.00")
    assert calc.discount == Decimal("100.00")
    assert calc.total == Decimal("400.00")


def test_free_goods_combined_with_compound_percentage_discounts() -> None:
    """Free goods (Buy 10 Get 1 Free) combined with compound percentage discounts (10% + 20% = 28%).

    Free goods are separated; discounts are applied only to paid subtotal.
    """
    unit_price = Decimal("100.00")
    quantity = 10  # Subtotal = 10 * 100 = 1,000.00

    bogo = BuyXGetYScheme(
        name="Stackable BOGO",
        buy_quantity=10,
        free_quantity=1,
        is_stackable=True,
    )
    discount1 = QuantityDiscountScheme(
        name="10% trade",
        minimum_quantity=5,
        discount_percent=Decimal("10.00"),
        is_stackable=True,
    )
    discount2 = QuantityDiscountScheme(
        name="20% cash",
        minimum_quantity=5,
        discount_percent=Decimal("20.00"),
        is_stackable=True,
    )

    calc = evaluate_line_schemes(quantity, unit_price, [bogo, discount1, discount2])

    assert calc.paid_quantity == 10
    assert calc.free_quantity == 1
    assert calc.delivered_quantity == 11
    assert calc.subtotal == Decimal("1000.00")
    assert calc.discount_percent == Decimal("28.00")
    assert calc.discount == Decimal("280.00")
    assert calc.total == Decimal("720.00")
    assert calc.free_value == Decimal("100.00")


def test_compound_stacking_payable_never_becomes_negative() -> None:
    """Payable total must never become negative, even under extreme stacked percentages."""
    unit_price = Decimal("500.00")
    quantity = 4

    rule1 = QuantityDiscountScheme(minimum_quantity=1, discount_percent=Decimal("90.00"), is_stackable=True)
    rule2 = QuantityDiscountScheme(minimum_quantity=1, discount_percent=Decimal("90.00"), is_stackable=True)
    rule3 = QuantityDiscountScheme(minimum_quantity=1, discount_percent=Decimal("90.00"), is_stackable=True)

    calc = evaluate_line_schemes(quantity, unit_price, [rule1, rule2, rule3])

    assert calc.discount <= calc.subtotal
    assert calc.total >= Decimal("0.00")
    # Multiplier: 0.10 * 0.10 * 0.10 = 0.001 -> 99.9% effective discount
    assert calc.total == Decimal("2.00")


def test_compound_stacking_rounding_precision() -> None:
    """Ensure decimal precision and ROUND_HALF_UP rounding on fractional percentages."""
    unit_price = Decimal("777.60")
    quantity = 10  # Subtotal = 7,776.00

    rule1 = QuantityDiscountScheme(minimum_quantity=1, discount_percent=Decimal("3.50"), is_stackable=True)
    rule2 = QuantityDiscountScheme(minimum_quantity=1, discount_percent=Decimal("2.25"), is_stackable=True)

    # Multiplier: (1 - 0.035) * (1 - 0.0225) = 0.965 * 0.9775 = 0.9432875
    # Effective discount % = (1 - 0.9432875) * 100 = 5.67125% -> rounded to 5.67%
    calc = evaluate_line_schemes(quantity, unit_price, [rule1, rule2])

    assert calc.subtotal == Decimal("7776.00")
    assert calc.discount_percent == Decimal("5.67")
    # 7776.00 * 5.67 / 100 = 440.8992 -> 440.90
    assert calc.discount == Decimal("440.90")
    assert calc.total == Decimal("7335.10")


# =====================================================================
# 8. Client Sample Data Validation (Section 6)
# =====================================================================

def test_client_sample_product_1_glucose_biscuit() -> None:
    """Product 1: SKU-BS-075 Glucose biscuit 75g (case of 96)

    - Dealer price: ₹8.10 per piece -> ₹777.60 per case
    - Order: 10 cases
    - Scheme: Buy 10 cases, get 1 free
    - Expected: 10 paid cases (960 pieces) + 1 free case (96 pieces) = 11 delivered cases (1056 pieces)
    - Subtotal: ₹7776.00, Free Value: ₹777.60, Total: ₹7776.00
    """
    case_size = 96
    dealer_piece_price = Decimal("8.10")
    unit_price = dealer_piece_price * case_size  # ₹777.60
    assert unit_price == Decimal("777.60")

    ordered_cases = 10
    scheme = BuyXGetYScheme(buy_quantity=10, free_quantity=1)
    calc = calculate_line(ordered_cases, unit_price, scheme)

    assert calc.paid_quantity == 10
    assert calc.free_quantity == 1
    assert calc.delivered_quantity == 11

    # In pieces
    paid_pieces = calc.paid_quantity * case_size
    free_pieces = calc.free_quantity * case_size
    delivered_pieces = calc.delivered_quantity * case_size
    assert paid_pieces == 960
    assert free_pieces == 96
    assert delivered_pieces == 1056

    assert calc.subtotal == Decimal("7776.00")
    assert calc.discount == Decimal("0.00")
    assert calc.free_value == Decimal("777.60")
    assert calc.total == Decimal("7776.00")


def test_client_sample_product_2_detergent_powder() -> None:
    """Product 2: SKU-DP-1KG Detergent powder 1kg (case of 20)

    - Dealer price: ₹101.50 per piece -> ₹2030.00 per case
    - Order: 5 cases (100 pieces)
    - Scheme: 3% off on 5 or more cases
    - Expected: 5 paid cases, 0 free cases, 3% discount
    - Subtotal: 5 * ₹2030.00 = ₹10,150.00
    - Discount: 3% of ₹10,150.00 = ₹304.50
    - Total: ₹10,150.00 - ₹304.50 = ₹9,845.50
    """
    case_size = 20
    dealer_piece_price = Decimal("101.50")
    unit_price = dealer_piece_price * case_size  # ₹2030.00
    assert unit_price == Decimal("2030.00")

    ordered_cases = 5
    scheme = QuantityDiscountScheme(
        minimum_quantity=5,
        discount_percent=Decimal("3.00"),
    )
    calc = calculate_line(ordered_cases, unit_price, scheme)

    assert calc.paid_quantity == 5
    assert calc.free_quantity == 0
    assert calc.delivered_quantity == 5

    # In pieces
    paid_pieces = calc.paid_quantity * case_size
    assert paid_pieces == 100

    assert calc.subtotal == Decimal("10150.00")
    assert calc.discount == Decimal("304.50")
    assert calc.total == Decimal("9845.50")
