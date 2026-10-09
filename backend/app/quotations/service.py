"""Building quotations: assembling items from the library (a copy), filling selling rates (the
tender Suggest logic), totals, revisions and their differences, status changes with
follow-ups, the won hand-over (tender with the same lines, then the site) and expiry."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.auth.deps import Principal
from app.crm.models import Lead, LeadActivity
from app.masters.conversions import Rule
from app.masters.models import Client, LibraryItem, System, UnitConversion
from app.masters.rate import MissingPriceError, system_rate
from app.masters.rate_policy import load_histories
from app.material import service as material
from app.models import User
from app.quotations import library as lib
from app.quotations.markup import plain
from app.quotations.models import (
    OPEN_STATUSES,
    OfferItem,
    OfferLine,
    Quotation,
    QuotationFollowUp,
    QuotationItem,
    QuotationLine,
    QuotationSettings,
    Reference,
    SpecBlock,
)
from app.sites import service as site_service
from app.sites.models import AreaScope, Site, StageTemplate
from app.tenders import pricing
from app.tenders import service as tender_service
from app.tenders.models import BoqLine, Tender

CENT = Decimal("0.01")
TERMINAL = ("won", "lost", "expired")


def settings(db: Session) -> QuotationSettings:
    s = db.get(QuotationSettings, 1)
    if s is None:
        s = QuotationSettings(id=1)
        db.add(s)
        db.flush()
    return s


def money(v) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


# --- who sees what -------------------------------------------------------------------------------


def visible_q(scope: str, principal: Principal):
    """all: every quotation; own (and assigned): the caller's (salesperson or maker) and those
    of their leads."""
    q = select(Quotation)
    if scope == "all":
        return q
    me = principal.user.id
    return q.where(
        or_(
            Quotation.salesperson_id == me,
            Quotation.created_by == me,
            Quotation.lead_id.in_(select(Lead.id).where(Lead.owner_id == me)),
        )
    )


def get_visible(db: Session, qid: int, scope: str, principal: Principal) -> Quotation:
    q = db.scalar(visible_q(scope, principal).where(Quotation.id == qid))
    if q is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Quotation not found")
    return q


def check_edit(db: Session, q: Quotation, principal: Principal) -> None:
    scope = principal.permissions.get("quotation.edit")
    if scope is None or db.scalar(visible_q(scope, principal).where(Quotation.id == q.id)) is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot change this quotation")
    if not q.is_latest:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"R{q.revision} is an old revision: change the latest one (or make a new revision)",
        )
    if q.status in ("won", "lost", "expired"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{q.code} R{q.revision} is {q.status}: make a new revision to change it",
        )


# --- options -------------------------------------------------------------------------------------


def option_labels(item: QuotationItem) -> list[str]:
    """Every option label the item has (spec blocks, their sections and offer lines)."""
    found: list[str] = []
    for s in item.specs:
        if s.get("option_label"):
            found.append(str(s["option_label"]))
        for sec in s.get("sections") or []:
            if sec.get("option"):
                found.append(str(sec["option"]))
    for ln in item.lines:
        if ln.option:
            found.append(ln.option)
    return sorted(set(found), key=lambda o: (len(o), o))


def offered(item: QuotationItem) -> set[str]:
    """The ticked options; none ticked: all of them."""
    return set(item.options or []) or set(option_labels(item))


def is_offered(item: QuotationItem, option: str | None) -> bool:
    return option is None or str(option) in offered(item)


# --- rates ---------------------------------------------------------------------------------------


@dataclass
class RateContext:
    db: Session
    rules: list[Rule] = field(default_factory=list)
    _ctx: Any = None
    _matcher: Any = None

    @classmethod
    def make(cls, db: Session) -> "RateContext":
        rules = [
            Rule(r.from_unit, r.to_unit, r.factor, None)
            for r in db.scalars(select(UnitConversion).where(UnitConversion.product_id.is_(None)))
        ]
        return cls(db, rules)

    @property
    def policy(self):
        if self._ctx is None:
            self._ctx = pricing.PolicyContext(pricing.rate_policy(self.db), None)
            self._ctx.histories = load_histories(self.db)
        return self._ctx

    @property
    def matcher(self):
        if self._matcher is None:
            systems = list(self.db.scalars(select(System).where(System.is_active)))
            self._matcher = pricing._SystemMatcher(self.db, systems, self.rules)
        return self._matcher

    def factor(self, uom: str, other: str | None) -> Decimal | None:
        return pricing._unit_factor(self.rules, uom, other)


def _system(rc: RateContext, line: QuotationLine, system_id: int) -> bool:
    system = rc.db.get(System, system_id)
    if system is None:
        return False
    try:
        b = system_rate(rc.db, system)
    except MissingPriceError as e:
        line.rate_note = f"System {system.code}: {e}"
        return False
    f = rc.factor(line.uom, system.unit)
    if f is None:
        line.rate_note = f"System {system.code} is per {system.unit}, the line per {line.uom}"
        return False
    line.rate = money(b.rate * f)
    line.cost_rate = money(b.base_cost * f)
    line.margin_percent = b.margin_percent
    line.rate_source = "system"
    line.system_id = system.id
    line.rate_note = f"System {system.code} “{system.name}”"
    return True


def _library(rc: RateContext, line: QuotationLine, item_id: int) -> bool:
    item = rc.db.get(LibraryItem, item_id)
    if item is None:
        return False
    hit = {
        "id": item.id,
        "median_rate": item.median_rate,
        "latest_rate": item.latest_rate,
        "min_rate": item.min_rate,
        "max_rate": item.max_rate,
        "boq_count": item.boq_count,
    }
    priced = pricing.library_rate(hit, rc.policy)
    f = rc.factor(line.uom, item.unit)
    if priced is None or f is None:
        line.rate_note = "Rate library item has no rate in this unit"
        return False
    base, details = priced
    line.rate = money(Decimal(base) * f)
    line.cost_rate = None
    line.margin_percent = None
    line.rate_source = "library"
    line.library_item_id = item.id
    line.rate_note = f"Rate library: {details['used']}, {details['n_boqs']} BOQs"
    return True


def _suggest(rc: RateContext, line: QuotationLine) -> bool:
    """No explicit link: the tender Suggest (systems by name, then the rate library)."""
    probe = SimpleNamespace(description=plain(line.description), unit=line.uom)
    lexemes = pricing._lexemes(rc.db, [probe.description])[0]
    found = rc.matcher.candidates(probe, lexemes) + pricing._library_candidates(
        rc.db, probe, rc.rules, rc.policy
    )
    found.sort(key=lambda c: (-c.score, c.source != "system", c.ref_id))
    if not found or Decimal(str(found[0].score)) < pricing.threshold(rc.db):
        return False
    best = found[0]
    line.rate = money(best.rate)
    line.cost_rate = money(best.cost_rate) if best.cost_rate is not None else None
    line.margin_percent = best.margin_percent
    line.rate_source = best.source
    line.system_id = best.ref_id if best.source == "system" else None
    line.library_item_id = best.ref_id if best.source == "library" else None
    line.rate_note = f"Suggested: {best.reason} (score {best.score:.2f})"
    return True


def fill_rate(rc: RateContext, line: QuotationLine, src: OfferLine | None) -> None:
    """The selling rate from the line's source: its system build-up, its rate library item, its
    fixed rate, else Suggest; the library's default rate is the last resort."""
    if line.overridden:
        return
    line.cost_rate = line.margin_percent = None
    if line.client_scope:
        line.rate, line.rate_source, line.rate_note = None, None, "Client's scope"
        return
    source = src.rate_source if src else None
    if source == "system" and src.system_id and _system(rc, line, src.system_id):
        return
    if source == "library" and src.library_item_id and _library(rc, line, src.library_item_id):
        return
    if source == "fixed" and src.default_rate is not None:
        line.rate, line.rate_source = money(src.default_rate), "fixed"
        line.rate_note = "Fixed rate from the library"
        return
    if source != "fixed" and _suggest(rc, line):
        return
    default = src.default_rate if src else None
    line.rate = money(default) if default is not None else None
    line.rate_source = "fixed" if default is not None else None
    line.rate_note = (line.rate_note + "; " if line.rate_note else "") + (
        "library default rate" if default is not None else "no rate found: enter one"
    )


