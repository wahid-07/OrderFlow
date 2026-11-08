"""OrderFlow Scheme Engine.

This module provides the core calculation logic for FMCG distributor trade schemes,
including:
1. Buy X Get Y Free (free goods in integer multiples of buy_quantity).
2. Quantity Discount (percentage off when quantity reaches a minimum threshold).
3. Slab Discount (tiered percentage discounts based on order quantity brackets).

Evaluation and Stacking Policy:
- Single scheme rule:
  Calculates the benefit (free goods or percentage discount) directly.
- Multiple candidate schemes for a line:
  1. Filters to schemes eligible for the requested quantity.
  2. If all eligible schemes have `is_stackable=True`, they stack deterministically:
     - Free goods are calculated first.
     - Percentage discounts apply only to the paid quantity subtotal (never to free items).
  3. If any eligible scheme is non-stackable (`is_stackable=False`, safe default):
     - Highest explicit `priority` wins.
     - When priority is equal, the scheme yielding the highest net economic benefit
       (discount amount + free goods value) wins.
     - Competing discounts or duplicate free goods are never applied.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Sequence

from pydantic import BaseModel, Field, model_validator

MONEY = Decimal("0.01")


class BuyXGetYScheme(BaseModel):
    """Buy X cases and receive Y cases free for every full multiple of X."""

    type: Literal["buy_x_get_y"] = "buy_x_get_y"
    buy_quantity: int = Field(gt=0, description="Minimum paid quantity required per free unit")
    free_quantity: int = Field(gt=0, description="Free units received per full multiple")
    priority: int = Field(default=0, description="Higher number takes precedence")
    is_stackable: bool = Field(default=False, description="Whether this scheme can stack with others")
    name: str = Field(default="", description="Display name of the scheme")


class QuantityDiscountScheme(BaseModel):
    """Flat percentage discount once quantity meets or exceeds minimum threshold."""

    type: Literal["quantity_discount"] = "quantity_discount"
    minimum_quantity: int = Field(gt=0, description="Minimum quantity to unlock the discount")
    discount_percent: Decimal = Field(gt=0, le=100, description="Percentage discount (0-100)")
    priority: int = Field(default=0, description="Higher number takes precedence")
    is_stackable: bool = Field(default=False, description="Whether this scheme can stack with others")
    name: str = Field(default="", description="Display name of the scheme")


class SlabTier(BaseModel):
    """A single tier within a slab discount scheme."""

    min_quantity: int = Field(ge=1, description="Minimum quantity (inclusive) for this tier")
    max_quantity: int | None = Field(
        default=None,
        ge=1,
        description="Maximum quantity (inclusive). None indicates no upper bound (e.g. 50+).",
    )
    discount_percent: Decimal = Field(ge=0, le=100, description="Discount percentage for this tier")

    @model_validator(mode="after")
    def validate_range(self) -> "SlabTier":
        if self.max_quantity is not None and self.max_quantity < self.min_quantity:
            raise ValueError(
                f"max_quantity ({self.max_quantity}) must be greater than or equal to min_quantity ({self.min_quantity})"
            )
        return self


class SlabDiscountScheme(BaseModel):
    """Configurable tiered quantity discount scheme with multiple brackets."""

    type: Literal["slab_discount"] = "slab_discount"
    tiers: list[SlabTier] = Field(min_length=1, description="List of non-overlapping slab tiers")
    priority: int = Field(default=0, description="Higher number takes precedence")
    is_stackable: bool = Field(default=False, description="Whether this scheme can stack with others")
    name: str = Field(default="", description="Display name of the scheme")

    @model_validator(mode="after")
    def validate_tiers(self) -> "SlabDiscountScheme":
        sorted_tiers = sorted(self.tiers, key=lambda t: t.min_quantity)
        for i in range(len(sorted_tiers) - 1):
            curr_tier = sorted_tiers[i]
            next_tier = sorted_tiers[i + 1]

            if curr_tier.max_quantity is None:
                raise ValueError(
                    f"Tier with min_quantity={curr_tier.min_quantity} has no upper bound but is followed by another tier"
                )

            if next_tier.min_quantity <= curr_tier.max_quantity:
                raise ValueError(
                    f"Overlapping slab tiers detected: [{curr_tier.min_quantity}, {curr_tier.max_quantity}] "
                    f"and [{next_tier.min_quantity}, {next_tier.max_quantity}]"
                )
        return self


SchemeRule = BuyXGetYScheme | QuantityDiscountScheme | SlabDiscountScheme


def find_eligible_slab_tier(scheme: SlabDiscountScheme, quantity: int) -> SlabTier | None:
    """Find the highest eligible slab tier for the given quantity."""
    for tier in sorted(scheme.tiers, key=lambda t: t.min_quantity, reverse=True):
        if quantity >= tier.min_quantity:
            if tier.max_quantity is None or quantity <= tier.max_quantity:
                return tier
    return None


@dataclass(frozen=True)
class LineCalculation:
    """Complete calculation breakdown for an order line item."""

    requested_quantity: int
    paid_quantity: int
    free_quantity: int
    delivered_quantity: int
    unit_price: Decimal
    subtotal: Decimal
    discount: Decimal
    free_value: Decimal
    total: Decimal
    discount_percent: Decimal = Decimal("0.00")
    scheme_label: str | None = None
    applied_schemes: tuple[str, ...] = ()


def _calculate_single_rule(
    quantity: int,
    unit_price: Decimal,
    rule: SchemeRule | None,
) -> LineCalculation:
    """Calculate line item figures against a single scheme rule."""
    subtotal = (unit_price * quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
    free_quantity = 0
    discount = Decimal("0.00")
    discount_percent = Decimal("0.00")
    scheme_label = None

    if isinstance(rule, BuyXGetYScheme):
        free_quantity = (quantity // rule.buy_quantity) * rule.free_quantity
        if free_quantity > 0:
            scheme_label = f"{rule.buy_quantity}+ cases → {rule.free_quantity} free"
    elif isinstance(rule, QuantityDiscountScheme):
        if quantity >= rule.minimum_quantity:
            discount_percent = rule.discount_percent
            discount = (subtotal * discount_percent / Decimal("100")).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )
            pct_str = format(discount_percent.normalize(), "f")
            scheme_label = f"{rule.minimum_quantity}+ cases → {pct_str}% off"
    elif isinstance(rule, SlabDiscountScheme):
        tier = find_eligible_slab_tier(rule, quantity)
        if tier is not None and tier.discount_percent > 0:
            discount_percent = tier.discount_percent
            discount = (subtotal * discount_percent / Decimal("100")).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )
            pct_str = format(discount_percent.normalize(), "f")
            if tier.max_quantity:
                scheme_label = f"{tier.min_quantity}–{tier.max_quantity} cases → {pct_str}% off"
            else:
                scheme_label = f"{tier.min_quantity}+ cases → {pct_str}% off"

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
        discount_percent=discount_percent,
        scheme_label=scheme_label,
        applied_schemes=(rule.name,) if rule and rule.name and scheme_label else (),
    )


def evaluate_line_schemes(
    quantity: int,
    unit_price: Decimal,
    rules: Sequence[SchemeRule],
) -> LineCalculation:
    """Evaluate multiple candidate schemes for a line item using the priority & stacking policy."""
    if not rules:
        return _calculate_single_rule(quantity, unit_price, None)

    # 1. Calculate each rule individually to determine eligibility and individual benefits
    candidates: list[tuple[SchemeRule, LineCalculation]] = []
    for rule in rules:
        calc = _calculate_single_rule(quantity, unit_price, rule)
        # Rule is eligible if it provides any free goods or discount
        if calc.free_quantity > 0 or calc.discount > Decimal("0.00"):
            candidates.append((rule, calc))

    if not candidates:
        # None of the rules met their qualification thresholds
        return _calculate_single_rule(quantity, unit_price, None)

    if len(candidates) == 1:
        return candidates[0][1]

    # 2. Check if ALL eligible schemes are marked stackable
    all_stackable = all(rule.is_stackable for rule, _ in candidates)

    if all_stackable:
        # Combine benefits deterministically:
        # - Sum free quantities from BuyXGetY schemes
        # - Compound percentage discounts from discount schemes applied to paid subtotal:
        #   remaining_multiplier = (1 - d1/100) * (1 - d2/100) * ...
        #   effective_discount_pct = (1 - remaining_multiplier) * 100
        subtotal = (unit_price * quantity).quantize(MONEY, rounding=ROUND_HALF_UP)
        total_free_qty = 0
        remaining_multiplier = Decimal("1.0")
        has_percentage_discount = False
        labels: list[str] = []
        applied_names: list[str] = []

        for rule, calc in candidates:
            if calc.free_quantity > 0:
                total_free_qty += calc.free_quantity
            if calc.discount_percent > Decimal("0.00"):
                has_percentage_discount = True
                factor = Decimal("1.0") - (calc.discount_percent / Decimal("100.0"))
                remaining_multiplier *= factor
            if calc.scheme_label:
                labels.append(calc.scheme_label)
            if rule.name:
                applied_names.append(rule.name)

        if has_percentage_discount:
            # Bound multiplier safely between 0.0 and 1.0
            remaining_multiplier = max(Decimal("0.0"), min(Decimal("1.0"), remaining_multiplier))
            effective_discount_pct = (
                (Decimal("1.0") - remaining_multiplier) * Decimal("100.0")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            discount = (subtotal * effective_discount_pct / Decimal("100.0")).quantize(
                MONEY,
                rounding=ROUND_HALF_UP,
            )
            # Guarantee discount never exceeds subtotal
            discount = min(discount, subtotal)
        else:
            effective_discount_pct = Decimal("0.00")
            discount = Decimal("0.00")

        free_value = (unit_price * total_free_qty).quantize(MONEY, rounding=ROUND_HALF_UP)

        return LineCalculation(
            requested_quantity=quantity,
            paid_quantity=quantity,
            free_quantity=total_free_qty,
            delivered_quantity=quantity + total_free_qty,
            unit_price=unit_price,
            subtotal=subtotal,
            discount=discount,
            free_value=free_value,
            total=subtotal - discount,
            discount_percent=effective_discount_pct,
            scheme_label=" + ".join(labels) if labels else None,
            applied_schemes=tuple(applied_names),
        )

    # 3. Non-stackable: select the single best rule by priority and net economic benefit
    # First, filter by highest priority
    max_priority = max(rule.priority for rule, _ in candidates)
    priority_candidates = [
        (rule, calc) for rule, calc in candidates if rule.priority == max_priority
    ]

    if len(priority_candidates) == 1:
        return priority_candidates[0][1]

    # Compare total economic benefit: discount + free_value
    def benefit_key(item: tuple[SchemeRule, LineCalculation]) -> tuple[Decimal, Decimal, str]:
        rule, calc = item
        total_benefit = calc.discount + calc.free_value
        # Tie-breaker 1: prefer cash discount over free goods
        # Tie-breaker 2: deterministic by rule type and name
        return (total_benefit, calc.discount, f"{rule.type}:{rule.name}")

    best_rule, best_calc = max(priority_candidates, key=benefit_key)
    return best_calc


def calculate_line(
    quantity: int,
    unit_price: Decimal,
    rule: SchemeRule | Sequence[SchemeRule] | None,
) -> LineCalculation:
    """Calculate order line totals and scheme benefits.

    Supports:
    - rule=None: Standard line calculation without scheme.
    - rule=SchemeRule: Evaluates a single scheme rule.
    - rule=Sequence[SchemeRule]: Evaluates multiple candidate schemes via priority & stacking.
    """
    if quantity <= 0:
        raise ValueError("quantity must be greater than zero")
    if unit_price < 0:
        raise ValueError("unit_price cannot be negative")

    if rule is None:
        return _calculate_single_rule(quantity, unit_price, None)

    if isinstance(rule, Sequence) and not isinstance(rule, (str, bytes)):
        return evaluate_line_schemes(quantity, unit_price, rule)

    return _calculate_single_rule(quantity, unit_price, rule)
