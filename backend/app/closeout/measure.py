# ruff: noqa: E501  (output shapes read better unwrapped)
"""Measurements the client approves line by line, the RFI zones (what was handed to us), the
billing checklist grid and the quality checklist.

Billing writes each line (L x B, or perimeter x height, less deductions; the drawing or 3D area;
photos) and sends a set to the client's billing role. The client approves a line or corrects a
value (old, new, remark, name and time); our billing accepts the correction or disputes it. A
client that does not use the app: our staff record the approval with the signed sheet. Approved
lines are locked; RA bills and back-to-back labour bills take only approved quantities."""

import re
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.closeout import sizes
from app.closeout.common import locked, now, unprocessable
from app.closeout.models import MeasurementChange, MeasurementSet, RfiZone
from app.sites.models import AreaScope, Site, SiteNode, Task
from app.team.models import Measurement

Q3 = Decimal("0.001")
SIZE_FIELDS = ("length_m", "breadth_m", "perimeter_m", "height_m", "deductions_sqm", "qty")


def qty_of(m: Measurement) -> Decimal:
    """In the line's unit: L x B or perimeter x height for sqm, the running length for rmt, less
    deductions; the typed qty when there are no sizes (or the unit is counted, nos / cum)."""
    return sizes.qty_in(
        m.unit, m.length_m, m.breadth_m, m.perimeter_m, m.height_m, m.deductions_sqm, m.qty
    )


def line_unit(db: Session, contract_line_id: int | None, data: dict, what: str) -> str:
    """The unit of the contract line (the accepted work order's once there is one); a
    measurement in another unit is refused with the reason."""
    from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine  # noqa: PLC0415
    from app.finance.models import ContractLine  # noqa: PLC0415

    cl = db.get(ContractLine, contract_line_id) if contract_line_id else None
    if cl is None:
        return sizes.check_unit(sizes.unit_code(data.get("unit")) or "sqm", data, what, None)
    source = None
    if cl.wo_line_id:
        wl = db.get(ClientWorkOrderLine, cl.wo_line_id)
        wo = db.get(ClientWorkOrder, wl.work_order_id) if wl else None
        source = (wo.client_ref or wo.code) if wo else None
    return sizes.check_unit(cl.unit, data, cl.description, source)


def guard(m: Measurement) -> None:
    if m.status == "approved":
        raise locked(
            f"Measurement #{m.id} (approved{' by ' + m.approved_name if m.approved_name else ''})"
        )


# --- RFI zones ----------------------------------------------------------------------------------


def _ancestors(db: Session, node_id: int | None) -> list[int]:
    out, seen = [], set()
    while node_id and node_id not in seen:
        seen.add(node_id)
        out.append(node_id)
        n = db.get(SiteNode, node_id)
        node_id = n.parent_id if n else None
    return out


def zone_of(db: Session, site_id: int, node_id: int | None) -> RfiZone | None:
    """The zone the place is in (the nearest marked node above it)."""
    zones = {
        z.node_id: z
        for z in db.scalars(
            select(RfiZone).where(RfiZone.site_id == site_id, RfiZone.node_id.is_not(None))
        )
    }
    for nid in _ancestors(db, node_id):
        if nid in zones:
            return zones[nid]
    return None


def in_our_zones(db: Session, site_id: int, node_id: int | None) -> bool | None:
    """True / False, or None when the site has no zones marked (nothing to check)."""
    if not db.scalar(select(RfiZone.id).where(RfiZone.site_id == site_id).limit(1)):
        return None
    z = zone_of(db, site_id, node_id)
    return bool(z and z.ours)


# --- writing and approving ----------------------------------------------------------------------