# --- assembling ----------------------------------------------------------------------------------


def spec_copy(block: SpecBlock) -> dict[str, Any]:
    return {
        "spec_block_id": block.id,
        "version": block.version,
        "title": block.title,
        "heading_prefix": block.heading_prefix,
        "option_label": block.option_label,
        "sections": block.sections or [],
        "images": block.images or [],
    }


def line_copy(src: OfferLine, option: str | None, order: int) -> QuotationLine:
    return QuotationLine(
        offer_line_id=src.id,
        library_version=src.version,
        sort_order=order,
        option=option,
        description=src.description,
        uom=src.uom,
        system_id=src.system_id,
        library_item_id=src.library_item_id,
        if_required=src.if_required,
        client_scope=src.client_scope,
    )


def add_item(
    db: Session, q: Quotation, offer: OfferItem, options: list[str] | None, rc: RateContext
) -> QuotationItem:
    """Copy an offer item (its spec blocks and offer lines) into the quotation, rates filled."""
    order = max((i.sort_order for i in q.items), default=0) + 10
    item = QuotationItem(
        offer_item_id=offer.id,
        sort_order=order,
        name=offer.name,
        budget_title=offer.budget_title,
        area_type_id=offer.area_type_id,
        options=[str(o) for o in options or []],
        specs=[spec_copy(s.spec) for s in offer.specs if s.spec.is_active],
    )
    for n, link in enumerate(offer.lines):
        ln = line_copy(link.line, link.option, n * 10)
        fill_rate(rc, ln, link.line)
        item.lines.append(ln)
    q.items.append(item)
    return item


