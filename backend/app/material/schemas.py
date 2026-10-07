from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Qty = Decimal
Pos = Field(gt=0)


# --- settings ------------------------------------------------------------------------------------


class PurchaseSettings(BaseModel):
    po_approval_limit: Decimal = Field(ge=0)
    allow_negative_stock: bool
    grn_approval_levels: int = Field(ge=1, le=2)
    po_tc_template_id: int | None = None
    freight_sac: str | None = Field(default=None, pattern=r"^[0-9]{4,8}$")  # None: unchanged


# --- stores --------------------------------------------------------------------------------------


class StoreIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str | None = None
    gstin_address_id: int | None = None


class StoreOut(BaseModel):
    id: int
    name: str
    kind: str
    site_id: int | None
    site_code: str | None
    address: str | None
    gstin_address_id: int | None
    is_active: bool
    items: int
    value: Decimal


class StockRow(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    unit: str
    qty: Decimal
    avg_rate: Decimal
    value: Decimal


class LedgerRow(BaseModel):
    id: int
    at: datetime
    product_id: int
    product_name: str
    qty: Decimal
    unit: str
    rate: Decimal
    value: Decimal
    ref_type: str
    ref_id: int | None
    ref_code: str | None
    note: str | None
    balance: Decimal


class AdjustIn(BaseModel):
    product_id: int
    qty: Decimal  # signed, in the product's unit
    rate: Decimal | None = Field(default=None, ge=0)  # an increase needs a rate
    kind: Literal["opening", "adjust"] = "adjust"
    note: str = Field(min_length=1)


# --- indents -------------------------------------------------------------------------------------


class IndentLineIn(BaseModel):
    product_id: int | None = None
    free_text: str | None = Field(default=None, max_length=300)
    qty: Decimal = Pos
    unit: str | None = None  # default: the product's unit
    boq_line_id: int | None = None
    area_scope_id: int | None = None
    remark: str | None = None

    @model_validator(mode="after")
    def product_or_text(self):
        if self.product_id is None and not (self.free_text or "").strip():
            raise ValueError("Pick a product or describe the material")
        if self.product_id is None and not self.unit:
            raise ValueError("Give the unit of a material that is not in the master")
        return self


class IndentIn(BaseModel):
    site_id: int
    required_by: date | None = None
    priority: Literal["normal", "urgent"] = "normal"
    remark: str | None = None
    lines: list[IndentLineIn] = Field(min_length=1)
    submit: bool = False


class IndentLineOut(BaseModel):
    id: int
    product_id: int | None
    product_name: str | None
    free_text: str | None
    qty: Decimal
    unit: str
    base_qty: Decimal
    base_unit: str | None
    boq_line_id: int | None
    area_scope_id: int | None
    remark: str | None
    ordered_qty: Decimal
    received_qty: Decimal


class IndentOut(BaseModel):
    id: int
    code: str
    site_id: int
    site_code: str
    site_name: str
    store_id: int
    required_by: date | None
    priority: str
    status: str
    remark: str | None
    reject_reason: str | None
    created_at: datetime
    created_by_name: str | None
    approved_at: datetime | None
    lines: list[IndentLineOut]
    can_edit: bool
    can_approve: bool


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1)


# --- RFQ -----------------------------------------------------------------------------------------


class RfqIn(BaseModel):
    indent_ids: list[int] = Field(min_length=1)
    vendor_ids: list[int] = Field(min_length=1)
    due_date: date | None = None
    remark: str | None = None


class QuoteIn(BaseModel):
    rfq_line_id: int
    vendor_id: int
    rate: Decimal = Field(ge=0)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)
    freight: Decimal = Field(default=Decimal(0), ge=0)
    lead_days: int | None = None
    remark: str | None = None


class VendorFreightIn(BaseModel):
    vendor_id: int
    freight: Decimal = Field(ge=0)


class QuotesIn(BaseModel):
    quotes: list[QuoteIn]
    vendor_freight: list[VendorFreightIn] = []


class ChoiceIn(BaseModel):
    rfq_line_id: int
    vendor_id: int
    reason: str | None = None


class QuoteCell(BaseModel):
    vendor_id: int
    rate: Decimal
    gst_percent: Decimal
    freight: Decimal
    lead_days: int | None
    landed_rate: Decimal  # rate + this line's share of freight, per unit
    lowest: bool


