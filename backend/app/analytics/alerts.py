# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Alerts: rules the worker checks every hour. Each fires at most once per item per day, goes to
the rule's roles (plus the site in-charge, or the item's owner), lands in the in-app bell (M6
notifications and their in_app outbox) and stays on the Alerts page until acknowledged. An item
acknowledged is not raised again for `ack_snooze_days`. Nothing is sent outside the app. Demo data
never raises alerts."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.analytics.common import ist_day, now, today
from app.analytics.kpi import dpr_missing_today, stock_levels
from app.analytics.models import ALERT_RULES, RULE_LABELS, Alert, AlertRecipient, SiteSummary
from app.analytics.summary import is_delayed, settings
from app.crm.models import KylasOutbox, Lead
from app.execution import service as ex
from app.execution.models import BUDGET_HEADS, SiteBudget
from app.finance import service as fsvc
from app.finance.models import PettyCashAccount, PettyCashEntry, TaxInvoice
from app.masters.models import Vendor
from app.material.models import PurchaseOrder
from app.models import Role, User, UserRole
from app.portal import service as portal
from app.sites.models import Site
from app.tenders.models import Tender


@dataclass
class Hit:
    item_key: str
    title: str
    link: str | None = None
    site_id: int | None = None
    users: list = field(default_factory=list)  # besides the rule's roles
    severity: str = "warn"


def rules(db: Session) -> dict[str, dict]:
    stored = settings(db).alert_rules or {}
    return {k: {**v, **(stored.get(k) or {})} for k, v in ALERT_RULES.items()}


def role_users(db: Session, roles: list[str]) -> list:
    return list(
        db.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(Role.code.in_(roles or ["-"]), User.is_active, User.is_demo.is_(False))
        )
    )


# --- the rules -----------------------------------------------------------------------------------