def refill_rates(db: Session, q: Quotation) -> int:
    """Fill again every rate not overridden (after a library or price change)."""
    rc = RateContext.make(db)
    n = 0
    for item in q.items:
        for ln in item.lines:
            if not ln.overridden:
                fill_rate(rc, ln, db.get(OfferLine, ln.offer_line_id) if ln.offer_line_id else None)
                n += 1
    return n


def areas_list(q: Quotation) -> str:
    if q.areas_list:
        return q.areas_list
    names = [i.name.upper() for i in q.items]
    if not names:
        return "ALL AREA"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " & " + names[-1]


def placeholder_values(db: Session, q: Quotation, letterhead) -> dict[str, str]:
    person = db.get(User, q.salesperson_id) if q.salesperson_id else None
    return {
        "date": q.quote_date.strftime("%d.%m.%Y"),
        "client_firm": q.client_firm,
        "client_city": q.client_city or "",
        "attention": q.attention or "",
        "project": q.project,
        "brand": q.brand or (letterhead.brand if letterhead else "") or "",
        "areas_list": areas_list(q),
        "salesperson": q.signatory_name
        or (person.full_name if person else "")
        or (letterhead.signatory_name if letterhead else "")
        or "",
        "designation": q.signatory_designation
        or (person.job_title if person else "")
        or (letterhead.signatory_designation if letterhead else "")
        or "",
        "enclosures": ", ".join(e for e in q.enclosures.split("\n") if e.strip()),
    }


# --- totals --------------------------------------------------------------------------------------


def line_amount(ln: QuotationLine) -> Decimal | None:
    if ln.qty is None or ln.rate is None or ln.client_scope:
        return None
    return money(Decimal(ln.qty) * Decimal(ln.rate))


def totals(q: Quotation) -> dict[str, Any]:
    """Per item and overall: lines with a quantity and a rate; where options are offered only
    the first offered option counts; "if required" and client's-scope lines never count."""
    items, grand = [], Decimal(0)
    for item in q.items:
        first = min(offered(item), key=lambda o: (len(o), o), default=None)
        s = Decimal(0)
        for ln in item.lines:
            if not is_offered(item, ln.option) or ln.if_required:
                continue
            if ln.option is not None and ln.option != first:
                continue
            s += line_amount(ln) or 0
        items.append({"item_id": item.id, "total": money(s)})
        grand += s
    return {
        "items": items,
        "total": money(grand),
        "option_note": any(len(offered(i)) > 1 for i in q.items),
    }


# --- revisions -----------------------------------------------------------------------------------


