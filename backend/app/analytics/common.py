"""Shared bits of the dashboards and analytics: filters, periods, permission checks."""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, status

from app.auth.deps import CurrentPrincipal, Principal
from app.execution.service import IST
from app.execution.service import today as _today

ZERO = Decimal(0)
OPEN_LEAD = ("new", "contacted", "site_visit", "quoted")
SIZE_BANDS = (
    (Decimal(1_000_000), "< ₹10 L"),
    (Decimal(5_000_000), "₹10–50 L"),
    (Decimal(20_000_000), "₹50 L–2 Cr"),
    (None, "> ₹2 Cr"),
)


def today() -> date:
    return _today()


def now() -> datetime:
    return datetime.now(UTC)


def money(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), ROUND_HALF_UP)


def pct(part, whole, places: str = "0.1") -> Decimal | None:
    part, whole = Decimal(part or 0), Decimal(whole or 0)
    return (part / whole * 100).quantize(Decimal(places), ROUND_HALF_UP) if whole else None


def inr_compact(value) -> str:
    """Compact Indian money for tiles: ₹29.49 Cr, ₹7.89 L, ₹72,228 (exact figures elsewhere)."""
    if value is None or value == "":
        return "—"
    v = Decimal(str(value))
    sign, a = ("-" if v < 0 else ""), abs(v)
    if a >= 10_000_000:
        return f"{sign}₹{a / 10_000_000:.2f} Cr"
    if a >= 100_000:
        return f"{sign}₹{a / 100_000:.2f} L"
    whole = str(int(a.quantize(Decimal(1), ROUND_HALF_UP)))
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join([head, *groups, tail])
    return f"{sign}₹{whole}"


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def month_end(d: date) -> date:
    return add_months(d, 1) - timedelta(days=1)


def quarter_start(d: date) -> date:
    return date(d.year, (d.month - 1) // 3 * 3 + 1, 1)


def ist_day(dt: datetime) -> date:
    return dt.astimezone(IST).date()


def size_band(value) -> str:
    v = Decimal(value or 0)
    for limit, label in SIZE_BANDS:
        if limit is None or v < limit:
            return label
    return SIZE_BANDS[-1][1]


@dataclass
class Filters:
    date_from: date
    date_to: date
    region: str | None = None
    salesperson: uuid.UUID | None = None
    client_type: str | None = None
    site_status: str | None = None
    demo: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {k: (str(v) if v is not None else None) for k, v in vars(self).items()}


def filters(
    date_from: date | None = None,
    date_to: date | None = None,
    region: Annotated[str | None, Query(max_length=100)] = None,
    salesperson: uuid.UUID | None = None,
    client_type: Annotated[str | None, Query(max_length=20)] = None,
    site_status: Annotated[str | None, Query(max_length=12)] = None,
    demo: bool = False,
) -> Filters:
    """Default range: the last 12 months, this one included."""
    end = date_to or today()
    start = date_from or add_months(month_start(end), -11)
    if start > end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The range ends before it starts")
    return Filters(
        start, end, region or None, salesperson, client_type or None, site_status or None, demo
    )


Filtered = Annotated[Filters, Depends(filters)]


def need_any(principal: Principal, *codes: str) -> str:
    """The widest scope the caller holds among `codes`; 403 without any."""
    from app.auth.rbac import widest

    scope = None
    for c in codes:
        scope = widest(scope, principal.permissions.get(c))
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Missing permission: {' or '.join(codes)}")
    return scope


def sees_cost(principal: Principal) -> bool:
    return "tender.margin" in principal.permissions


def sees_salary(principal: Principal) -> bool:
    return "payroll.view" in principal.permissions


def cost_or_403(principal: Principal) -> None:
    if not sees_cost(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cost and margin need tender.margin")


def months(start: date, end: date) -> list[date]:
    out, m = [], month_start(start)
    while m <= end:
        out.append(m)
        m = add_months(m, 1)
    return out


__all__ = ["CurrentPrincipal", "Filtered", "Filters", "ZERO", "timedelta"]
