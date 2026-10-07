"""Finance: client contracts and RA bills, tax invoices and credit notes, receipts, vendor bills
and payments, subcontractor RA bills, petty cash and expenses, payroll and labour wage payments,
Tally export.

Every finance number runs per financial year (1 Apr - 31 Mar) from doc_sequences and never
repeats; a cancelled document keeps its number. `tally_exported_at` marks a voucher that went into
a Tally export, so the next export skips it unless asked to include exported ones.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

import app.execution.models  # noqa: F401  (work orders, measurements)
from app.masters.models import Client, Tracked, Vendor
from app.models import Base

Qty = Numeric(14, 3)
Money = Numeric(14, 2)
Rate = Numeric(14, 4)
Pct = Numeric(6, 3)

PAY_MODES = ("neft", "rtgs", "cheque", "upi", "cash")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def money_col(**kw):
    return mapped_column(Money, server_default="0", **kw)


class FinanceSettings(Tracked, Base):
    """One row (id 1): numbering, tax rules, limits, payroll statutory rates, Tally ledgers."""

    __tablename__ = "finance_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, server_default="1")
    invoice_prefix: Mapped[str] = mapped_column(String(6), server_default="EESPL")
    works_sac: Mapped[str] = mapped_column(String(8), server_default="9954")
    match_tolerance_percent: Mapped[Decimal] = mapped_column(Pct, server_default="1")
    payment_approval_limit: Mapped[Decimal] = mapped_column(Money, server_default="100000")
    expense_photo_limit: Mapped[Decimal] = mapped_column(Money, server_default="500")
    # {vendor type: {"section": "194C", "individual": 1, "other": 2}}
    tds_rules: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pf_percent: Mapped[Decimal] = mapped_column(Pct, server_default="12")
    pf_wage_cap: Mapped[Decimal] = mapped_column(Money, server_default="15000")
    esi_threshold: Mapped[Decimal] = mapped_column(Money, server_default="21000")
    esi_employee_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0.75")
    esi_employer_percent: Mapped[Decimal] = mapped_column(Pct, server_default="3.25")
    # [{"from": 0, "to": 11999, "amount": 0}, {"from": 12000, "to": null, "amount": 200}]
    pt_slabs: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    tally_ledgers: Mapped[dict[str, Any]] = mapped_column(JSONB)
    party_ledgers: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


# --- client side ---------------------------------------------------------------------------------


class ClientContract(Tracked, Base):
    """The agreement with the client for one site: agreed BOQ rates and the commercial terms."""

    __tablename__ = "client_contracts"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), unique=True)
    tender_id: Mapped[int | None] = mapped_column(ForeignKey("tenders.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="RESTRICT"))
    contract_value: Mapped[Decimal] = money_col()
    retention_percent: Mapped[Decimal] = mapped_column(Pct, server_default="5")
    advance_amount: Mapped[Decimal] = money_col()
    advance_recovery_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    tds_percent: Mapped[Decimal] = mapped_column(Pct, server_default="2")  # 194C by the client
    gst_tds_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")  # 2 % (government)
    gst_percent: Mapped[Decimal] = mapped_column(Pct, server_default="18")
    sac: Mapped[str] = mapped_column(String(8), server_default="9954")
    place_of_supply: Mapped[str | None] = mapped_column(String(100))  # the state
    client_gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address: Mapped[str | None] = mapped_column(Text)
    from_gstin_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_gstins.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)

    client: Mapped[Client | None] = relationship(lazy="joined")
    lines: Mapped[list["ContractLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ContractLine.sort_order",
    )


class ContractLine(Tracked, Base):
    __tablename__ = "contract_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_contracts.id", ondelete="CASCADE"), index=True
    )
    boq_line_id: Mapped[int | None] = mapped_column(ForeignKey("boq_lines.id", ondelete="SET NULL"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    item_no: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20))
    qty: Mapped[Decimal] = mapped_column(Qty)
    rate: Mapped[Decimal] = mapped_column(Rate)
    is_extra: Mapped[bool] = mapped_column(Boolean, server_default="false")  # beyond the BOQ
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


RA_STATUSES = ("draft", "submitted", "certified", "invoiced", "cancelled")


class RaBill(Tracked, Base):
    """A running-account bill to the client. Submitted and client-certified amounts are both
    kept; deductions (retention, advance recovery, other) follow the certified amount."""

    __tablename__ = "ra_bills"
    __table_args__ = (
        CheckConstraint(_in("status", RA_STATUSES), name="status_valid"),
        UniqueConstraint("contract_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)  # RA-S-2026-0001-01
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_contracts.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10), server_default="draft", index=True)
    gross: Mapped[Decimal] = money_col()  # submitted, this bill
    certified_gross: Mapped[Decimal | None] = mapped_column(Money)
    retention: Mapped[Decimal] = money_col()
    advance_recovery: Mapped[Decimal] = money_col()
    other_deduction: Mapped[Decimal] = money_col()
    other_deduction_remark: Mapped[str | None] = mapped_column(Text)
    net: Mapped[Decimal] = money_col()  # (certified, else submitted) gross less deductions
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certified_by_client: Mapped[str | None] = mapped_column(String(200))
    remark: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["RaBillLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RaBillLine.id",
    )


class RaBillLine(Base):
    __tablename__ = "ra_bill_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    ra_bill_id: Mapped[int] = mapped_column(
        ForeignKey("ra_bills.id", ondelete="CASCADE"), index=True
    )
    contract_line_id: Mapped[int] = mapped_column(
        ForeignKey("contract_lines.id", ondelete="RESTRICT")
    )
    previous_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")
    suggested_qty: Mapped[Decimal] = mapped_column(Qty, server_default="0")
    qty: Mapped[Decimal] = mapped_column(Qty)  # submitted, this bill
    certified_qty: Mapped[Decimal | None] = mapped_column(Qty)
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount: Mapped[Decimal] = money_col()
    certified_amount: Mapped[Decimal | None] = mapped_column(Money)


class TaxInvoice(Tracked, Base):
    """A GST tax invoice (kind invoice) or a credit note against one (kind credit_note)."""

    __tablename__ = "tax_invoices"
    __table_args__ = (
        CheckConstraint("kind IN ('invoice', 'credit_note')", name="kind_valid"),
        CheckConstraint("status IN ('issued', 'cancelled')", name="status_valid"),
        CheckConstraint("length(number) <= 16", name="number_16_chars"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(16), unique=True)  # EESPL/26-27/0001
    kind: Mapped[str] = mapped_column(String(12), server_default="invoice")
    status: Mapped[str] = mapped_column(String(10), server_default="issued")
    invoice_date: Mapped[date] = mapped_column(Date, index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="RESTRICT"), index=True
    )
    contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_contracts.id", ondelete="RESTRICT")
    )
    ra_bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("ra_bills.id", ondelete="RESTRICT"), unique=True
    )
    against_id: Mapped[int | None] = mapped_column(  # a credit note's invoice
        ForeignKey("tax_invoices.id", ondelete="RESTRICT")
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    client_gstin: Mapped[str | None] = mapped_column(String(15))
    billing_address: Mapped[str | None] = mapped_column(Text)
    place_of_supply: Mapped[str | None] = mapped_column(String(100))
    from_gstin_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_gstins.id", ondelete="SET NULL")
    )
    interstate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    taxable: Mapped[Decimal] = money_col()
    cgst: Mapped[Decimal] = money_col()
    sgst: Mapped[Decimal] = money_col()
    igst: Mapped[Decimal] = money_col()
    round_off: Mapped[Decimal] = money_col()
    total: Mapped[Decimal] = money_col()
    # deductions the client makes when paying (from the RA bill); outstanding net of them
    retention: Mapped[Decimal] = money_col()
    advance_recovery: Mapped[Decimal] = money_col()
    other_deduction: Mapped[Decimal] = money_col()
    remark: Mapped[str | None] = mapped_column(Text)
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    client: Mapped[Client] = relationship(lazy="joined")
    lines: Mapped[list["InvoiceLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvoiceLine.id",
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("tax_invoices.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    sac: Mapped[str | None] = mapped_column(String(8))
    qty: Mapped[Decimal | None] = mapped_column(Qty)
    unit: Mapped[str | None] = mapped_column(String(20))
    rate: Mapped[Decimal | None] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)
    gst_percent: Mapped[Decimal] = mapped_column(Pct)


class Receipt(Tracked, Base):
    """Money (and tax credit) from a client. received + tds + gst_tds + write_off is spread over
    invoices (allocations); an advance receipt (mobilisation) stays unallocated."""

    __tablename__ = "receipts"
    __table_args__ = (CheckConstraint(_in("mode", PAY_MODES), name="mode_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # RCT/26-27/0001
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    on_date: Mapped[date] = mapped_column(Date, index=True)
    mode: Mapped[str] = mapped_column(String(8))
    ref_no: Mapped[str | None] = mapped_column(String(60))
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_bank_accounts.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal] = money_col()  # money received
    tds_amount: Mapped[Decimal] = money_col()  # income-tax TDS (194C) by the client
    gst_tds_amount: Mapped[Decimal] = money_col()  # GST TDS (government clients)
    write_off: Mapped[Decimal] = money_col()
    write_off_reason: Mapped[str | None] = mapped_column(Text)
    is_advance: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_retention: Mapped[bool] = mapped_column(Boolean, server_default="false")
    remark: Mapped[str | None] = mapped_column(Text)
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    allocations: Mapped[list["ReceiptAllocation"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class ReceiptAllocation(Base):
    __tablename__ = "receipt_allocations"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("receipts.id", ondelete="CASCADE"), index=True
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("tax_invoices.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money)


class RetentionRelease(Tracked, Base):
    """The client releases (part of) the retention held on a site: that amount falls due."""

    __tablename__ = "retention_releases"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    on_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    remark: Mapped[str | None] = mapped_column(Text)


# --- vendor side ---------------------------------------------------------------------------------

VB_STATUSES = ("draft", "approved", "partly_paid", "paid", "cancelled")


class VendorBill(Tracked, Base):
    """A supplier's invoice: from GRNs (three-way matched), direct (service, freight), or a
    subcontractor RA bill."""

    __tablename__ = "vendor_bills"
    __table_args__ = (
        CheckConstraint(_in("status", VB_STATUSES), name="status_valid"),
        CheckConstraint(
            "kind IN ('material', 'service', 'freight', 'subcontract', 'retention')",
            name="kind_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # VB/26-27/0001
    kind: Mapped[str] = mapped_column(String(12), server_default="material")
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    bill_no: Mapped[str] = mapped_column(String(60))  # the vendor's invoice number
    bill_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    interstate: Mapped[bool] = mapped_column(Boolean, server_default="false")
    itc_eligible: Mapped[bool] = mapped_column(Boolean, server_default="true")
    taxable: Mapped[Decimal] = money_col()
    cgst: Mapped[Decimal] = money_col()
    sgst: Mapped[Decimal] = money_col()
    igst: Mapped[Decimal] = money_col()
    round_off: Mapped[Decimal] = money_col()
    total: Mapped[Decimal] = money_col()
    tds_section: Mapped[str | None] = mapped_column(String(8))
    tds_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    tds_amount: Mapped[Decimal] = money_col()
    payable: Mapped[Decimal] = money_col()  # total less TDS (and recoveries on subcon bills)
    status: Mapped[str] = mapped_column(String(12), server_default="draft", index=True)
    match_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    lines: Mapped[list["VendorBillLine"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VendorBillLine.id",
    )


class VendorBillGrn(Base):
    __tablename__ = "vendor_bill_grns"

    vendor_bill_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="CASCADE"), primary_key=True
    )
    grn_id: Mapped[int] = mapped_column(
        ForeignKey("grns.id", ondelete="RESTRICT"), primary_key=True
    )


class VendorBillLine(Base):
    __tablename__ = "vendor_bill_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    vendor_bill_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="CASCADE"), index=True
    )
    grn_line_id: Mapped[int | None] = mapped_column(ForeignKey("grn_lines.id", ondelete="SET NULL"))
    po_line_id: Mapped[int | None] = mapped_column(ForeignKey("po_lines.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(Text)
    hsn_code: Mapped[str | None] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(Qty, server_default="1")
    unit: Mapped[str | None] = mapped_column(String(20))
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)
    gst_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    # for a matched line: what the GRN accepted and what the PO agreed
    grn_qty: Mapped[Decimal | None] = mapped_column(Qty)
    po_rate: Mapped[Decimal | None] = mapped_column(Rate)


class Payment(Tracked, Base):
    """Money to a vendor or subcontractor. Above the approval limit it waits for
    payables.approve; spread over bills (partial payment allowed)."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(_in("mode", PAY_MODES), name="mode_valid"),
        CheckConstraint("status IN ('pending_approval', 'paid', 'cancelled')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # PAY/26-27/0001
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date, index=True)
    mode: Mapped[str] = mapped_column(String(8))
    ref_no: Mapped[str | None] = mapped_column(String(60))
    bank_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("company_bank_accounts.id", ondelete="SET NULL")
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(16), server_default="paid")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remark: Mapped[str | None] = mapped_column(Text)
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vendor: Mapped[Vendor] = relationship(lazy="joined")
    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    vendor_bill_id: Mapped[int] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="RESTRICT"), index=True
    )
    amount: Mapped[Decimal] = mapped_column(Money)


