# ruff: noqa: E501
"""Material reconciliation and labour contractors' claims.

Per site and bill period: what was issued to the work against what the approved quantity needs
(approved qty x the system's consumption, with its wastage), what went back to the godown, and
the excess (to return with a transfer) or the short. A labour contractor claiming more than was
measured: their claim per area against the approved measurement, with the RFI zone and the
photos; the bill pays the approved quantity, or the claimed one with the director's approval."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.closeout.common import locked, now, unprocessable
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


def periods(db: Session, site: Site) -> list[dict]:
    """The site's bill periods: each RA bill from the day after the previous one's period."""
    from app.finance.models import RaBill  # noqa: PLC0415

    out, prev = [], None
    for b in db.scalars(select(RaBill).where(RaBill.site_id == site.id, RaBill.status != "cancelled", RaBill.period_to.is_not(None)).order_by(RaBill.period_to)):
        start = prev + timedelta(days=1) if prev else None
        out.append({"key": f"ra{b.id}", "label": f"{b.code}: {'from ' + start.strftime('%d.%m.%Y') + ' ' if start else ''}to {b.period_to:%d.%m.%Y}",
                    "start": start, "end": b.period_to + timedelta(days=1)})  # fmt: skip
        prev = b.period_to
    return out


def _site_store(db: Session, site: Site):
    from app.material.models import Store  # noqa: PLC0415

    return db.scalar(select(Store).where(Store.site_id == site.id))


def material(db: Session, site: Site, month: str | None = None, period: str | None = None) -> dict:
    from app.closeout.sizes import unit_code  # noqa: PLC0415
    from app.finance.models import ContractLine  # noqa: PLC0415
    from app.masters.models import Product, System, SystemComponent  # noqa: PLC0415
    from app.material.models import (  # noqa: PLC0415
        SiteIssue,
        SiteIssueLine,
        Store,
        Transfer,
        TransferLine,
    )
    from app.tenders.models import BoqLine  # noqa: PLC0415

    start, end = _period(month)
    plist = periods(db, site)
    label = "the whole site"
    if period:
        p = next((x for x in plist if x["key"] == period), None)
        if p is None:
            raise unprocessable("Unknown bill period")
        start, end, label = p["start"], p["end"], p["label"]
    need: dict[int, Decimal] = {}
    basis: dict[int, list[str]] = {}
    unknown: set[int] = set()  # a line per rmt against a consumption per sqm, its width not given
    widths: dict[int, dict] = {}  # those lines, to give their width once
    q = select(Measurement).where(Measurement.site_id == site.id, Measurement.status == "approved")
    if start:
        q = q.where(Measurement.measured_on >= start)
    if end:
        q = q.where(Measurement.measured_on < end)
    for m in db.scalars(q):
        cl = db.get(ContractLine, m.contract_line_id) if m.contract_line_id else None
        bl = db.get(BoqLine, cl.boq_line_id) if cl and cl.boq_line_id else None
        if bl is None or not bl.system_id:
            continue
        sysm = db.get(System, bl.system_id)
        qty = Decimal(m.qty)
        how = f"{qty:.3f} {m.unit}"
        if sysm is not None and unit_code(m.unit) != unit_code(sysm.unit):
            if unit_code(m.unit) in ("rmt", "rm") and unit_code(sysm.unit) == "sqm":
                widths[cl.id] = {"contract_line_id": cl.id, "description": cl.description, "unit": cl.unit, "width_m": cl.width_m}
                if cl.width_m:
                    qty, how = qty * Decimal(cl.width_m), f"{qty:.3f} {m.unit} x {Decimal(cl.width_m):.3f} m wide"
            if qty == Decimal(m.qty):  # still per rmt: the width is needed first
                for c in db.scalars(select(SystemComponent).where(SystemComponent.system_id == bl.system_id)):
                    unknown.add(c.product_id)
                    basis.setdefault(c.product_id, []).append(f"{how}: the consumption is per {sysm.unit}, give the width")
                continue
        for c in db.scalars(select(SystemComponent).where(SystemComponent.system_id == bl.system_id)):
            if c.consumption_per_unit is None:
                continue
            q_ = qty * Decimal(c.consumption_per_unit) * (1 + Decimal(c.wastage_percent or 0) / 100)
            need[c.product_id] = need.get(c.product_id, Decimal(0)) + q_
            basis.setdefault(c.product_id, []).append(f"{how} x {c.consumption_per_unit} (+{c.wastage_percent or 0} %)")
    # issued to the work (gross) and returned from it into the site store
    iq = select(SiteIssueLine.product_id, SiteIssue.kind, func.sum(SiteIssueLine.qty)).join(SiteIssue, SiteIssue.id == SiteIssueLine.issue_id).where(SiteIssue.site_id == site.id)
    if start:
        iq = iq.where(SiteIssue.issued_on >= start)
    if end:
        iq = iq.where(SiteIssue.issued_on < end)
    issued: dict[int, Decimal] = {}
    returned: dict[int, Decimal] = {}
    for pid, kind, qty_ in db.execute(iq.group_by(SiteIssueLine.product_id, SiteIssue.kind)).all():
        bucket = returned if kind == "return" else issued
        bucket[pid] = bucket.get(pid, Decimal(0)) + Decimal(qty_)
    # sent from the site store back to a godown (the transfers made by "return to godown")
    to_godown: dict[int, Decimal] = {}
    store = _site_store(db, site)
    if store is not None:
        godowns = select(Store.id).where(Store.kind == "godown")
        tq = (select(TransferLine.product_id, func.sum(TransferLine.qty_sent)).join(Transfer, Transfer.id == TransferLine.transfer_id)
              .where(Transfer.from_store_id == store.id, Transfer.to_store_id.in_(godowns), Transfer.status != "cancelled"))  # fmt: skip
        if start:
            tq = tq.where(Transfer.created_at >= start)
        if end:
            tq = tq.where(func.date(Transfer.created_at) < end)
        for pid, qty_ in db.execute(tq.group_by(TransferLine.product_id)).all():
            to_godown[pid] = Decimal(qty_)
    rows = []
    for pid in sorted(set(need) | set(issued) | set(returned) | unknown):
        p = db.get(Product, pid)
        n, i, r, g = (x.get(pid, Decimal(0)).quantize(Q3, ROUND_HALF_UP) for x in (need, issued, returned, to_godown))
        used = i - r
        diff = used - n
        state = "to check" if pid in unknown else "excess" if diff > 0 else "short" if diff < 0 else "even"
        rows.append({"product_id": pid, "product": p.name if p else str(pid), "unit": p.unit if p else "", "issued": i, "returned": r, "net_used": used, "needed": n,
                     "difference": diff, "state": state, "to_godown": g, "note": "to check: give the width" if pid in unknown else None,
                     "basis": basis.get(pid, [])[:6]})  # fmt: skip
    from app.material import service as material_svc  # noqa: PLC0415

    return {"site_id": site.id, "site": f"{site.code} {site.name}", "month": month, "period": label,
            "periods": [{"key": x["key"], "label": x["label"]} for x in plist], "rows": rows, "godown": material_svc.godown(db).name,
            "widths": list(widths.values())}  # fmt: skip


def return_excess(db: Session, site: Site, product_id: int, qty: Decimal, user_id):
    """The excess back from the work into the site store (a site return), then a transfer from
    the site store to the godown, dispatched (stores receive it there)."""
    from app.masters.models import Product  # noqa: PLC0415
    from app.material import service as svc  # noqa: PLC0415
    from app.material.models import (  # noqa: PLC0415
        SiteIssue,
        SiteIssueLine,
        Transfer,
        TransferLine,
    )

    row = next((r for r in material(db, site)["rows"] if r["product_id"] == product_id), None)
    if row is None or row["difference"] <= 0 or row["state"] != "excess":
        raise unprocessable("No excess of that product on this site")
    if qty > row["difference"]:
        raise unprocessable(f"The excess is {row['difference']} {row['unit']}: return at most that")
    p = db.get(Product, product_id)
    store = svc.site_store(db, site, user_id)
    rate = svc.average_rate(db, store.id, p.id)
    back = SiteIssue(code=svc.next_code(db, "ISS"), kind="return", store_id=store.id, site_id=site.id, issued_on=date.today(), remark="Excess from the reconciliation, back to the godown", created_by=user_id)
    db.add(back)
    db.flush()
    svc.post(db, store_id=store.id, product=p, qty=qty, rate=rate, ref_type="return", ref_id=back.id, user_id=user_id, note=back.code)
    back.lines.append(SiteIssueLine(product_id=p.id, product=p, qty=qty, rate=rate, value=svc.money(qty * rate)))
    godown = svc.godown(db)
    t = Transfer(code=svc.next_code(db, "TO"), from_store_id=store.id, to_store_id=godown.id, remark=f"Excess {p.name} from {site.code} (material reconciliation)", created_by=user_id)
    t.lines.append(TransferLine(product_id=p.id, product=p, qty_sent=qty, created_by=user_id))
    db.add(t)
    db.flush()
    for ln in t.lines:
        ln.rate = svc.take_out(db, store=store, product=p, qty=ln.qty_sent, ref_type="transfer_out", ref_id=t.id, user_id=user_id, note=t.code)
    t.status, t.dispatched_at, t.dispatched_by = "dispatched", now(), user_id
    db.flush()
    return t


def claims(db: Session, site: Site, period: str | None = None) -> list[dict]:
    """Each claim against the approved quantity of its area, with the zone and the photos."""
    from app.closeout.measure import zone_of  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    q = select(LabourClaim).where(LabourClaim.site_id == site.id)
    if period:
        q = q.where(LabourClaim.period == period)
    out = []
    name = lambda u: (db.get(User, u).full_name if u and db.get(User, u) else None)  # noqa: E731
    for c in db.scalars(q.order_by(LabourClaim.id)):
        approved, ms = approved_of(db, c)
        node = db.get(SiteNode, c.node_id) if c.node_id else None
        z = zone_of(db, site.id, c.node_id) if c.node_id else None
        out.append({"id": c.id, "contractor": c.contractor, "area": node.name if node else None, "node_id": c.node_id, "claimed": c.claimed_qty, "approved": approved,
                    "excess_claim": max(Decimal(0), Decimal(c.claimed_qty) - approved), "unit": c.unit, "period": c.period,
                    "zone": {"name": z.name, "ours": z.ours, "other": z.other_applicator} if z else None,
                    "photos": sum(len(m.photos or []) for m in ms), "claim_photos": len(c.photos or []), "status": c.status, "decision": c.decision,
                    "decision_reason": c.decision_reason, "decided_by": name(c.decided_by), "director": name(c.director_by), "director_reason": c.director_reason,
                    "pays": c.pay_qty if c.pay_qty is not None else approved, "note": c.note})  # fmt: skip
    return out


def approved_of(db: Session, c: LabourClaim) -> tuple[Decimal, list[Measurement]]:
    mq = select(Measurement).where(Measurement.site_id == c.site_id, Measurement.status == "approved")
    if c.node_id:
        from app.closeout.completion import _with_children  # noqa: PLC0415

        mq = mq.where(Measurement.node_id.in_(_with_children(db, c.site_id, [c.node_id])))
    if c.contract_line_id:
        mq = mq.where(Measurement.contract_line_id == c.contract_line_id)
    ms = list(db.scalars(mq))
    return sum((Decimal(m.qty) for m in ms), Decimal(0)), ms


def decide(db: Session, c: LabourClaim, decision: str, reason: str | None, principal) -> None:
    """Pay the approved quantity; or the claimed one: above the approved quantity it needs a
    reason and the director (a director deciding it approves it at once)."""
    if c.status == "decided":
        raise locked(f"Claim #{c.id} (decided)")
    approved, _ms = approved_of(db, c)
    c.decision, c.decision_reason, c.decided_by, c.decided_at = decision, (reason or "").strip() or None, principal.user.id, now()
    if decision == "approved" or Decimal(c.claimed_qty) <= approved:
        c.pay_qty = min(Decimal(c.claimed_qty), approved) if decision == "approved" else Decimal(c.claimed_qty)
        c.status = "decided"
        return
    if not c.decision_reason:
        raise unprocessable("Paying more than the approved measurement needs the reason")
    if "closeout.claim_approve" in principal.permissions:  # the director: approved at once
        c.director_by, c.director_at, c.director_reason = principal.user.id, now(), c.decision_reason
        c.pay_qty, c.status = Decimal(c.claimed_qty), "decided"
        return
    c.status = "director"
    from app.process import engine  # noqa: PLC0415

    node = db.get(SiteNode, c.node_id) if c.node_id else None
    engine.emit(db, "labour_claim_above", subject=f"claim:{c.id}", site_id=c.site_id, actor_id=principal.user.id,
                data={"contractor": c.contractor, "area": node.name if node else "the site", "claimed": f"{c.claimed_qty}", "approved": f"{approved}", "unit": c.unit or "",
                      "reason": c.decision_reason, "claim_id": c.id})  # fmt: skip


def director(db: Session, c: LabourClaim, approve: bool, reason: str, user_id) -> None:
    if c.status != "director":
        raise unprocessable(f"Claim #{c.id} is not waiting for the director")
    approved, _ms = approved_of(db, c)
    c.director_by, c.director_at, c.director_reason = user_id, now(), reason
    c.pay_qty = Decimal(c.claimed_qty) if approve else approved
    c.decision = "claimed" if approve else "approved"
    c.status = "decided"
    from app.process import engine  # noqa: PLC0415

    engine.emit(db, "labour_claim_decided", subject=f"claim:{c.id}", site_id=c.site_id, actor_id=user_id, data={"claim_id": c.id})