def write(db: Session, site: Site, data: dict, user) -> tuple[Measurement, str | None]:
    """A measurement line; outside our zones it needs a reason (the warning is returned)."""
    warning = None
    data = sizes.normalise(dict(data))
    unit = line_unit(db, data.get("contract_line_id"), data, data["description"])
    ours = in_our_zones(db, site.id, data.get("node_id"))
    if ours is False:
        z = zone_of(db, site.id, data.get("node_id"))
        warning = f"This place is outside our RFI zones{' (' + z.name + ': ' + (z.other_applicator or 'another applicator') + ')' if z else ''}"
        if not (data.get("zone_reason") or "").strip():
            raise unprocessable(f"{warning}: give the reason to measure it")
    m = Measurement(site_id=site.id, contract_line_id=data.get("contract_line_id"), node_id=data.get("node_id"), cad_area_id=data.get("cad_area_id"),
                    description=data["description"], unit=unit, entered=data.get("entered"), source=data.get("source") or "manual",
                    measured_on=data.get("measured_on") or now().date(), measured_by=user.id, note=data.get("note"),
                    length_m=data.get("length_m"), breadth_m=data.get("breadth_m"), perimeter_m=data.get("perimeter_m"), height_m=data.get("height_m"),
                    deductions_sqm=data.get("deductions_sqm"), qty=data.get("qty") or 0, zone_reason=data.get("zone_reason"),
                    status="draft" if site.measurements_need_approval else "approved", created_by=user.id)  # fmt: skip
    m.qty = qty_of(m)
    db.add(m)
    db.flush()
    return m, warning


def update(db: Session, m: Measurement, data: dict) -> None:
    guard(m)
    if m.status == "sent":
        raise unprocessable("The client has this line: let them approve or correct it")
    data = dict(data)
    if any(f in data for f in sizes.LENGTH_FIELDS):
        data["entered"] = m.entered
        data = sizes.normalise(data)
    merged = {f: getattr(m, f) for f in SIZE_FIELDS} | {
        k: v for k, v in data.items() if k in SIZE_FIELDS
    }
    merged["unit"] = data.get("unit")
    m.unit = line_unit(
        db,
        data.get("contract_line_id", m.contract_line_id),
        merged,
        data.get("description") or m.description,
    )
    for k in (*SIZE_FIELDS, "description", "node_id", "contract_line_id", "note", "entered"):
        if k in data:
            setattr(m, k, data[k])
    m.qty = qty_of(m)


def send(db: Session, site: Site, ids: list[int], title: str | None, user) -> MeasurementSet:
    rows = list(
        db.scalars(
            select(Measurement).where(
                Measurement.site_id == site.id, Measurement.id.in_(ids or [0])
            )
        )
    )
    if not rows:
        raise unprocessable("Pick the measurement lines to send")
    for m in rows:
        if m.status not in ("draft", "disputed"):
            raise unprocessable(f"Line #{m.id} is {m.status}")
    s = MeasurementSet(code=f"MB-{site.code}-{(db.query(MeasurementSet).filter(MeasurementSet.site_id == site.id).count() + 1):02d}",
                       site_id=site.id, title=title, sent_at=now(), sent_by=user.id, created_by=user.id)  # fmt: skip
    db.add(s)
    db.flush()
    for m in rows:
        m.status, m.set_id = "sent", s.id
    from app.portal import service as portal  # noqa: PLC0415

    users = [
        u for u in portal.client_users_of(db, site.id) if _client_can(db, u, "measurement.approve")
    ]
    portal.notify(
        db,
        users,
        "measurements_sent",
        f"{len(rows)} measurement line(s) to approve: {s.code}",
        f"/portal/sites/{site.id}?tab=measurements",
        site.id,
    )
    db.flush()
    return s


def _client_can(db: Session, user_id, right: str) -> bool:
    from app.portal import service as portal  # noqa: PLC0415

    have = portal.rights_of(db, user_id)
    return have is None or right in have


def client_approve(db: Session, m: Measurement, user) -> None:
    guard(m)
    if m.status != "sent":
        raise unprocessable(f"Line #{m.id} is {m.status}: nothing to approve")
    if db.scalar(
        select(MeasurementChange.id).where(
            MeasurementChange.measurement_id == m.id, MeasurementChange.status == "pending"
        )
    ):
        raise unprocessable("A correction on this line waits for our answer")
    m.status, m.approved_at, m.approved_by_user, m.approved_name = (
        "approved",
        now(),
        user.id,
        user.full_name,
    )