class SubconBill(Tracked, Base):
    """A subcontractor's RA bill from verified WO measurements not billed before. Approving it
    raises the vendor bill that is paid like any other."""

    __tablename__ = "subcon_bills"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'approved', 'cancelled')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # SB/26-27/0001
    wo_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="RESTRICT"), index=True
    )
    bill_date: Mapped[date] = mapped_column(Date)
    gross: Mapped[Decimal] = money_col()
    retention: Mapped[Decimal] = money_col()
    tds: Mapped[Decimal] = money_col()
    material_recovery: Mapped[Decimal] = money_col()
    advance_recovery: Mapped[Decimal] = money_col()
    gst_percent: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    gst: Mapped[Decimal] = money_col()
    net: Mapped[Decimal] = money_col()
    status: Mapped[str] = mapped_column(String(10), server_default="draft")
    vendor_bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)


class SubconBillLine(Base):
    """One verified measurement on the bill (unique: a measurement is billed once)."""

    __tablename__ = "subcon_bill_lines"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    subcon_bill_id: Mapped[int] = mapped_column(
        ForeignKey("subcon_bills.id", ondelete="CASCADE"), index=True
    )
    measurement_id: Mapped[int] = mapped_column(
        ForeignKey("wo_measurements.id", ondelete="RESTRICT"), unique=True
    )
    qty: Mapped[Decimal] = mapped_column(Qty)
    rate: Mapped[Decimal] = mapped_column(Rate)
    amount: Mapped[Decimal] = mapped_column(Money)


