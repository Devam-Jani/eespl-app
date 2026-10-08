# ruff: noqa: E501  (HTML templates read better unwrapped)
"""PDFs in the EESPL format: tax invoice / credit note, RA bill, payslip."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.execution.pdf import _doc, e
from app.finance import service as svc
from app.finance.models import PayrollRun, Payslip, TaxInvoice
from app.masters.models import CompanyBankAccount, CompanyProfile
from app.material.po_pdf import in_words
from app.models import User
from app.tenders.export import company, inr

EXTRA_CSS = """
<style>
.inv-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; }
.inv-meta .box { border: 0.6px solid #999; padding: 5px 6px; }
.inv-meta h3 { margin: 0 0 3px; font-size: 8pt; color: #2f6f4f; text-transform: uppercase; }
.words { margin-top: 4px; font-style: italic; }
.small { font-size: 7.5pt; color: #444; }
.keep { page-break-inside: avoid; }
</style>
"""


def _num(v) -> str:
    v = Decimal(v)
    return f"{v.normalize():f}" if v == v.to_integral() else f"{v:.3f}".rstrip("0")


def short_item(text: str, limit: int = 80) -> str:
    """The item's code and short name for an invoice: the BOQ title before " — " (the full
    specification stays on the RA bill), cut at about 80 characters."""
    title = text.split(" — ", 1)[0].strip()
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def tax_invoice(db: Session, inv: TaxInvoice, out: dict) -> bytes:
    c = company(db)
    ours = svc.our_gstin(db, inv.from_gstin_id)
    profile = db.get(CompanyProfile, 1)
    bank = (
        db.scalar(
            select(CompanyBankAccount)
            .order_by(CompanyBankAccount.is_primary.desc(), CompanyBankAccount.id)
            .limit(1)
        )
        if hasattr(CompanyBankAccount, "is_primary")
        else db.scalar(select(CompanyBankAccount).limit(1))
    )
    credit = inv.kind == "credit_note"
    rows = []
    for n, ln in enumerate(inv.lines, start=1):
        rate = Decimal(ln.gst_percent)
        cgst, sgst, igst = svc.line_tax(ln.amount, rate, inv.interstate)  # what the totals add up
        split = (
            f"<td class='num'>{_num(rate)}%</td><td class='num'>{e(inr(igst))}</td>"
            if inv.interstate
            else f"<td class='num'>{_num(rate / 2)}% {e(inr(cgst))}</td><td class='num'>{_num(rate / 2)}% {e(inr(sgst))}</td>"
        )
        rows.append(
            f"<tr><td>{n}</td><td>{e(short_item(ln.description))}</td><td>{e(ln.sac or '')}</td>"
            f"<td class='num'>{e(_num(ln.qty) if ln.qty is not None else '')} {e(ln.unit or '')}</td>"
            f"<td class='num'>{e(inr(ln.rate) if ln.rate is not None else '')}</td>"
            f"<td class='num'>{e(inr(ln.amount))}</td>{split}</tr>"
        )
    tax_head = (
        "<th class='num'>IGST %</th><th class='num'>IGST</th>"
        if inv.interstate
        else "<th class='num'>CGST</th><th class='num'>SGST</th>"
    )
    tax_rows = (
        f"<tr><td>IGST</td><td class='num'>{e(inr(inv.igst))}</td></tr>"
        if inv.interstate
        else f"<tr><td>CGST</td><td class='num'>{e(inr(inv.cgst))}</td></tr><tr><td>SGST</td><td class='num'>{e(inr(inv.sgst))}</td></tr>"
    )
    deductions = ""
    if not credit and (
        Decimal(inv.retention) or Decimal(inv.advance_recovery) or Decimal(inv.other_deduction)
    ):
        net = (
            Decimal(inv.total)
            - Decimal(inv.retention)
            - Decimal(inv.advance_recovery)
            - Decimal(inv.other_deduction)
        )
        deductions = (
            "<h2>Deductions as per contract</h2><table class='totals'>"
            f"<tr><td>Retention</td><td class='num'>{e(inr(inv.retention))}</td></tr>"
            f"<tr><td>Mobilisation advance recovery</td><td class='num'>{e(inr(inv.advance_recovery))}</td></tr>"
            f"<tr><td>Other</td><td class='num'>{e(inr(inv.other_deduction))}</td></tr>"
            f"<tr><td><b>Net payable now (before TDS)</b></td><td class='num'><b>{e(inr(net))}</b></td></tr></table>"
        )
    against = ""
    if credit and inv.against_id:
        orig = db.get(TaxInvoice, inv.against_id)
        against = f"<div><b>Against invoice:</b> {e(orig.number)} dated {orig.invoice_date:%d-%m-%Y}</div>"
    bank_html = (
        (
            f"<h2>Bank details</h2><div>{e(bank.account_name)} · {e(bank.bank or '')} {e(bank.branch or '')}<br>"
            f"A/c {e(bank.account_number)} · IFSC {e(bank.ifsc)}</div>"
        )
        if bank and not credit
        else ""
    )
    contact = " · ".join(
        x
        for x in (
            f"Phone {profile.phone}" if profile and profile.phone else "",
            f"Email {profile.email}" if profile and profile.email else "",
        )
        if x
    )
    our_line = " · ".join(
        x
        for x in (
            e(f"GSTIN {ours.gstin} ({ours.state})")
            if ours
            else '<b style="color:#c00000">GSTIN not set</b>',
            e(f"PAN {profile.pan}") if profile and profile.pan else "",
            e(contact),
        )
        if x
    )
    body = f"""{EXTRA_CSS}
<div class="small">{our_line}</div>
<div class="inv-meta">
<div class="box"><h3>{"Credit note" if credit else "Invoice"}</h3><b>No:</b> {e(inv.number)}<br><b>Date:</b> {inv.invoice_date:%d-%m-%Y}<br>
{f"<b>Due:</b> {inv.due_date:%d-%m-%Y}<br>" if inv.due_date else ""}<b>Place of supply:</b> {e(inv.place_of_supply or "—")}<br>
<b>Supply:</b> {"Inter-state (IGST)" if inv.interstate else "Intra-state (CGST + SGST)"}{against}
{f"<br><b>Site:</b> {e(out.get('site_code'))}" if out.get("site_code") else ""}</div>
<div class="box"><h3>Bill to</h3><b>{e(inv.client.name)}</b><br>{e(inv.billing_address or "")}<br>
{e(f"GSTIN: {inv.client_gstin}" if inv.client_gstin else "GSTIN: unregistered")}</div></div>
<table><thead><tr><th>#</th><th>Description</th><th>SAC</th><th class="num">Qty</th><th class="num">Rate</th>
<th class="num">Taxable</th>{tax_head}</tr></thead><tbody>{"".join(rows)}</tbody></table>
<div class="keep">
<table class="totals"><tr><td>Taxable value</td><td class="num">{e(inr(inv.taxable))}</td></tr>{tax_rows}
<tr><td>Round off</td><td class="num">{e(inr(inv.round_off))}</td></tr>
<tr><td><b>{"Credit total" if credit else "Invoice total"}</b></td><td class="num"><b>{e(inr(inv.total))}</b></td></tr></table>
<div class="words">{e(in_words(inv.total))}</div>
{deductions}{bank_html}
{f'<h2>Remarks</h2><div class="pre">{e(inv.remark)}</div>' if inv.remark else ""}
<p class="small">Certified that the particulars given above are true and correct. Tax is not payable on reverse charge.</p>
<div class="sign"><div><b>Receiver's signature</b><div class="line"></div></div>
<div><b>For {e(c.name)}</b><div class="line">Authorised signatory</div></div></div>
</div>"""
    return _doc(db, "CREDIT NOTE" if credit else "TAX INVOICE", body)


def ra_bill(db: Session, out: dict) -> bytes:
    rows = []
    for n, ln in enumerate(out["lines"], start=1):
        if not (Decimal(ln["qty"]) or Decimal(ln["previous_qty"])):
            continue
        cert = ln["certified_qty"]
        rows.append(
            f"<tr><td>{e(ln['item_no'] or n)}</td><td class='desc'>{e(ln['description'])}</td><td>{e(ln['unit'])}</td>"
            f"<td class='num'>{_num(ln['boq_qty'])}</td><td class='num'>{_num(ln['previous_qty'])}</td>"
            f"<td class='num'>{_num(ln['qty'])}</td><td class='num'>{_num(cert) if cert is not None else '—'}</td>"
            f"<td class='num'>{_num(ln['cumulative_qty'])}</td><td class='num'>{e(inr(ln['rate']))}</td>"
            f"<td class='num'>{e(inr(ln['certified_amount'] if cert is not None else ln['amount']))}</td>"
            f"<td class='num'>{e(inr(ln['cumulative_amount']))}</td></tr>"
        )
    certified = out["certified_gross"] is not None
    # landscape, with the full specification in a wide description column
    body = f"""{EXTRA_CSS}<style>@page {{ size: A4 landscape; }} td.desc {{ width: 42%; font-size: 7.5pt; }}</style>
<div class="inv-meta"><div class="box"><h3>Bill</h3><b>{e(out["code"])}</b> · RA bill {out["seq"]}<br>
<b>Period:</b> {e(f"{out['period_from']:%d-%m-%Y}" if out["period_from"] else "start")} to {out["period_to"]:%d-%m-%Y}<br>
<b>Status:</b> {e(out["status"])}{f" · certified by {e(out['certified_by_client'])}" if out.get("certified_by_client") else ""}</div>
<div class="box"><h3>Client / site</h3><b>{e(out["client_name"] or "")}</b><br>{e(out["site_code"])} · {e(out["site_name"])}</div></div>
<table><thead><tr><th>Item</th><th>Description</th><th>Unit</th><th class="num">BOQ qty</th><th class="num">Previous</th>
<th class="num">This bill</th><th class="num">Certified</th><th class="num">Cumulative</th><th class="num">Rate</th>
<th class="num">This bill ₹</th><th class="num">Cumulative ₹</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<div class="keep"><table class="totals">
<tr><td>Gross this bill (submitted)</td><td class="num">{e(inr(out["gross"]))}</td></tr>
{f'<tr><td>Gross this bill (certified)</td><td class="num">{e(inr(out["certified_gross"]))}</td></tr>' if certified else ""}
<tr><td>Less retention {_num(out["retention_percent"])}%</td><td class="num">-{e(inr(out["retention"]))}</td></tr>
<tr><td>Less mobilisation advance recovery</td><td class="num">-{e(inr(out["advance_recovery"]))}</td></tr>
<tr><td>Less other {e(f"({out['other_deduction_remark']})" if out.get("other_deduction_remark") else "")}</td><td class="num">-{e(inr(out["other_deduction"]))}</td></tr>
<tr><td><b>Net amount (before GST)</b></td><td class="num"><b>{e(inr(out["net"]))}</b></td></tr></table>
<p class="small">GST is charged on the tax invoice raised on the certified amount.</p>
<div class="sign"><div><b>Certified by the client</b><div class="line">{e(out.get("certified_by_client") or "")}</div></div>
<div><b>For {e(company(db).name)}</b><div class="line">Project manager</div></div></div></div>"""
    return _doc(db, "RUNNING ACCOUNT BILL", body)


def payslip(db: Session, run: PayrollRun, p: Payslip, user: User) -> bytes:
    earn = [("Basic", p.basic), ("HRA", p.hra), ("Other allowances", p.other_allowance)]
    ded = [
        ("Provident fund (employee)", p.pf_employee),
        ("ESI (employee)", p.esi_employee),
        ("Professional tax", p.pt),
        ("Advance recovery", p.advance_recovery),
    ]
    n = max(len(earn), len(ded))
    rows = "".join(
        f"<tr><td>{e(earn[i][0]) if i < len(earn) else ''}</td><td class='num'>{e(inr(earn[i][1])) if i < len(earn) else ''}</td>"
        f"<td>{e(ded[i][0]) if i < len(ded) else ''}</td><td class='num'>{e(inr(ded[i][1])) if i < len(ded) else ''}</td></tr>"
        for i in range(n)
    )
    total_ded = sum((Decimal(x[1]) for x in ded), Decimal(0))
    ids = "".join(
        f"<br>{label}: {e(v)}"
        for label, v in (
            ("PAN", user.pan),
            ("UAN", user.uan),
            ("ESI no.", user.esi_no),
            (
                "Bank",
                f"{user.bank_account_masked} · {user.bank_ifsc or ''}"
                if user.bank_account
                else None,
            ),
        )
        if v
    )
    body = f"""{EXTRA_CSS}
<div class="inv-meta"><div class="box"><h3>Employee</h3><b>{e(user.full_name)}</b><br>{e(user.email)}{ids}</div>
<div class="box"><h3>Month</h3><b>{e(run.month)}</b> · {e(run.status)}<br>Days in month {p.days_in_month} · worked {p.worked_days}
· leave {_num(p.leave_days)} · loss of pay {_num(p.lop_days)} · paid days {_num(p.paid_days)}</div></div>
<table><thead><tr><th>Earnings</th><th class="num">₹</th><th>Deductions</th><th class="num">₹</th></tr></thead>
<tbody>{rows}<tr><td><b>Gross</b></td><td class="num"><b>{e(inr(p.gross))}</b></td><td><b>Total deductions</b></td>
<td class="num"><b>{e(inr(total_ded))}</b></td></tr></tbody></table>
<table class="totals"><tr><td>Gross less deductions</td><td class="num">{e(inr(Decimal(p.gross) - total_ded))}</td></tr>
<tr><td>Round off</td><td class="num">{e(inr(p.round_off))}</td></tr>
<tr><td><b>Net pay</b></td><td class="num"><b>{e(inr(p.net))}</b></td></tr></table>
<div class="words">{e(in_words(p.net))}</div>
<p class="small">Employer contributions (not deducted): PF {e(inr(p.pf_employer))} · ESI {e(inr(p.esi_employer))}.</p>
<p class="small">This is a computer-generated payslip.</p>"""
    return _doc(db, "PAYSLIP", body)