class RfqLineOut(BaseModel):
    id: int
    indent_line_id: int | None
    product_id: int
    product_name: str
    qty: Decimal
    unit: str
    chosen_vendor_id: int | None
    choice_reason: str | None
    quotes: list[QuoteCell]


class RfqVendorOut(BaseModel):
    vendor_id: int
    name: str
    freight: Decimal
    total: Decimal  # landed total of the lines it quoted


class RfqOut(BaseModel):
    id: int
    code: str
    due_date: date | None
    status: str
    remark: str | None
    created_at: datetime
    indent_ids: list[int]
    indent_codes: list[str]
    vendors: list[RfqVendorOut]
    lines: list[RfqLineOut]
    po_ids: list[int]


# --- POs -----------------------------------------------------------------------------------------


class PoLineIn(BaseModel):
    indent_line_id: int | None = None
    product_id: int
    qty: Decimal = Pos
    unit: str | None = None
    rate: Decimal = Field(ge=0)
    discount_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)


class PoChargeIn(BaseModel):
    kind: Literal["freight", "loading", "unloading", "packing", "other"]
    description: str | None = None
    amount: Decimal = Field(ge=0)
    gst_percent: Decimal = Field(default=Decimal(18), ge=0, le=28)
    add_to_cost: bool | None = None  # default: on for freight


class PoIn(BaseModel):
    vendor_id: int
    store_id: int
    from_gstin_id: int | None = None
    po_date: date | None = None
    expected_delivery: date | None = None
    payment_terms: str | None = None
    remark: str | None = None
    indent_ids: list[int] = []
    lines: list[PoLineIn] = Field(min_length=1)
    charges: list[PoChargeIn] = []


class PoLineOut(BaseModel):
    id: int
    indent_line_id: int | None
    product_id: int
    product_code: str
    product_name: str
    qty: Decimal
    unit: str
    base_qty: Decimal
    rate: Decimal
    discount_percent: Decimal
    gst_percent: Decimal
    amount: Decimal
    received_qty: Decimal
    hsn_code: str | None = None
    indent_qty: str | None = None  # the qty in the indented unit, e.g. "20 nos"


class PoChargeOut(BaseModel):
    id: int
    kind: str
    description: str | None
    amount: Decimal
    gst_percent: Decimal
    add_to_cost: bool


class PoOut(BaseModel):
    id: int
    code: str
    vendor_id: int
    vendor_name: str
    vendor_gstin: str | None
    from_gstin_id: int | None
    from_gstin: str | None
    store_id: int
    store_name: str
    rfq_id: int | None
    po_date: date
    expected_delivery: date | None
    payment_terms: str | None
    remark: str | None
    status: str
    interstate: bool
    approved_at: datetime | None
    approved_by_name: str | None
    sent_at: datetime | None
    created_at: datetime
    created_by_name: str | None
    subtotal: Decimal
    discount_total: Decimal
    taxable: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    charges_total: Decimal
    round_off: Decimal
    grand_total: Decimal
    indent_ids: list[int]
    lines: list[PoLineOut]
    charges: list[PoChargeOut]
    approval_limit: Decimal
    vendor_registered: bool = True
    gstin_missing: bool = False  # our GSTIN is not set: the PO cannot be sent
    warnings: list[str] = []
    needs_approver: bool
    can_edit: bool
    can_approve: bool


# --- GRN -----------------------------------------------------------------------------------------


class GrnLineIn(BaseModel):
    po_line_id: int | None = None
    product_id: int | None = None  # direct purchase
    unit: str | None = None
    received_qty: Decimal = Field(ge=0)
    invoice_qty: Decimal | None = Field(default=None, ge=0)
    accepted_qty: Decimal | None = Field(default=None, ge=0)  # default: all received
    rejected_qty: Decimal = Field(default=Decimal(0), ge=0)
    reason: str | None = None
    rate: Decimal | None = Field(default=None, ge=0)  # direct purchase: net rate per unit


class GrnIn(BaseModel):
    po_id: int | None = None
    store_id: int | None = None  # default: the PO's delivery store
    vendor_id: int | None = None  # direct purchase
    challan_no: str | None = None
    invoice_no: str | None = None
    invoice_date: date | None = None
    invoice_amount: Decimal | None = None
    vehicle_no: str | None = None
    received_at: date | None = None
    remark: str | None = None
    lines: list[GrnLineIn] = Field(min_length=1)
    submit: bool = False