def client_correct(
    db: Session, m: Measurement, field: str, new_value, remark: str | None, user
) -> MeasurementChange:
    """The client's correction (20 ft -> 19 ft 5 in): kept with the old value, name and time, in
    the unit the person typed; our billing answers it."""
    guard(m)
    if m.status != "sent":
        raise unprocessable(f"Line #{m.id} is {m.status}")
    if field not in SIZE_FIELDS:
        raise unprocessable(f"Correct one of {', '.join(SIZE_FIELDS)}")
    if field in sizes.LENGTH_FIELDS:
        value, typed = sizes.parse_length(new_value)
    else:
        value, typed = Decimal(str(new_value)), None
    if value is None or value < 0:
        raise unprocessable("Give the correct value")
    c = MeasurementChange(measurement_id=m.id, field=field, old_value=getattr(m, field), new_value=value, remark=remark,
                          old_text=(m.entered or {}).get(field), new_text=typed,
                          by_user=user.id, by_name=user.full_name, side="client", at=now(), status="pending")  # fmt: skip
    db.add(c)
    db.flush()
    return c


def answer(
    db: Session, m: Measurement, c: MeasurementChange, accept: bool, reply: str | None, user
) -> None:
    """Our billing accepts the correction (the line takes the new value and is approved as
    corrected) or disputes it with a reason (the line goes back to the client)."""
    guard(m)
    if c.status != "pending":
        raise unprocessable("Already answered")
    c.replied_by, c.replied_at, c.reply = user.id, now(), reply
    if accept:
        c.status = "accepted"
        setattr(m, c.field, c.new_value)
        entered = dict(m.entered or {})
        if c.new_text:
            entered[c.field] = c.new_text
        else:
            entered.pop(c.field, None)
        m.entered = entered or None
        m.qty = qty_of(m)
        if not db.scalar(
            select(MeasurementChange.id).where(
                MeasurementChange.measurement_id == m.id,
                MeasurementChange.status == "pending",
                MeasurementChange.id != c.id,
            )
        ):
            from app.models import User  # noqa: PLC0415

            u = db.get(User, c.by_user) if c.by_user else None
            m.status, m.approved_at, m.approved_by_user, m.approved_name = (
                "approved",
                now(),
                c.by_user,
                (u.full_name if u else c.by_name),
            )
    else:
        if not (reply or "").strip():
            raise unprocessable("Say why the correction is disputed")
        c.status = "disputed"
        m.status = "sent"  # still the client's to approve, with our reason


def record_approval(
    db: Session, m: Measurement, approved_name: str, on: date | None, copy_path: str | None, user
) -> None:
    """The client signed the paper sheet: our staff record it, with the signed copy."""
    guard(m)
    if not copy_path:
        raise unprocessable("Upload the signed sheet (photo or scan)")
    m.status, m.approved_name, m.recorded_by_staff, m.signed_copy_path = (
        "approved",
        approved_name,
        True,
        copy_path,
    )
    m.approved_at = now() if on is None else now().replace(year=on.year, month=on.month, day=on.day)
    m.approved_by_user = None


def stamp_billed(db: Session, ra) -> int:
    """The approved lines a new RA bill takes (the checklist's "billed in")."""
    ids = [ln.contract_line_id for ln in ra.lines if ln.qty and ln.qty > 0]
    n = 0
    for m in db.scalars(
        select(Measurement).where(
            Measurement.contract_line_id.in_(ids or [0]),
            Measurement.status == "approved",
            Measurement.ra_bill_id.is_(None),
        )
    ):
        m.ra_bill_id = ra.id
        n += 1
    return n