def copy_quotation(db: Session, q: Quotation, user_id) -> Quotation:
    """A new revision: the same text, items and lines; the old one stays as it was."""
    cols = {
        c: getattr(q, c)
        for c in (
            "code lead_id client_id survey_id tender_id letterhead_id salesperson_id client_firm "
            "client_city client_state attention project brand areas_list validity_days "
            "show_amounts "
            "letter_template_id opening subject body enclosures signatory_name "
            "signatory_designation terms references references_title notes"
        ).split()
    }
    new = Quotation(
        **cols,
        revision=q.revision + 1,
        previous_id=q.id,
        quote_date=date.today(),
        status="draft",
        is_latest=True,
        created_by=user_id,
    )
    for item in q.items:
        ni = QuotationItem(
            offer_item_id=item.offer_item_id,
            sort_order=item.sort_order,
            name=item.name,
            budget_title=item.budget_title,
            area_type_id=item.area_type_id,
            options=list(item.options or []),
            specs=[dict(s) for s in item.specs],
        )
        for ln in item.lines:
            ni.lines.append(
                QuotationLine(
                    **{
                        c: getattr(ln, c)
                        for c in (
                            "offer_line_id library_version sort_order option description uom rate "
                            "rate_source rate_note system_id library_item_id cost_rate "
                            "margin_percent overridden qty if_required client_scope"
                        ).split()
                    }
                )
            )
        new.items.append(ni)
    q.is_latest = False
    db.add(new)
    db.flush()
    return new


def _key(item: QuotationItem, ln: QuotationLine) -> tuple:
    return (item.name, ln.offer_line_id or plain(ln.description)[:80], ln.option)


def diff(old: Quotation, new: Quotation) -> dict[str, Any]:
    """What changed between two revisions, for negotiation: rates, quantities, lines and items."""

    def lines(q):
        return {_key(i, ln): (i, ln) for i in q.items for ln in i.lines}

    a, b = lines(old), lines(new)
    changed, added, removed = [], [], []
    for k, (item, ln) in b.items():
        label = plain(ln.description)[:90]
        if k not in a:
            added.append({"item": item.name, "line": label, "rate": ln.rate})
            continue
        _, before = a[k]
        if (
            before.rate != ln.rate
            or before.qty != ln.qty
            or plain(before.description) != plain(ln.description)
        ):
            change = {"item": item.name, "line": label, "option": ln.option, "uom": ln.uom}
            if before.rate != ln.rate:
                change.update(old_rate=before.rate, new_rate=ln.rate)
                if before.rate and ln.rate:
                    change["rate_change_percent"] = money(
                        (Decimal(ln.rate) - before.rate) / before.rate * 100
                    )
            if before.qty != ln.qty:
                change.update(old_qty=before.qty, new_qty=ln.qty)
            if plain(before.description) != plain(ln.description):
                change["text_changed"] = True
            changed.append(change)
    for k, (item, ln) in a.items():
        if k not in b:
            removed.append({"item": item.name, "line": plain(ln.description)[:90], "rate": ln.rate})
    old_items = {i.name for i in old.items}
    new_items = {i.name for i in new.items}
    return {
        "from": f"R{old.revision}",
        "to": f"R{new.revision}",
        "changed": changed,
        "added": added,
        "removed": removed,
        "items_added": sorted(new_items - old_items),
        "items_removed": sorted(old_items - new_items),
        "total_from": totals(old)["total"],
        "total_to": totals(new)["total"],
    }


# --- status, follow-ups, won / lost, expiry ------------------------------------------------------


def _activity(db: Session, q: Quotation, text: str, user_id, file_id: int | None = None) -> None:
    if q.lead_id:
        db.add(
            LeadActivity(
                lead_id=q.lead_id,
                type="quotation",
                text=text,
                by=user_id,
                quotation_file_id=file_id,
            )
        )


def schedule_followups(db: Session, q: Quotation, sent_on: date) -> list[QuotationFollowUp]:
    """Follow-ups on day 2, 7, 15, 30 (setting) after sending; open ones of earlier revisions
    of the same quotation are replaced."""
    cancel_followups(db, q, all_revisions=True)
    rows = [
        QuotationFollowUp(
            quotation_id=q.id,
            salesperson_id=q.salesperson_id,
            day=int(d),
            due_on=sent_on + timedelta(days=int(d)),
        )
        for d in sorted({int(x) for x in settings(db).followup_days or []})
    ]
    db.add_all(rows)
    return rows


def cancel_followups(db: Session, q: Quotation, all_revisions: bool = False) -> None:
    ids = (
        select(Quotation.id).where(Quotation.code == q.code)
        if all_revisions
        else select(Quotation.id).where(Quotation.id == q.id)
    )
    db.execute(
        update(QuotationFollowUp)
        .where(QuotationFollowUp.quotation_id.in_(ids), QuotationFollowUp.status == "open")
        .values(status="cancelled")
    )


