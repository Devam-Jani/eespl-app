"""Dashboards and analytics: settings, pre-computed summary tables (refreshed by the worker
nightly and on demand), progress snapshots for forecasts, alerts, weekly management reports and
the registry of invented demo rows.

Summary tables carry `as_of`; every tile shows it. They are a cache of numbers that can always be
recomputed from the records (tests check that they match the live queries).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

import app.crm.models  # noqa: F401  (leads)
import app.execution.models as ex
import app.finance.models as fin
import app.material.models as mat
import app.portal.models  # noqa: F401  (notifications, snags)
from app.crm.models import Lead
from app.masters.models import Tracked
from app.models import Base
from app.sites.models import Task
from app.tenders.models import Tender

Money = Numeric(16, 2)
Pct = Numeric(7, 2)

# Alert rules, with their defaults. `roles` get the alert (plus the site in-charge where a site is
# involved, and the item's owner where there is one).
ALERT_RULES: dict[str, dict[str, Any]] = {
    "dpr_missing": {"on": True, "after_hour": 20, "roles": ["office_admin"]},
    "behind_schedule": {"on": True, "roles": ["super_admin", "office_admin"]},
    "budget_head": {"on": True, "percent": 90, "roles": ["office_admin", "accounts"]},
    "invoice_overdue": {"on": True, "days": [30, 60, 90], "roles": ["accounts", "office_admin"]},
    "po_late": {"on": True, "roles": ["store_purchase"]},
    "low_stock": {"on": True, "roles": ["store_purchase"]},
    "petty_negative": {"on": True, "roles": ["accounts"]},
    "tender_due": {"on": True, "days": 2, "roles": ["estimator", "office_admin"]},
    "kylas_failing": {"on": True, "hours": 24, "roles": ["super_admin"]},
    "followup_overdue": {"on": True, "roles": ["office_admin"]},
}
RULE_LABELS = {
    "dpr_missing": "DPR missing after 8 pm",
    "behind_schedule": "Site behind schedule",
    "budget_head": "Cost passed a budget head",
    "invoice_overdue": "Invoice overdue",
    "po_late": "PO delivery late",
    "low_stock": "Low stock",
    "petty_negative": "Petty cash balance negative",
    "tender_due": "Tender due, not submitted",
    "kylas_failing": "Kylas sync failing",
    "followup_overdue": "Quotation follow-up overdue",
}


class AnalyticsSettings(Tracked, Base):
    """One row (id 1)."""

    __tablename__ = "analytics_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # a site is delayed when its progress is this many points behind the time elapsed
    delay_threshold_points: Mapped[Decimal] = mapped_column(Pct, server_default="15")
    # an acknowledged alert is not raised again for the same item for this many days
    ack_snooze_days: Mapped[int] = mapped_column(Integer, server_default="7")
    alert_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    weekly_report: Mapped[bool] = mapped_column(Boolean, server_default="true")
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerts_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SiteSummary(Base):
    """Per site: the heavy numbers behind the dashboards (billing, cost, progress, forecast)."""

    __tablename__ = "site_summaries"

    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false", index=True)
    historic: Mapped[bool] = mapped_column(Boolean, server_default="false")  # Powerplay import
    status: Mapped[str] = mapped_column(String(12))
    client_id: Mapped[int | None] = mapped_column(Integer)
    client_type: Mapped[str | None] = mapped_column(String(20))
    region: Mapped[str | None] = mapped_column(String(100))  # the site's state
    salesperson_id: Mapped[uuid.UUID | None] = mapped_column()
    system_id: Mapped[int | None] = mapped_column(Integer)  # the biggest system on its BOQ
    start_date: Mapped[date | None] = mapped_column(Date)
    target_date: Mapped[date | None] = mapped_column(Date)
    progress: Mapped[Decimal] = mapped_column(Pct, server_default="0")
    elapsed: Mapped[Decimal | None] = mapped_column(Pct)  # % of planned time gone
    rate_per_day: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))  # % per day, last 30 d
    forecast_end: Mapped[date | None] = mapped_column(Date)
    delayed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    delay_reason: Mapped[str | None] = mapped_column(String(40))
    contract_value: Mapped[Decimal | None] = mapped_column(Money)
    billed: Mapped[Decimal] = mapped_column(Money, server_default="0")  # taxable, less credit notes
    certified: Mapped[Decimal] = mapped_column(Money, server_default="0")
    received: Mapped[Decimal] = mapped_column(Money, server_default="0")
    outstanding: Mapped[Decimal] = mapped_column(Money, server_default="0")
    retention_held: Mapped[Decimal] = mapped_column(Money, server_default="0")
    cost: Mapped[Decimal] = mapped_column(Money, server_default="0")  # without staff salary
    cost_heads: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    salary_cost: Mapped[Decimal] = mapped_column(Money, server_default="0")
    budget_heads: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    tender_margin: Mapped[Decimal | None] = mapped_column(Pct)  # quoted margin %
    open_snags: Mapped[int] = mapped_column(Integer, server_default="0")
    closed_snags: Mapped[int] = mapped_column(Integer, server_default="0")
    snag_close_days: Mapped[Decimal | None] = mapped_column(Numeric(8, 1))
    man_days: Mapped[Decimal] = mapped_column(Numeric(12, 1), server_default="0")
    labour_cost: Mapped[Decimal] = mapped_column(Money, server_default="0")
    area_done: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")  # sqm
    material_value: Mapped[Decimal] = mapped_column(Money, server_default="0")  # received
    freight: Mapped[Decimal] = mapped_column(Money, server_default="0")


class MonthlySummary(Base):
    """Per month and site (site NULL: rows not tied to a site): billing, money in, cost."""

    __tablename__ = "monthly_summaries"
    __table_args__ = (
        UniqueConstraint("month", "site_id", "is_demo", postgresql_nulls_not_distinct=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    month: Mapped[date] = mapped_column(Date, index=True)  # first day of the month
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")
    billed: Mapped[Decimal] = mapped_column(Money, server_default="0")  # taxable less CNs
    invoiced: Mapped[Decimal] = mapped_column(Money, server_default="0")  # receivable raised
    credited: Mapped[Decimal] = mapped_column(Money, server_default="0")  # credit notes, gross
    received: Mapped[Decimal] = mapped_column(Money, server_default="0")  # receipts, money in
    settled: Mapped[Decimal] = mapped_column(Money, server_default="0")  # allocated to invoices
    cost: Mapped[Decimal] = mapped_column(Money, server_default="0")  # without staff salary
    salary_cost: Mapped[Decimal] = mapped_column(Money, server_default="0")
    man_days: Mapped[Decimal] = mapped_column(Numeric(12, 1), server_default="0")
    labour_cost: Mapped[Decimal] = mapped_column(Money, server_default="0")
    marked: Mapped[int] = mapped_column(Integer, server_default="0")  # attendance rows
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceSummary(Base):
    """Per issued invoice: what is still owed, the retention in it, the due part and its age."""

    __tablename__ = "invoice_summaries"

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("tax_invoices.id", ondelete="CASCADE"), primary_key=True
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false", index=True)
    site_id: Mapped[int | None] = mapped_column(Integer, index=True)
    client_id: Mapped[int] = mapped_column(Integer, index=True)
    invoice_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    total: Mapped[Decimal] = mapped_column(Money)
    outstanding: Mapped[Decimal] = mapped_column(Money)
    retention_held: Mapped[Decimal] = mapped_column(Money)
    due: Mapped[Decimal] = mapped_column(Money)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProgressSnapshot(Base):
    """A site's overall progress on a day (written nightly): the history behind forecasts."""

    __tablename__ = "progress_snapshots"

    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True
    )
    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    percent: Mapped[Decimal] = mapped_column(Pct)