def changes_of(db: Session, m: Measurement, preloaded: dict | None = None) -> list[dict]:
    rows = (
        preloaded.get(m.id, [])
        if preloaded is not None
        else db.scalars(
            select(MeasurementChange)
            .where(MeasurementChange.measurement_id == m.id)
            .order_by(MeasurementChange.id)
        )
    )
    return [{"id": c.id, "field": c.field, "old": c.old_value, "new": c.new_value, "old_text": c.old_text, "new_text": c.new_text,
             "old_shown": sizes.shown(c.old_value, c.old_text) if c.field in sizes.LENGTH_FIELDS else str(c.old_value),
             "new_shown": sizes.shown(c.new_value, c.new_text) if c.field in sizes.LENGTH_FIELDS else str(c.new_value),
             "remark": c.remark, "by": c.by_name, "side": c.side, "at": c.at,
             "status": c.status, "reply": c.reply} for c in rows]  # fmt: skip


def changes_by_measurement(db: Session, ids: list[int]) -> dict[int, list[MeasurementChange]]:
    out: dict[int, list[MeasurementChange]] = {}
    for c in db.scalars(
        select(MeasurementChange)
        .where(MeasurementChange.measurement_id.in_(ids))
        .order_by(MeasurementChange.id)
    ):
        out.setdefault(c.measurement_id, []).append(c)
    return out


def line_out(db: Session, m: Measurement, changes: dict | None = None) -> dict:
    node = db.get(SiteNode, m.node_id) if m.node_id else None
    from app.finance.models import RaBill  # noqa: PLC0415

    ra = db.get(RaBill, m.ra_bill_id) if m.ra_bill_id else None
    return {"id": m.id, "description": m.description, "node_id": m.node_id, "place": node.name if node else None, "contract_line_id": m.contract_line_id,
            "length_m": m.length_m, "breadth_m": m.breadth_m, "perimeter_m": m.perimeter_m, "height_m": m.height_m, "deductions_sqm": m.deductions_sqm,
            "qty": m.qty, "unit": m.unit, "status": m.status, "set_id": m.set_id, "measured_on": m.measured_on, "approved_name": m.approved_name,
            "approved_at": m.approved_at, "recorded_by_staff": m.recorded_by_staff, "entered": m.entered or {},
            "shown": {f: sizes.shown(getattr(m, f), (m.entered or {}).get(f)) for f in sizes.LENGTH_FIELDS if getattr(m, f) is not None}, "zone_reason": m.zone_reason, "photos": len(m.photos or []),
            "billed_in": ra.code if ra else None, "changes": changes_of(db, m, changes)}  # fmt: skip


# --- the billing checklist ------------------------------------------------------------------------


def _children(db: Session, site_id: int) -> dict[int | None, list[SiteNode]]:
    out: dict[int | None, list[SiteNode]] = {}
    for n in db.scalars(
        select(SiteNode)
        .where(SiteNode.site_id == site_id)
        .order_by(SiteNode.sort_order, SiteNode.id)
    ):
        out.setdefault(n.parent_id, []).append(n)
    return out


def _under(kids: dict, node_id: int, kind: str) -> list[SiteNode]:
    out, todo = [], list(kids.get(node_id, []))
    while todo:
        n = todo.pop(0)
        if n.kind == kind:
            out.append(n)
        else:
            todo = kids.get(n.id, []) + todo
    return out


