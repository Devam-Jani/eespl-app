"""Vouchers for Tally: sales (tax invoices, credit notes), purchase (vendor and subcontractor
bills), receipt, payment, and journal (petty cash, payroll). Built as TallyPrime import XML and as
an Excel day book. Download only: nothing is sent anywhere.

Tally's sign convention: a debit entry has ISDEEMEDPOSITIVE Yes and a negative AMOUNT; a credit
has No and a positive AMOUNT. Every voucher balances (debits = credits).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance import service as svc
from app.finance.models import (
    Payment,
    PayrollRun,
    PettyCashAccount,
    PettyCashEntry,
    Receipt,
    TaxInvoice,
    VendorBill,
)
from app.masters.models import Client, CompanyBankAccount, Vendor
from app.models import User

ZERO = Decimal(0)


@dataclass
class Voucher:
    source: object  # the row to mark exported
    vtype: str  # Sales, Credit Note, Purchase, Receipt, Payment, Journal
    number: str
    on: date
    party: str | None
    narration: str
    entries: list[tuple[str, Decimal]] = field(default_factory=list)  # (ledger, + debit / - credit)

    def add(self, ledger: str, amount: Decimal) -> None:
        amount = Decimal(amount)
        if amount:
            self.entries.append((ledger, svc.money(amount)))

    def balanced(self) -> bool:
        return sum((a for _, a in self.entries), ZERO) == 0


def _ledgers(db: Session) -> dict:
    return svc.settings(db).tally_ledgers or {}


def _party(db: Session, name: str) -> str:
    return (svc.settings(db).party_ledgers or {}).get(name, name)


def _bank(db: Session, L: dict, bank_id: int | None, mode: str) -> str:
    if mode == "cash":
        return L.get("cash", "Cash")
    banks = L.get("banks") or {}
    if bank_id and str(bank_id) in banks:
        return banks[str(bank_id)]
    if bank_id:
        b = db.get(CompanyBankAccount, bank_id)
        if b is not None:
            return f"{b.bank or 'Bank'} {b.account_number[-4:]}"
    return L.get("bank_default", "Bank")


def vouchers(db: Session, start: date, end: date, include_exported: bool = False) -> list[Voucher]:
    L = _ledgers(db)
    out: list[Voucher] = []

    def fresh(model, date_col):
        q = select(model).where(date_col >= start, date_col <= end)
        if not include_exported:
            q = q.where(model.tally_exported_at.is_(None))
        return db.scalars(q.order_by(date_col, model.id))

    for inv in fresh(TaxInvoice, TaxInvoice.invoice_date):
        if inv.status != "issued":
            continue
        party = _party(db, db.get(Client, inv.client_id).name)
        sign = 1 if inv.kind == "invoice" else -1
        v = Voucher(
            inv,
            "Sales" if inv.kind == "invoice" else "Credit Note",
            inv.number,
            inv.invoice_date,
            party,
            inv.remark or "",
        )
        v.add(party, sign * Decimal(inv.total))
        v.add(L.get("sales", "Sales"), -sign * Decimal(inv.taxable))
        v.add(L.get("output_cgst", "Output CGST"), -sign * Decimal(inv.cgst))
        v.add(L.get("output_sgst", "Output SGST"), -sign * Decimal(inv.sgst))
        v.add(L.get("output_igst", "Output IGST"), -sign * Decimal(inv.igst))
        v.add(L.get("round_off", "Round Off"), -sign * Decimal(inv.round_off))
        if inv.kind == "invoice" and Decimal(
            inv.advance_recovery
        ):  # set off against the advance received
            v.add(L.get("client_advance", "Client Advances"), Decimal(inv.advance_recovery))
            v.add(party, -Decimal(inv.advance_recovery))
        out.append(v)

    for b in fresh(VendorBill, VendorBill.bill_date):
        if b.status in ("draft", "cancelled"):
            continue
        party = _party(db, db.get(Vendor, b.vendor_id).name)
        v = Voucher(
            b,
            "Purchase",
            b.number,
            b.bill_date,
            party,
            f"Bill {b.bill_no}. {b.remark or ''}".strip(),
        )
        if b.kind == "retention":
            v.add(L.get("retention_payable", "Retention Payable"), Decimal(b.payable))
            v.add(party, -Decimal(b.payable))
            out.append(v)
            continue
        expense = {
            "material": "purchase",
            "service": "service",
            "freight": "freight",
            "subcontract": "subcontract",
        }[b.kind]
        tax = Decimal(b.cgst) + Decimal(b.sgst) + Decimal(b.igst)
        if b.itc_eligible:
            v.add(L.get(expense, "Purchase"), Decimal(b.taxable))
            v.add(L.get("input_cgst", "Input CGST"), Decimal(b.cgst))
            v.add(L.get("input_sgst", "Input SGST"), Decimal(b.sgst))
            v.add(L.get("input_igst", "Input IGST"), Decimal(b.igst))
        else:  # no input tax credit: the tax is part of the cost
            v.add(L.get(expense, "Purchase"), Decimal(b.taxable) + tax)
        v.add(L.get("round_off", "Round Off"), Decimal(b.round_off))
        v.add(L.get("tds_payable", "TDS Payable"), -Decimal(b.tds_amount))
        held = (
            Decimal(b.total) - Decimal(b.tds_amount) - Decimal(b.payable)
        )  # retention and recoveries
        v.add(L.get("retention_payable", "Retention Payable"), -held)
        v.add(party, -Decimal(b.payable))
        out.append(v)

    for r in fresh(Receipt, Receipt.on_date):
        party = _party(db, db.get(Client, r.client_id).name)
        v = Voucher(
            r, "Receipt", r.number, r.on_date, party, f"{r.mode.upper()} {r.ref_no or ''}".strip()
        )
        v.add(_bank(db, L, r.bank_account_id, r.mode), Decimal(r.amount))
        v.add(L.get("tds_receivable", "TDS Receivable"), Decimal(r.tds_amount))
        v.add(L.get("gst_tds_receivable", "GST TDS Receivable"), Decimal(r.gst_tds_amount))
        v.add(L.get("write_off", "Discount Allowed"), Decimal(r.write_off))
        total = (
            Decimal(r.amount)
            + Decimal(r.tds_amount)
            + Decimal(r.gst_tds_amount)
            + Decimal(r.write_off)
        )
        v.add(L.get("client_advance", "Client Advances") if r.is_advance else party, -total)
        out.append(v)

    for p in fresh(Payment, Payment.on_date):
        if p.status != "paid":
            continue
        party = _party(db, db.get(Vendor, p.vendor_id).name)
        v = Voucher(
            p, "Payment", p.number, p.on_date, party, f"{p.mode.upper()} {p.ref_no or ''}".strip()
        )
        v.add(party, Decimal(p.amount))
        v.add(_bank(db, L, p.bank_account_id, p.mode), -Decimal(p.amount))
        out.append(v)

    for e in fresh(PettyCashEntry, PettyCashEntry.on_date):
        if e.status != "approved":
            continue
        acc = db.get(PettyCashAccount, e.account_id)
        person = L.get("petty_cash_prefix", "Petty Cash - ") + db.get(User, acc.user_id).full_name
        v = Voucher(
            e,
            "Journal" if e.kind == "expense" else "Contra",
            e.number,
            e.on_date,
            None,
            e.remark or e.kind,
        )
        if e.kind == "advance":
            v.add(person, Decimal(e.amount))
            v.add(_bank(db, L, e.bank_account_id, e.mode), -Decimal(e.amount))
        elif e.kind == "settlement":
            v.add(L.get("cash", "Cash"), Decimal(e.amount))
            v.add(person, -Decimal(e.amount))
        else:
            label = e.category.name if e.category else "Expense"
            v.narration = f"{label}: {e.paid_to or ''} {e.remark or ''}".strip()
            v.add(L.get("site_expenses", "Site Expenses"), Decimal(e.amount))
            v.add(person, -Decimal(e.amount))
        out.append(v)

    q = select(PayrollRun).where(PayrollRun.status == "locked")
    if not include_exported:
        q = q.where(PayrollRun.tally_exported_at.is_(None))
    for run in db.scalars(q):
        _, last = svc.ex.month_range(run.month)
        if not (start <= last <= end):
            continue
        v = Voucher(run, "Journal", f"PAYROLL-{run.month}", last, None, f"Salaries for {run.month}")
        tot = {
            k: sum((Decimal(getattr(p, k)) for p in run.payslips), ZERO)
            for k in (
                "gross",
                "pf_employee",
                "pf_employer",
                "esi_employee",
                "esi_employer",
                "pt",
                "advance_recovery",
                "net",
            )
        }
        v.add(L.get("salary", "Salaries"), tot["gross"] + tot["pf_employer"] + tot["esi_employer"])
        v.add(L.get("pf_payable", "PF Payable"), -(tot["pf_employee"] + tot["pf_employer"]))
        v.add(L.get("esi_payable", "ESI Payable"), -(tot["esi_employee"] + tot["esi_employer"]))
        v.add(L.get("pt_payable", "Professional Tax Payable"), -tot["pt"])
        v.add(L.get("staff_advance", "Staff Advances"), -tot["advance_recovery"])
        v.add(L.get("salary_payable", "Salary Payable"), -tot["net"])
        out.append(v)
    return sorted(out, key=lambda v: (v.on, v.vtype, v.number))


def to_xml(vs: list[Voucher], company: str | None = None) -> str:
    msgs = []
    for v in vs:
        entries = "".join(
            "<ALLLEDGERENTRIES.LIST>"
            f"<LEDGERNAME>{escape(ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{'Yes' if amount > 0 else 'No'}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{-amount:.2f}</AMOUNT>"
            "</ALLLEDGERENTRIES.LIST>"
            for ledger, amount in v.entries
        )
        party = f"<PARTYLEDGERNAME>{escape(v.party)}</PARTYLEDGERNAME>" if v.party else ""
        msgs.append(
            '<TALLYMESSAGE xmlns:UDF="TallyUDF">'
            f'<VOUCHER VCHTYPE="{escape(v.vtype)}" ACTION="Create">'
            f"<DATE>{v.on:%Y%m%d}</DATE><VOUCHERTYPENAME>{escape(v.vtype)}</VOUCHERTYPENAME>"
            f"<VOUCHERNUMBER>{escape(v.number)}</VOUCHERNUMBER>{party}"
            f"<NARRATION>{escape(v.narration)}</NARRATION>{entries}"
            "</VOUCHER></TALLYMESSAGE>"
        )
    static = (
        f"<STATICVARIABLES><SVCURRENTCOMPANY>{escape(company)}</SVCURRENTCOMPANY></STATICVARIABLES>"
        if company
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<ENVELOPE>'
        "<HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>"
        "<BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"
        f"{static}</REQUESTDESC><REQUESTDATA>{''.join(msgs)}</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>\n"
    )


def day_book_rows(vs: list[Voucher]) -> list[list]:
    rows = []
    for v in vs:
        for ledger, amount in v.entries:
            rows.append(
                [
                    v.on,
                    v.vtype,
                    v.number,
                    v.party,
                    ledger,
                    amount if amount > 0 else None,
                    -amount if amount < 0 else None,
                    v.narration,
                ]
            )
    return rows
