"""The margin rule, the one place it is written: a margin is on the SELLING price,
rate = cost ÷ (1 − m/100), so a 25 % margin on a cost of 100 is a rate of 133.33 (25 % of the rate).
A margin of 100 % or more has no rate and is refused. A rate working saved on the cost basis keeps
it (cost × (1 + m/100)); nothing else uses that basis.

Used by the rate build-up (masters.rate), the tender BOQ (tenders.pricing) and the rate working
(costing.working). Round only the final figure, half up to paise (the callers' money())."""

from decimal import Decimal

HUNDRED = Decimal(100)


class MarginTooHigh(ValueError):
    """A margin on the selling price of 100 % or more."""

    def __init__(self, margin_percent: Decimal):
        super().__init__(
            f"A margin of {margin_percent}% is not possible: it is on the selling price, "
            "so it must be below 100%"
        )


def with_margin(cost: Decimal, margin_percent: Decimal, basis: str = "selling") -> Decimal | None:
    """The rate before rounding: on the selling price cost ÷ (1 − m); on cost (a working saved
    that way) cost × (1 + m). None for a selling margin of 100 % or more."""
    m = Decimal(margin_percent) / HUNDRED
    if basis == "selling":
        return None if m >= 1 else Decimal(cost) / (1 - m)
    return Decimal(cost) * (1 + m)


def selling_rate(cost: Decimal, margin_percent: Decimal) -> Decimal:
    """cost ÷ (1 − m/100), unrounded; raises MarginTooHigh for 100 % or more."""
    rate = with_margin(cost, margin_percent, "selling")
    if rate is None:
        raise MarginTooHigh(margin_percent)
    return rate