def mark_sent(db: Session, q: Quotation, user_id) -> None:
    if q.status not in ("draft", "negotiation", "sent"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {q.status} quotation cannot be sent")
    first = q.status == "draft"
    q.status = "sent" if first else q.status
    q.sent_at = datetime.now(UTC)
    schedule_followups(db, q, date.today())
    if q.lead_id:
        lead = db.get(Lead, q.lead_id)
        if lead and lead.status in ("new", "contacted", "site_visit"):
            lead.status = "quoted"
    _activity(db, q, f"Quotation {q.code} R{q.revision} sent", user_id)


def mark_lost(db: Session, q: Quotation, reason: str | None, note: str | None, user_id) -> None:
    if not reason:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Choose why the quotation was lost"
        )
    q.status, q.lost_reason, q.lost_note = "lost", reason, note
    q.decided_at = datetime.now(UTC)
    cancel_followups(db, q, all_revisions=True)
    _activity(db, q, f"Quotation {q.code} R{q.revision} lost ({reason})", user_id)


def mark_won(
    db: Session,
    q: Quotation,
    user_id,
    site_id: int | None = None,
    choices: dict[int, str] | None = None,
) -> tuple[Tender, Site]:
    """Won: the tender (order) record gets the quotation's lines (the chosen option of each
    item; "if required" lines too, client's scope never), then the site is made or linked. The
    execution and billing work from those same lines."""
    if q.status not in ("draft", "sent", "negotiation"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A {q.status} quotation cannot be won")
    choices = choices or {}
    client_id = q.client_id
    if client_id is None:
        client = db.scalar(select(Client).where(Client.name == q.client_firm))
        if client is None:
            client = Client(
                name=q.client_firm, city=q.client_city, state=q.client_state, created_by=user_id
            )
            db.add(client)
            db.flush()
        client_id = q.client_id = client.id
    tender = db.get(Tender, q.tender_id) if q.tender_id else None
    if tender is None:
        tender = Tender(
            code=tender_service.next_code(db),
            name=f"{q.project} ({q.code} R{q.revision})",
            client_id=client_id,
            site_name=q.project,
            site_city=q.client_city,
            site_state=q.client_state,
            owner_id=q.salesperson_id,
            received_on=q.quote_date,
            status="won",
            created_by=user_id,
        )
        db.add(tender)
        db.flush()
        order = 10
        for item in q.items:
            pick = choices.get(item.id) or min(
                offered(item), key=lambda o: (len(o), o), default=None
            )
            for ln in item.lines:
                if ln.client_scope or (ln.option is not None and ln.option != pick):
                    continue
                db.add(
                    BoqLine(
                        tender_id=tender.id,
                        sort_order=order,
                        description=f"{item.name} — {plain(ln.description)}",
                        unit=ln.uom,
                        unit_raw=ln.uom,
                        qty=ln.qty,
                        rate=ln.rate,
                        cost_rate=ln.cost_rate,
                        margin_percent=ln.margin_percent,
                        source={"system": "system", "library": "library"}.get(
                            ln.rate_source or "", "manual"
                        )
                        if ln.rate is not None
                        else None,
                        system_id=ln.system_id,
                        library_item_id=ln.library_item_id,
                        status="priced" if ln.rate is not None else "unpriced",
                        created_by=user_id,
                    )
                )
                order += 10
        db.flush()
        q.tender_id = tender.id
    tender.status = "won"
    tender.decided_at = datetime.now(UTC)
    site = (
        db.get(Site, site_id)
        if site_id
        else db.scalar(select(Site).where(Site.tender_id == tender.id))
    )
    if site_id and site is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Site not found")
    if site is None:
        site = Site(
            code=site_service.next_code(db),
            name=q.project,
            client_id=client_id,
            tender_id=tender.id,
            city=q.client_city,
            state=q.client_state,
            status="planned",
            created_by=user_id,
        )
        db.add(site)
        db.flush()
        material.site_store(db, site, user_id)
    elif site.tender_id is None:
        site.tender_id = tender.id
    q.site_id = site.id
    q.status = "won"
    q.decided_at = datetime.now(UTC)
    cancel_followups(db, q, all_revisions=True)
    if q.lead_id:
        lead = db.get(Lead, q.lead_id)
        if lead:
            lead.status = "won"
            lead.tender_id = lead.tender_id or tender.id
    _activity(
        db, q, f"Quotation {q.code} R{q.revision} won: {tender.code}, site {site.code}", user_id
    )
    return tender, site


def expire_due(db: Session, today: date | None = None) -> int:
    """Sent or in negotiation past the validity: expired (follow-ups stop)."""
    today = today or date.today()
    n = 0
    for q in db.scalars(
        select(Quotation).where(Quotation.status.in_(OPEN_STATUSES), Quotation.is_latest)
    ):
        if q.quote_date + timedelta(days=q.validity_days) < today:
            q.status = "expired"
            cancel_followups(db, q, all_revisions=True)
            n += 1
    return n


def closure_target(db: Session, user_id=None) -> Decimal:
    """The salesperson's closure target (won ÷ decided, %), else the company one (65 %)."""
    s = settings(db)
    own = (s.closure_targets or {}).get(str(user_id)) if user_id else None
    return Decimal(str(own if own is not None else s.closure_target_percent))


def followup_rows(
    db: Session,
    user_id=None,
    upto: date | None = None,
    status_: str | None = "open",
    quotation_code: str | None = None,
) -> list[dict]:
    """Follow-ups for the sales dashboard and the list: the salesperson's (or everyone's),
    oldest first, with the quotation they are for (all revisions of one code with
    quotation_code; any status with status_=None)."""
    q = (
        select(QuotationFollowUp, Quotation, User.full_name)
        .join(Quotation, Quotation.id == QuotationFollowUp.quotation_id)
        .outerjoin(User, User.id == QuotationFollowUp.salesperson_id)
        .order_by(QuotationFollowUp.due_on, QuotationFollowUp.id)
    )
    if status_:
        q = q.where(QuotationFollowUp.status == status_)
    if quotation_code:
        q = q.where(Quotation.code == quotation_code)
    if user_id is not None:
        q = q.where(QuotationFollowUp.salesperson_id == user_id)
    if upto is not None:
        q = q.where(QuotationFollowUp.due_on <= upto)
    today = date.today()
    return [
        {
            "id": f.id,
            "quotation_id": qt.id,
            "code": f"{qt.code} R{qt.revision}",
            "client_firm": qt.client_firm,
            "project": qt.project,
            "quotation_status": qt.status,
            "day": f.day,
            "due_on": f.due_on,
            "overdue": f.due_on < today and f.status == "open",
            "status": f.status,
            "salesperson": name,
            "note": f.note,
        }
        for f, qt, name in db.execute(q).all()
    ]


# --- references ----------------------------------------------------------------------------------


def references_from_sites(db: Session, user_id) -> int:
    """A reference row for each completed site that has none yet (client, project, the area
    types and systems treated, the area covered in sqft). Editable afterwards."""
    n = 0
    have = set(db.scalars(select(Reference.site_id).where(Reference.site_id.is_not(None))))
    for site in db.scalars(select(Site).where(Site.status == "completed", Site.is_demo.is_(False))):
        if site.id in have:
            continue
        client = db.get(Client, site.client_id) if site.client_id else None
        scopes = list(db.scalars(select(AreaScope).where(AreaScope.site_id == site.id)))
        sqm = sum((Decimal(s.qty or 0) for s in scopes if s.unit == "sqm"), Decimal(0))
        sqft = sum((Decimal(s.qty or 0) for s in scopes if s.unit == "sqft"), Decimal(0))
        sqft = money(sqft + sqm * Decimal("10.7639")) if sqm or sqft else None
        works = db.scalars(
            select(StageTemplate.name).where(
                StageTemplate.id.in_({s.stage_template_id for s in scopes} or {0})
            )
        ).all()
        row = Reference(
            client_name=client.name if client else site.name,
            project=site.name,
            application=", ".join(sorted(works)),
            area_value=sqft,
            area_unit="SQFT" if sqft else None,
            state=site.state,
            site_id=site.id,
            source="site",
            needs_check=True,
            created_by=user_id,
        )
        db.add(row)
        lib.save_version(db, row, "create", user_id, note=f"from site {site.code}")
        n += 1
    return n