def _col(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().title()


def checklist(db: Session, site: Site, tower_id: int, month: str | None = None) -> dict:
    """Per tower: flats (rows) by area (columns); each cell from the zones, the handover, the
    stages, the measurement book and the bills. A month shows what each bill of that month took."""
    from app.finance.models import RaBill  # noqa: PLC0415

    kids = _children(db, site.id)
    flats = _under(kids, tower_id, "flat")
    cols: list[str] = []
    rows = []
    for f in flats:
        cells = {}
        for a in kids.get(f.id, []):
            col = _col(a.name)
            if col not in cols:
                cols.append(col)
            cells[col] = cell(db, site, a, month, RaBill)
        rows.append({"flat_id": f.id, "flat": f.name, "cells": cells})
    counts: dict[str, int] = {}
    for r in rows:
        for c in r["cells"].values():
            counts[c["status"]] = counts.get(c["status"], 0) + 1
    tower = db.get(SiteNode, tower_id)
    return {
        "site_id": site.id,
        "tower": tower.name if tower else None,
        "columns": cols,
        "rows": rows,
        "counts": counts,
        "month": month,
    }


def cell(db: Session, site: Site, a: SiteNode, month: str | None, RaBill) -> dict:  # noqa: N803
    z = zone_of(db, site.id, a.id)
    has_zones = db.scalar(select(RfiZone.id).where(RfiZone.site_id == site.id).limit(1)) is not None
    if has_zones and not (z and z.ours):
        return {
            "node_id": a.id,
            "status": "not_ours",
            "label": f"not ours{' (' + z.other_applicator + ')' if z and z.other_applicator else ''}",
        }
    ms = list(db.scalars(select(Measurement).where(Measurement.node_id == a.id)))
    billed = [m for m in ms if m.ra_bill_id]
    if billed:
        ra = db.get(RaBill, billed[0].ra_bill_id)
        if month is None or (ra and ra.period_to and ra.period_to.strftime("%Y-%m") == month):
            return {
                "node_id": a.id,
                "status": "billed",
                "label": f"billed in {ra.code if ra else '?'}",
                "bill": ra.code if ra else None,
            }
    if any(m.status == "approved" for m in ms):
        return {"node_id": a.id, "status": "approved", "label": "approved"}
    if ms:
        return {"node_id": a.id, "status": "measured", "label": "measured"}
    scopes = list(db.scalars(select(AreaScope).where(AreaScope.node_id == a.id)))
    if scopes and all(Decimal(s.progress_percent) >= 100 for s in scopes):
        return {"node_id": a.id, "status": "done", "label": "done"}
    if scopes and any(Decimal(s.progress_percent) > 0 for s in scopes):
        return {"node_id": a.id, "status": "in_progress", "label": "in progress"}
    handed = any(
        getattr(db.get(SiteNode, nid), "handover_status", None) == "received"
        for nid in _ancestors(db, a.id)
    )
    if not handed:
        return {"node_id": a.id, "status": "waiting_handover", "label": "waiting for handover"}
    return {"node_id": a.id, "status": "to_start", "label": "handed over, to start"}


# --- the quality checklist ------------------------------------------------------------------------


def quality(db: Session, site: Site, node_id: int) -> list[dict]:
    """Per area: each stage with its start and end dates, our sign and the client's."""
    from app.execution.models import Inspection  # noqa: PLC0415
    from app.models import User  # noqa: PLC0415

    out = []
    for scope in db.scalars(
        select(AreaScope).where(AreaScope.site_id == site.id, AreaScope.node_id == node_id)
    ):
        for t in db.scalars(
            select(Task)
            .where(Task.area_scope_id == scope.id, Task.parent_task_id.is_(None))
            .order_by(Task.sort_order)
        ):
            i = db.scalars(
                select(Inspection).where(Inspection.task_id == t.id).order_by(Inspection.id.desc())
            ).first()
            by = db.get(User, i.inspected_by) if i and i.inspected_by else None
            out.append({"stage": t.name, "task_id": t.id, "status": t.status, "started_on": (i.stage_started_on if i and i.stage_started_on else t.actual_start),
                        "ended_on": (i.stage_ended_on if i and i.stage_ended_on else t.actual_end), "inspection_id": i.id if i else None,
                        "our_sign": by.full_name if by else None, "result": i.result if i else None,
                        "client_sign": (i.client_signed_name if i and i.client_signoff == "signed" else None), "client_signoff": i.client_signoff if i else None,
                        "recorded_by_staff": bool(i and i.client_recorded_by_staff)})  # fmt: skip
    return out