class KpiSnapshot(Base):
    """The management tiles as of a day: the previous-period comparison for stock values."""

    __tablename__ = "kpi_snapshots"

    on_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint("rule", "item_key", "day"),
        CheckConstraint(
            "rule IN (" + ", ".join(f"'{r}'" for r in ALERT_RULES) + ")", name="rule_valid"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    rule: Mapped[str] = mapped_column(String(20), index=True)
    item_key: Mapped[str] = mapped_column(String(60))  # e.g. invoice:12:60
    day: Mapped[date] = mapped_column(Date, index=True)  # IST
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    link: Mapped[str | None] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(8), server_default="warn")  # info, warn, high
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # superseded
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class AlertRecipient(Base):
    __tablename__ = "alert_recipients"

    alert_id: Mapped[int] = mapped_column(
        ForeignKey("alerts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class WeeklyReport(Base):
    """The Monday management summary (its numbers; the PDF is drawn from them on download)."""

    __tablename__ = "weekly_reports"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    week_start: Mapped[date] = mapped_column(Date, unique=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DemoRow(Base):
    """Every row the demo seed inserted (so --purge removes exactly those and nothing else)."""

    __tablename__ = "demo_rows"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    table_name: Mapped[str] = mapped_column(String(60))
    row_key: Mapped[str] = mapped_column(Text)  # the primary key, as text (composite: a,b)


# --- indexes the dashboard queries need on existing tables ---------------------------------------

Index("ix_tax_invoices_against_id", fin.TaxInvoice.against_id)
Index("ix_receipt_allocations_invoice_id", fin.ReceiptAllocation.invoice_id)
Index("ix_receipts_site_id", fin.Receipt.site_id)
Index("ix_vendor_bills_status_due", fin.VendorBill.status, fin.VendorBill.due_date)
Index("ix_payment_allocations_bill", fin.PaymentAllocation.vendor_bill_id)
Index("ix_ra_bills_site_status", fin.RaBill.site_id, fin.RaBill.status)
Index(
    "ix_purchase_orders_status_delivery",
    mat.PurchaseOrder.status,
    mat.PurchaseOrder.expected_delivery,
)
Index("ix_purchase_orders_po_date", mat.PurchaseOrder.po_date)
Index("ix_po_lines_product", mat.PoLine.product_id)
Index("ix_site_issues_site_date", mat.SiteIssue.site_id, mat.SiteIssue.issued_on)
Index("ix_freight_entries_site_date", mat.FreightEntry.site_id, mat.FreightEntry.on_date)
Index("ix_stock_ledger_product", mat.StockLedger.product_id)
Index("ix_attendance_site_date", ex.Attendance.site_id, ex.Attendance.on_date)
Index("ix_equipment_usage_site_date", ex.EquipmentUsage.site_id, ex.EquipmentUsage.on_date)
Index("ix_site_costs_site_date", ex.SiteCost.site_id, ex.SiteCost.on_date)
Index("ix_leads_owner_status", Lead.owner_id, Lead.status)
Index("ix_leads_next_follow_up", Lead.next_follow_up)
Index("ix_leads_created_at", Lead.created_at)
Index("ix_tenders_status_due", Tender.status, Tender.due_on)
Index("ix_tenders_owner", Tender.owner_id)
Index("ix_tenders_decided_at", Tender.decided_at)
Index("ix_tasks_site_status", Task.site_id, Task.status)