def _dpr_missing(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    if at.astimezone(ex.IST).hour < int(cfg.get("after_hour", 20)):
        return
    for s in dpr_missing_today(db, demo=False):
        yield Hit(
            f"site:{s.id}",
            f"{s.code}: no DPR submitted for today",
            f"/sites/{s.id}?tab=dpr",
            s.id,
            [s.site_incharge_id],
        )


def _behind_schedule(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    threshold = settings(db).delay_threshold_points
    for s in db.scalars(select(Site).where(Site.status == "active", Site.is_demo.is_(False))):
        why = is_delayed(
            s.status, s.progress_percent, s.start_date, s.target_date, today(), threshold
        )
        if why:
            yield Hit(
                f"site:{s.id}",
                f"{s.code} is behind schedule ({why}, {s.progress_percent:.0f}% done)",
                f"/sites/{s.id}",
                s.id,
                [s.site_incharge_id],
            )


def _budget_head(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    limit = Decimal(str(cfg.get("percent", 90)))
    with_budget = select(SiteBudget.site_id).distinct()
    q = select(Site).where(
        Site.status.in_(("active", "on_hold")),
        Site.is_demo.is_(False),
        (Site.id.in_(with_budget)) | Site.tender_id.is_not(None),
    )
    for s in db.scalars(q):
        budget = {
            b.head: Decimal(b.amount)
            for b in db.scalars(select(SiteBudget).where(SiteBudget.site_id == s.id))
        }
        for head, amount in ex.tender_budget(db, s).items():
            budget.setdefault(head, amount)
        if not budget:
            continue
        actual = ex.actuals(db, s.id)
        for head in BUDGET_HEADS:
            b = budget.get(head)
            if b and b > 0 and actual[head] >= b * limit / 100:
                used = (actual[head] / b * 100).quantize(Decimal("1"))
                yield Hit(
                    f"site:{s.id}:{head}",
                    f"{s.code}: {head} cost at {used}% of its budget",
                    f"/sites/{s.id}?tab=budget",
                    s.id,
                    [s.site_incharge_id],
                    "high" if used >= 100 else "warn",
                )


def _invoice_overdue(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    day = today()
    steps = sorted(int(d) for d in cfg.get("days", [30, 60, 90]))
    for inv in db.scalars(
        select(TaxInvoice)
        .join(TaxInvoice.client)
        .where(
            TaxInvoice.kind == "invoice", TaxInvoice.status == "issued", TaxInvoice.due_date < day
        )
    ):
        if inv.client.is_demo:
            continue
        late = (day - inv.due_date).days
        crossed = [d for d in steps if late >= d]
        if not crossed or fsvc.outstanding(db, inv) <= 0:
            continue
        bucket = crossed[-1]
        yield Hit(
            f"invoice:{inv.id}:{bucket}",
            f"Invoice {inv.number} ({inv.client.name}) overdue {late} days",
            f"/drill?kind=invoices&filter=overdue&days={bucket}",
            inv.site_id,
            [],
            "high" if bucket >= 90 else "warn",
        )


def _po_late(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    for po, name in db.execute(
        select(PurchaseOrder, Vendor.name)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .where(
            PurchaseOrder.status.in_(("approved", "sent", "partly_received")),
            PurchaseOrder.expected_delivery < today(),
            Vendor.is_demo.is_(False),
        )
    ):
        yield Hit(
            f"po:{po.id}",
            f"{po.code} from {name} was due on {po.expected_delivery:%d %b}",
            f"/purchase-orders/{po.id}",
        )


def _low_stock(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    for r in stock_levels(db, demo=False):
        if r["low"]:
            yield Hit(
                f"product:{r['product_id']}",
                f"{r['name']}: {r['stock']:.2f} {r['unit']} in stock, reorder level {r['reorder_level']:.2f}",
                "/drill?kind=products&filter=low_stock",
            )


def _petty_negative(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    for acc, name in db.execute(
        select(PettyCashAccount, User.full_name)
        .join(User, User.id == PettyCashAccount.user_id)
        .where(PettyCashAccount.is_active, User.is_demo.is_(False))
    ):
        if db.scalar(select(func.count()).where(PettyCashEntry.account_id == acc.id)) == 0:
            continue
        bal = fsvc.petty_balance(db, acc.id)["balance"]
        if bal < 0:
            yield Hit(
                f"petty:{acc.id}",
                f"Petty cash of {name} is negative ({bal:,.2f})",
                "/petty-cash",
                None,
                [acc.user_id],
            )


def _tender_due(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    day = today()
    for t in db.scalars(
        select(Tender).where(
            Tender.status == "draft",
            Tender.is_demo.is_(False),
            Tender.due_on.between(day, day + timedelta(days=int(cfg.get("days", 2)))),
        )
    ):
        yield Hit(
            f"tender:{t.id}",
            f"{t.code} {t.name[:80]} is due {t.due_on:%d %b} and not submitted",
            f"/tenders/{t.id}",
            None,
            [t.owner_id],
            "high",
        )


def _kylas_failing(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    from app.crm import kylas_push

    on, _ = kylas_push.enabled(db)
    if not on:
        return
    since = at - timedelta(hours=int(cfg.get("hours", 24)))
    stuck = db.scalar(
        select(func.count()).where(
            KylasOutbox.status.in_(("pending", "failed", "unknown")), KylasOutbox.created_at < since
        )
    )
    failed = db.scalar(
        select(func.count()).where(
            Lead.kylas_sync_status == "failed", Lead.updated_at < since, Lead.is_demo.is_(False)
        )
    )
    if stuck or failed:
        yield Hit(
            "kylas",
            f"Kylas sync failing for over {cfg.get('hours', 24)} h ({stuck + failed} lead(s) not synced)",
            "/drill?kind=leads&filter=kylas_failed",
            None,
            [],
            "high",
        )


def _followup_overdue(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """Quotation follow-ups past their day, still open (the salesperson gets it)."""
    from app.quotations.models import Quotation, QuotationFollowUp

    rows = db.execute(
        select(QuotationFollowUp, Quotation)
        .join(Quotation, Quotation.id == QuotationFollowUp.quotation_id)
        .where(QuotationFollowUp.status == "open", QuotationFollowUp.due_on < today())
    ).all()
    for f, q in rows:
        yield Hit(
            f"followup:{f.id}",
            f"Follow up {q.code} R{q.revision} {q.client_firm[:60]}: due {f.due_on:%d %b} (day {f.day})",
            f"/quotations/{q.id}",
            None,
            [f.salesperson_id] if f.salesperson_id else [],
            "warn",
        )


def _planning_users(db: Session) -> list:
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415

    planner = sc_settings(db).planning_user_id
    return [planner] if planner else role_users(db, ["office_admin"])


def _dn_unconfirmed(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """A delivery not confirmed 24 h (setting) after it was expected: the site in-charge."""
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import DeliveryNote  # noqa: PLC0415

    first = sc_settings(db).escalate_first_hours
    for dn in db.scalars(
        select(DeliveryNote).where(
            DeliveryNote.confirmed_at.is_(None),
            DeliveryNote.status == "dispatched",
            DeliveryNote.expected_at <= at - timedelta(hours=first),
        )
    ):
        site = db.get(Site, dn.site_id)
        hours = int((at - dn.expected_at).total_seconds() // 3600)
        yield Hit(
            f"dn:{dn.id}",
            f"{dn.code} for {site.name} not confirmed at site, {hours} h after it was expected",
            f"/deliveries/{dn.id}",
            site.id,
            [site.site_incharge_id],
            "warn",
        )


def _dn_escalated(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """Still not confirmed 48 h (setting) after it was expected: planning."""
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import DeliveryNote  # noqa: PLC0415

    second = sc_settings(db).escalate_second_hours
    planners = _planning_users(db)
    for dn in db.scalars(
        select(DeliveryNote).where(
            DeliveryNote.confirmed_at.is_(None),
            DeliveryNote.status == "dispatched",
            DeliveryNote.expected_at <= at - timedelta(hours=second),
        )
    ):
        site = db.get(Site, dn.site_id)
        hours = int((at - dn.expected_at).total_seconds() // 3600)
        drop = " (driver's drop-off photo attached)" if dn.drop_photo else ""
        yield Hit(
            f"dn:{dn.id}",
            f"{dn.code} for {site.name} still not confirmed, {hours} h after it was expected{drop}",
            f"/deliveries/{dn.id}",
            site.id,
            planners,
            "high",
        )


def _contract_expiring(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    from app.masters.models import Product  # noqa: PLC0415
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import RateContract  # noqa: PLC0415

    day = today()
    days = sc_settings(db).contract_expiry_days
    for c in db.scalars(
        select(RateContract).where(
            RateContract.is_active, RateContract.valid_till.between(day, day + timedelta(days=days))
        )
    ):
        v, p = db.get(Vendor, c.vendor_id), db.get(Product, c.product_id)
        yield Hit(
            f"rc:{c.id}",
            f"Rate contract {v.name} · {p.name} ends {c.valid_till:%d %b %Y}: renew it or agree a new rate",
            "/rate-contracts",
            None,
            [],
            "warn",
        )


def _ready_not_billed(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """Work done, not billed within 7 days (setting): billing and the site in-charge."""
    from app.sitecontrol.deliveries import settings as sc_settings  # noqa: PLC0415
    from app.sitecontrol.models import ReadyToBill  # noqa: PLC0415

    days = sc_settings(db).bill_alert_days
    rows = db.execute(
        select(ReadyToBill.site_id, func.count())
        .where(ReadyToBill.status == "open", ReadyToBill.created_at <= at - timedelta(days=days))
        .group_by(ReadyToBill.site_id)
    ).all()
    for site_id, n in rows:
        site = db.get(Site, site_id)
        yield Hit(
            f"rtb:{site_id}",
            f"{site.name}: {n} finished stage(s) not billed for over {days} days",
            "/ready-to-bill",
            site_id,
            [site.site_incharge_id],
            "warn",
        )


def _consumption_var(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """Weekly: sites whose material issued is off the systems' consumption (±15 %, setting)."""
    from app.sitecontrol import service as sc  # noqa: PLC0415

    week = f"{at.isocalendar().year}-W{at.isocalendar().week:02d}"
    planners = _planning_users(db)
    for site in db.scalars(select(Site).where(Site.status == "active", Site.is_demo.is_(False))):
        key = f"cons:{site.id}:{week}"
        if db.scalar(
            select(Alert.id).where(Alert.rule == "consumption_var", Alert.item_key == key)
        ):
            continue  # once a week
        flagged = [r for r in sc.consumption(db, site.id) if r["flag"]]
        if flagged:
            yield Hit(
                key,
                f"{site.name}: {len(flagged)} material(s) off the system's consumption this week",
                f"/consumption?site={site.id}",
                site.id,
                planners,
                "warn",
            )


def _award_followup(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """A tender awaiting award: a follow-up reminder every 60 days (setting) to its salesperson
    and planning, until it is won or lost."""
    from app.team.service import settings as team_settings  # noqa: PLC0415
    from app.tenders.models import TenderRevision  # noqa: PLC0415

    days = team_settings(db).award_followup_days
    for t in db.scalars(
        select(Tender).where(Tender.status == "submitted", Tender.is_demo.is_(False))
    ):
        submitted = db.scalar(
            select(func.max(TenderRevision.submitted_at)).where(TenderRevision.tender_id == t.id)
        )
        last = t.award_followup_at or submitted
        if last is None or (at - last).days < days:
            continue
        yield Hit(
            f"award:{t.id}:{(at - last).days // days}",
            f"{t.code} {t.name}: awaiting award for {(at - last).days} days, follow up",
            f"/tenders/{t.id}?tab=award",
            None,
            [t.owner_id],
            "warn",
        )


def _ra_monthly(db: Session, cfg: dict, at: datetime) -> Iterator[Hit]:
    """On the billing day each month (setting, the 25th): an RA bill to raise for every ongoing
    site with measured work not billed and no RA bill this month."""
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import ClientContract, ContractLine, RaBill  # noqa: PLC0415
    from app.team.service import book_total  # noqa: PLC0415
    from app.team.service import settings as team_settings  # noqa: PLC0415

    day = ist_day(at)
    if day.day < team_settings(db).billing_day:
        return
    month_start = datetime(day.year, day.month, 1, tzinfo=ex.IST)
    for c in db.scalars(select(ClientContract)):
        site = db.get(Site, c.site_id)
        if (
            site is None
            or site.is_demo
            or (site.status != "active" and site.board_status != "ongoing")
        ):
            continue
        unbilled = sum(
            (
                max(Decimal(0), book_total(db, cl.id) - fsvc.billed_before(db, cl.id, None))
                for cl in db.scalars(select(ContractLine).where(ContractLine.contract_id == c.id))
            ),
            Decimal(0),
        )
        if unbilled <= 0 or db.scalar(
            select(RaBill.id)
            .where(RaBill.contract_id == c.id, RaBill.created_at >= month_start)
            .limit(1)
        ):
            continue
        yield Hit(
            f"ra:{site.id}:{day:%Y-%m}",
            f"{site.name}: monthly RA bill due (measured work not billed)",
            f"/sites/{site.id}?tab=finance",
            site.id,
            [site.site_incharge_id],
            "warn",
        )


RULES = {
    "dpr_missing": _dpr_missing,
    "behind_schedule": _behind_schedule,
    "budget_head": _budget_head,
    "invoice_overdue": _invoice_overdue,
    "po_late": _po_late,
    "low_stock": _low_stock,
    "petty_negative": _petty_negative,
    "tender_due": _tender_due,
    "kylas_failing": _kylas_failing,
    "followup_overdue": _followup_overdue,
    "dn_unconfirmed": _dn_unconfirmed,
    "dn_escalated": _dn_escalated,
    "contract_expiring": _contract_expiring,
    "ready_not_billed": _ready_not_billed,
    "consumption_var": _consumption_var,
    "award_followup": _award_followup,
    "ra_monthly": _ra_monthly,
}


def run(db: Session, at: datetime | None = None) -> dict[str, int]:
    """Check every rule; returns {rule: alerts raised now}."""
    at = at or now()
    day = ist_day(at)
    cfg_all = rules(db)
    snooze = settings(db).ack_snooze_days
    raised: dict[str, int] = {}
    for rule, fn in RULES.items():
        cfg = cfg_all[rule]
        if not cfg.get("on", True):
            continue
        n = 0
        for hit in fn(db, cfg, at):
            if db.scalar(
                select(Alert.id).where(
                    Alert.rule == rule, Alert.item_key == hit.item_key, Alert.day == day
                )
            ):
                continue  # once per item per day
            acked = db.scalar(
                select(func.max(Alert.acknowledged_at)).where(
                    Alert.rule == rule, Alert.item_key == hit.item_key
                )
            )
            if acked and acked > at - timedelta(days=snooze):
                continue
            db.execute(
                update(Alert)
                .where(
                    Alert.rule == rule,
                    Alert.item_key == hit.item_key,
                    Alert.acknowledged_at.is_(None),
                    Alert.closed_at.is_(None),
                )
                .values(closed_at=at)
            )
            alert = Alert(
                rule=rule,
                item_key=hit.item_key,
                day=day,
                site_id=hit.site_id,
                title=hit.title[:300],
                link=hit.link,
                severity=hit.severity,
            )
            db.add(alert)
            db.flush()
            users = list(
                dict.fromkeys([u for u in [*role_users(db, cfg.get("roles", [])), *hit.users] if u])
            )
            for uid in users:
                db.add(AlertRecipient(alert_id=alert.id, user_id=uid))
            portal.notify(
                db,
                users,
                f"alert:{rule}",
                f"{RULE_LABELS[rule]}: {hit.title}",
                hit.link or "/alerts",
                hit.site_id,
            )
            n += 1
        raised[rule] = n
    s = settings(db)
    s.alerts_run_at = at
    db.commit()
    return raised


# --- reading -------------------------------------------------------------------------------------


def visible(
    db: Session,
    principal,
    rule: str | None = None,
    site_id: int | None = None,
    state: str = "open",
    limit: int = 200,
):
    """Alerts sent to the caller (all of them for dashboard.company)."""
    q = select(Alert)
    if "dashboard.company" not in principal.permissions:
        q = q.where(
            Alert.id.in_(
                select(AlertRecipient.alert_id).where(AlertRecipient.user_id == principal.user.id)
            )
        )
    if state == "open":
        q = q.where(Alert.acknowledged_at.is_(None), Alert.closed_at.is_(None))
    elif state == "acknowledged":
        q = q.where(Alert.acknowledged_at.is_not(None))
    if rule:
        q = q.where(Alert.rule == rule)
    if site_id:
        q = q.where(Alert.site_id == site_id)
    return list(db.scalars(q.order_by(Alert.created_at.desc()).limit(limit)))


def alert_out(a: Alert, names: dict) -> dict:
    return {
        "id": a.id,
        "rule": a.rule,
        "rule_label": RULE_LABELS[a.rule],
        "title": a.title,
        "link": a.link,
        "site_id": a.site_id,
        "severity": a.severity,
        "day": a.day,
        "created_at": a.created_at,
        "acknowledged_at": a.acknowledged_at,
        "acknowledged_by": names.get(a.acknowledged_by),
        "closed": a.closed_at is not None,
    }


__all__ = ["SiteSummary"]