class GrnLineOut(BaseModel):
    id: int
    po_line_id: int | None
    product_id: int
    product_name: str
    unit: str
    ordered_qty: Decimal | None
    received_qty: Decimal
    invoice_qty: Decimal | None
    accepted_qty: Decimal
    rejected_qty: Decimal
    reason: str | None
    rate: Decimal
    landed_rate: Decimal | None
    base_unit: str


class GrnPhotoOut(BaseModel):
    id: int
    kind: str
    filename: str


class GrnOut(BaseModel):
    id: int
    code: str
    po_id: int | None
    po_code: str | None
    store_id: int
    store_name: str
    vendor_id: int
    vendor_name: str
    challan_no: str | None
    invoice_no: str | None
    invoice_date: date | None
    invoice_amount: Decimal | None
    vehicle_no: str | None
    received_at: date
    remark: str | None
    status: str
    levels_required: int
    approvals: int
    reject_reason: str | None
    created_at: datetime
    created_by_name: str | None
    lines: list[GrnLineOut]
    photos: list[GrnPhotoOut]
    can_edit: bool
    can_approve: bool


# --- transfers and issues ------------------------------------------------------------------------


class TransferLineIn(BaseModel):
    product_id: int
    qty: Decimal = Pos
    unit: str | None = None


class TransferIn(BaseModel):
    from_store_id: int
    to_store_id: int
    vehicle_no: str | None = None
    transporter: str | None = None
    freight_amount: Decimal = Field(default=Decimal(0), ge=0)
    remark: str | None = None
    lines: list[TransferLineIn] = Field(min_length=1)
    dispatch: bool = False


class ReceiveLineIn(BaseModel):
    line_id: int
    qty_received: Decimal = Field(ge=0)
    shortage_reason: str | None = None


class ReceiveIn(BaseModel):
    lines: list[ReceiveLineIn]


class TransferLineOut(BaseModel):
    id: int
    product_id: int
    product_name: str
    unit: str
    qty_sent: Decimal
    qty_received: Decimal | None
    shortage_qty: Decimal
    shortage_reason: str | None
    rate: Decimal | None


class TransferOut(BaseModel):
    id: int
    code: str
    from_store_id: int
    from_store_name: str
    to_store_id: int
    to_store_name: str
    status: str
    vehicle_no: str | None
    transporter: str | None
    freight_amount: Decimal
    remark: str | None
    created_at: datetime
    dispatched_at: datetime | None
    received_at: datetime | None
    lines: list[TransferLineOut]
    can_dispatch: bool
    can_receive: bool


class IssueLineIn(BaseModel):
    product_id: int
    qty: Decimal = Pos
    unit: str | None = None


class IssueIn(BaseModel):
    kind: Literal["issue", "return"] = "issue"
    site_id: int
    store_id: int | None = None  # default: the site's store
    task_id: int | None = None
    area_scope_id: int | None = None
    issued_on: date | None = None
    remark: str | None = None
    lines: list[IssueLineIn] = Field(min_length=1)


class IssueLineOut(BaseModel):
    product_id: int
    product_name: str
    unit: str
    qty: Decimal
    rate: Decimal
    value: Decimal


class IssueOut(BaseModel):
    id: int
    code: str
    kind: str
    store_id: int
    store_name: str
    site_id: int
    task_id: int | None
    task_name: str | None
    area_scope_id: int | None
    issued_on: date
    remark: str | None
    created_at: datetime
    lines: list[IssueLineOut]


# --- freight -------------------------------------------------------------------------------------


class FreightBillIn(BaseModel):
    site_id: int
    direction: Literal["inbound", "godown_to_site", "other"] = "inbound"
    on_date: date
    amount: Decimal = Pos
    gst_percent: Decimal = Field(default=Decimal(0), ge=0, le=28)
    transporter: str | None = None
    vehicle_no: str | None = None
    from_place: str | None = None
    to_place: str | None = None
    bill_no: str | None = None
    remark: str | None = None


class FreightOut(BaseModel):
    id: int
    source: str
    ref_code: str | None
    site_id: int | None
    site_code: str | None
    direction: str
    on_date: date
    amount: Decimal
    gst_percent: Decimal
    transporter: str | None
    vehicle_no: str | None
    bill_no: str | None
    remark: str | None


class FreightReportRow(BaseModel):
    site_id: int | None
    site_code: str | None
    site_name: str | None
    month: str  # 2026-10
    inbound: Decimal
    godown_to_site: Decimal
    other: Decimal
    total: Decimal