class SubconRetentionRelease(Tracked, Base):
    __tablename__ = "subcon_retention_releases"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    wo_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="RESTRICT"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    vendor_bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendor_bills.id", ondelete="SET NULL")
    )


# --- petty cash and expenses ---------------------------------------------------------------------


class ExpenseCategory(Tracked, Base):
    __tablename__ = "expense_categories"
    __table_args__ = (
        CheckConstraint(
            "budget_head IN ('material', 'labour', 'subcontract', 'equipment', 'freight', 'other')",
            name="head_valid",
        ),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    budget_head: Mapped[str] = mapped_column(String(12), server_default="other")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


class PettyCashAccount(Tracked, Base):
    __tablename__ = "petty_cash_accounts"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")


PETTY_KINDS = ("advance", "expense", "settlement")


class PettyCashEntry(Tracked, Base):
    """advance (+): money given to the person (top-up); expense (-): spent once approved;
    settlement (-): cash handed back. Balance = advances - approved expenses - settlements."""

    __tablename__ = "petty_cash_entries"
    __table_args__ = (
        CheckConstraint(_in("kind", PETTY_KINDS), name="kind_valid"),
        CheckConstraint("status IN ('submitted', 'approved', 'rejected')", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)  # PC/26-27/0001
    account_id: Mapped[int] = mapped_column(
        ForeignKey("petty_cash_accounts.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10))
    on_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT")
    )
    paid_to: Mapped[str | None] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(8), server_default="cash")
    bank_account_id: Mapped[int | None] = mapped_column(  # where an advance came from
        ForeignKey("company_bank_accounts.id", ondelete="SET NULL")
    )
    photo_path: Mapped[str | None] = mapped_column(String(400))
    remark: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), server_default="approved")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reject_reason: Mapped[str | None] = mapped_column(Text)
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    category: Mapped[ExpenseCategory | None] = relationship(lazy="joined")


