# ruff: noqa: E501
"""Material reconciliation and labour contractors' claims.

Per site and bill period: what was issued to the site against what the approved quantity needs
(approved qty x the system's consumption, with its wastage): the excess (to return to the godown
as a transfer) or the short. A labour contractor claiming more than was measured: their claim per
area against the approved measurement, with the RFI zone and the photos; the labour bill pays the
approved quantity."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.closeout.models import LabourClaim
from app.sites.models import Site, SiteNode
from app.team.models import Measurement

Q3 = Decimal("0.001")


def _period(month: str | None) -> tuple[date | None, date | None]:
    if not month:
        return None, None
    y, m = (int(x) for x in month.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), (m % 12) + 1, 1)
    return start, end


def material(db: Session, site: Site, month: str | None = None) -> dict:
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.masters.models import Product, SystemComponent  # noqa: PLC0415
    from app.material.models import SiteIssue, SiteIssueLine  # noqa: PLC0415
    from app.tenders.models import BoqLine  # noqa: PLC0415

    start, end = _period(month)
    need: dict[int, Decimal] = {}
    basis: dict[int, list[str]] = {}
    q = select(Measurement).where(Measurement.site_id == site.id, Measurement.status == "approved")
    if start:
        q = q.where(Measurement.measured_on >= start, Measurement.measured_on < end)
    for m in db.scalars(q):
        cl = db.get(ContractLine, m.contract_line_id) if m.contract_line_id else None
        bl = db.get(BoqLine, cl.boq_line_id) if cl and cl.boq_line_id else None
        if bl is None or not bl.system_id:
            continue
        for c in db.scalars(
            select(SystemComponent).where(SystemComponent.system_id == bl.system_id)
        ):
            if c.consumption_per_unit is None:
                continue
            q_ = (
                Decimal(m.qty)
                * Decimal(c.consumption_per_unit)
                * (1 + Decimal(c.wastage_percent or 0) / 100)
            )
            need[c.product_id] = need.get(c.product_id, Decimal(0)) + q_
            basis.setdefault(c.product_id, []).append(
                f"{Decimal(m.qty):.2f} {m.unit} x {c.consumption_per_unit}"
            )
    iq = (
        select(SiteIssueLine.product_id, SiteIssue.kind, func.sum(SiteIssueLine.qty))
        .join(SiteIssue, SiteIssue.id == SiteIssueLine.issue_id)
        .where(SiteIssue.site_id == site.id)
    )
    if start:
        iq = iq.where(SiteIssue.issued_on >= start, SiteIssue.issued_on < end)
    issued: dict[int, Decimal] = {}
    for pid, kind, qty in db.execute(iq.group_by(SiteIssueLine.product_id, SiteIssue.kind)).all():
        issued[pid] = issued.get(pid, Decimal(0)) + (
            Decimal(qty) if kind != "return" else -Decimal(qty)
        )
    rows = []
    for pid in sorted(set(need) | set(issued)):
        p = db.get(Product, pid)
        n, i = (
            need.get(pid, Decimal(0)).quantize(Q3, ROUND_HALF_UP),
            issued.get(pid, Decimal(0)).quantize(Q3, ROUND_HALF_UP),
        )
        diff = i - n
        rows.append({"product_id": pid, "product": p.name if p else str(pid), "unit": p.unit if p else "", "issued": i, "needed": n, "difference": diff,
                     "state": "excess" if diff > 0 else "short" if diff < 0 else "even", "basis": basis.get(pid, [])[:6]})  # fmt: skip
    return {
        "site_id": site.id,
        "month": month,
        "rows": rows,
        "return_hint": "Return the excess to the godown with a transfer (Material > Transfers)",
    }


def claims(db: Session, site: Site, period: str | None = None) -> list[dict]:
    """Each claim against the approved quantity of its area, with the zone and the photos."""
    from app.closeout.measure import zone_of  # noqa: PLC0415

    q = select(LabourClaim).where(LabourClaim.site_id == site.id)
    if period:
        q = q.where(LabourClaim.period == period)
    out = []
    for c in db.scalars(q.order_by(LabourClaim.id)):
        mq = select(Measurement).where(
            Measurement.site_id == site.id, Measurement.status == "approved"
        )
        if c.node_id:
            mq = mq.where(Measurement.node_id == c.node_id)
        if c.contract_line_id:
            mq = mq.where(Measurement.contract_line_id == c.contract_line_id)
        ms = list(db.scalars(mq))
        approved = sum((Decimal(m.qty) for m in ms), Decimal(0))
        node = db.get(SiteNode, c.node_id) if c.node_id else None
        z = zone_of(db, site.id, c.node_id) if c.node_id else None
        out.append({"id": c.id, "contractor": c.contractor, "area": node.name if node else None, "node_id": c.node_id, "claimed": c.claimed_qty, "approved": approved,
                    "excess_claim": max(Decimal(0), Decimal(c.claimed_qty) - approved), "unit": c.unit, "period": c.period,
                    "zone": {"name": z.name, "ours": z.ours, "other": z.other_applicator} if z else None,
                    "photos": sum(len(m.photos or []) for m in ms), "pays": approved, "note": c.note})  # fmt: skip
    return out