# --- payroll -------------------------------------------------------------------------------------


class SalaryStructure(Tracked, Base):
    """A person's monthly salary from a date (the latest one in force applies)."""

    __tablename__ = "salary_structures"
    __table_args__ = (UniqueConstraint("user_id", "effective_from"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    effective_from: Mapped[date] = mapped_column(Date)
    basic: Mapped[Decimal] = mapped_column(Money)
    hra: Mapped[Decimal] = money_col()
    other_allowance: Mapped[Decimal] = money_col()
    pf: Mapped[bool] = mapped_column(Boolean, server_default="true")
    esi: Mapped[bool] = mapped_column(Boolean, server_default="true")
    pt_state: Mapped[str] = mapped_column(String(50), server_default="Gujarat")
    monthly_ctc: Mapped[Decimal] = money_col()


class StaffAdvance(Tracked, Base):
    __tablename__ = "staff_advances"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    on_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    recovered_in_payslip_id: Mapped[int | None] = mapped_column(
        ForeignKey("payslips.id", ondelete="SET NULL")
    )
    remark: Mapped[str | None] = mapped_column(Text)


class PayrollRun(Tracked, Base):
    __tablename__ = "payroll_runs"
    __table_args__ = (CheckConstraint("status IN ('draft', 'locked')", name="status_valid"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), unique=True)  # 2026-10
    status: Mapped[str] = mapped_column(String(8), server_default="draft")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    paid_mode: Mapped[str | None] = mapped_column(String(8))
    paid_ref: Mapped[str | None] = mapped_column(String(60))
    tally_exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    payslips: Mapped[list["Payslip"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", passive_deletes=True, order_by="Payslip.id"
    )


class Payslip(Tracked, Base):
    __tablename__ = "payslips"
    __table_args__ = (UniqueConstraint("run_id", "user_id"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_runs.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    structure_id: Mapped[int] = mapped_column(
        ForeignKey("salary_structures.id", ondelete="RESTRICT")
    )
    days_in_month: Mapped[int] = mapped_column(Integer)
    worked_days: Mapped[int] = mapped_column(Integer, server_default="0")  # from staff check-ins
    leave_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), server_default="0")
    lop_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), server_default="0")
    paid_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    basic: Mapped[Decimal] = money_col()
    hra: Mapped[Decimal] = money_col()
    other_allowance: Mapped[Decimal] = money_col()
    gross: Mapped[Decimal] = money_col()
    pf_employee: Mapped[Decimal] = money_col()
    pf_employer: Mapped[Decimal] = money_col()
    esi_employee: Mapped[Decimal] = money_col()
    esi_employer: Mapped[Decimal] = money_col()
    pt: Mapped[Decimal] = money_col()
    advance_recovery: Mapped[Decimal] = money_col()
    net: Mapped[Decimal] = money_col()
    site_days: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")  # {site id: days}


class LabourAdvance(Tracked, Base):
    __tablename__ = "labour_advances"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    labour_id: Mapped[int] = mapped_column(ForeignKey("labour.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    on_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)
    recovered_in_id: Mapped[int | None] = mapped_column(
        ForeignKey("labour_wage_payments.id", ondelete="SET NULL")
    )


class LabourWagePayment(Tracked, Base):
    """Wages of one worker at one site for a period, from the muster roll, less advances."""

    __tablename__ = "labour_wage_payments"
    __table_args__ = (
        UniqueConstraint("labour_id", "site_id", "period_from"),
        CheckConstraint("status IN ('due', 'paid')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    labour_id: Mapped[int] = mapped_column(ForeignKey("labour.id", ondelete="RESTRICT"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="RESTRICT"), index=True)
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    days: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    ot_hours: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    wage_due: Mapped[Decimal] = mapped_column(Money)
    advances_recovered: Mapped[Decimal] = money_col()
    net: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(4), server_default="due")
    paid_on: Mapped[date | None] = mapped_column(Date)
    mode: Mapped[str | None] = mapped_column(String(8))
    ref_no: Mapped[str | None] = mapped_column(String(60))


class TallyExport(Tracked, Base):
    __tablename__ = "tally_exports"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    vouchers: Mapped[int] = mapped_column(Integer)
    include_exported: Mapped[bool] = mapped_column(Boolean, server_default="false")
