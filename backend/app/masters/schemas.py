import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.masters.models import (
    CATEGORY_KINDS,
    CLIENT_TYPES,
    LABOUR_UNITS,
    TAG_MODULES,
    VENDOR_TYPES,
)

T = TypeVar("T")

ClientType = Literal[CLIENT_TYPES]  # type: ignore[valid-type]
LabourUnit = Literal[LABOUR_UNITS]  # type: ignore[valid-type]
NonNegative = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=4)]
Percent = Annotated[Decimal, Field(ge=0, lt=1000, max_digits=6, decimal_places=2)]
Name = Annotated[str, Field(min_length=1, max_length=200)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


# --- GSTIN / PAN ---

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_digit(first14: str) -> str:
    """GSTIN checksum (mod 36 Luhn variant) over the first 14 characters."""
    total = 0
    for i, ch in enumerate(first14):
        product = _GST_CHARS.index(ch) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def validate_gstin(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    value = value.upper().replace(" ", "")
    if not GSTIN_RE.match(value):
        raise ValueError("GSTIN must look like 27AAPFU0939F1ZV (15 characters)")
    if gstin_check_digit(value[:14]) != value[14]:
        raise ValueError("GSTIN check digit is wrong; please re-check the number")
    return value


def validate_pan(value: str | None) -> str | None:
    value = _blank_to_none(value)
    if value is None:
        return None
    value = value.upper().replace(" ", "")
    if not PAN_RE.match(value):
        raise ValueError("PAN must look like AAPFU0939F (10 characters)")
    return value


# --- clients ---


class ContactIn(BaseModel):
    name: Name
    designation: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=50)
    email: EmailStr | None = None
    is_primary: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        return _blank_to_none(v) if isinstance(v, str) else v


class ContactOut(ORM):
    id: int
    name: str
    designation: str | None
    phone: str | None
    email: str | None
    is_primary: bool


def _one_primary(contacts: list[ContactIn] | None) -> None:
    if contacts and sum(c.is_primary for c in contacts) > 1:
        raise ValueError("Only one contact can be primary")


class ClientFields(BaseModel):
    gstin: str | None = None
    pan: str | None = None
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    _gstin = field_validator("gstin")(validate_gstin)
    _pan = field_validator("pan")(validate_pan)

    @model_validator(mode="after")
    def _pan_matches_gstin(self):
        if self.gstin and self.pan and self.gstin[2:12] != self.pan:
            raise ValueError("PAN does not match the PAN inside the GSTIN")
        return self


class ClientIn(ClientFields):
    name: Name
    type: ClientType = "other"
    is_active: bool = True
    contacts: list[ContactIn] = []

    @model_validator(mode="after")
    def _contacts(self):
        _one_primary(self.contacts)
        return self


class ClientUpdate(ClientFields):
    name: Name | None = None
    type: ClientType | None = None
    is_active: bool | None = None
    contacts: list[ContactIn] | None = None  # when given, replaces all contacts

    @model_validator(mode="after")
    def _contacts(self):
        _one_primary(self.contacts)
        return self


class ClientOut(ORM):
    id: int
    name: str
    type: str
    gstin: str | None
    pan: str | None
    address: str | None
    city: str | None
    state: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    created_by: str | None = None
    contacts: list[ContactOut]

    @field_validator("created_by", mode="before")
    @classmethod
    def _uuid(cls, v):
        return str(v) if v is not None else None


# --- products ---


class PriceIn(BaseModel):
    purchase_rate: NonNegative
    freight_per_unit: NonNegative = Decimal(0)
    effective_from: date = Field(default_factory=date.today)
    note: str | None = None


class PriceOut(ORM):
    id: int
    purchase_rate: Decimal
    freight_per_unit: Decimal
    effective_from: date
    note: str | None
    created_at: datetime


class ProductIn(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: Name
    brand: str | None = Field(default=None, max_length=100)
    # a material category, by id or by name (case-insensitive)
    category_id: int | None = None
    category: str | None = Field(default=None, max_length=100)
    unit: str
    pack_size: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    gst_percent: Percent = Decimal(18)
    is_active: bool = True


class ProductUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: Name | None = None
    brand: str | None = Field(default=None, max_length=100)
    category_id: int | None = None
    category: str | None = Field(default=None, max_length=100)
    unit: str | None = None
    pack_size: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    gst_percent: Percent | None = None
    is_active: bool | None = None


class ProductCost(BaseModel):
    """Only returned to callers with tender.margin."""

    current_price: PriceOut | None


class ProductOut(ORM):
    id: int
    code: str
    name: str
    brand: str | None
    category_id: int | None
    category: str | None
    unit: str
    pack_size: Decimal | None
    gst_percent: Decimal
    is_active: bool
    cost: ProductCost | None = None

    @field_validator("category", mode="before")
    @classmethod
    def _category_name(cls, v):
        return getattr(v, "name", v)


# --- systems ---


class ComponentIn(BaseModel):
    product_id: int
    consumption_per_unit: NonNegative
    wastage_percent: Percent = Decimal(0)


class SystemFields(BaseModel):
    description: str | None = None
    surface_prep_per_unit: NonNegative | None = None
    labour_rate: NonNegative | None = None
    labour_unit: LabourUnit | None = None
    default_margin_percent: Percent | None = None
    is_active: bool | None = None


class SystemIn(SystemFields):
    code: str = Field(min_length=1, max_length=50)
    name: Name
    unit: str = "sqm"
    components: list[ComponentIn] = []


class SystemUpdate(SystemFields):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: Name | None = None
    unit: str | None = None
    components: list[ComponentIn] | None = None  # when given, replaces all components


class ComponentPublic(BaseModel):
    product_id: int
    product_code: str
    product_name: str
    brand: str | None
    unit: str


class ComponentCostOut(ComponentPublic):
    consumption_per_unit: Decimal
    wastage_percent: Decimal


class SystemCost(BaseModel):
    """Only returned to callers with tender.margin."""

    surface_prep_per_unit: Decimal
    labour_rate: Decimal
    labour_unit: str
    default_margin_percent: Decimal
    components: list[ComponentCostOut]


class SystemOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    unit: str
    is_active: bool
    rate: Decimal | None  # final selling rate at the default margin, today's prices
    rate_error: str | None = None
    components: list[ComponentPublic]
    cost: SystemCost | None = None


class ComponentBreakdown(BaseModel):
    product_id: int
    product_name: str
    unit: str
    consumption_per_unit: Decimal
    wastage_percent: Decimal
    quantity_with_wastage: Decimal
    purchase_rate: Decimal
    freight_per_unit: Decimal
    landed_rate: Decimal
    cost: Decimal


class RateBreakdownOut(BaseModel):
    system_id: int
    unit: str
    components: list[ComponentBreakdown]
    material_cost: Decimal
    surface_prep: Decimal
    labour_rate: Decimal
    labour_unit: str
    labour_per_unit: Decimal
    base_cost: Decimal
    margin_percent: Decimal
    margin_amount: Decimal
    rate: Decimal


# --- library ---


class UnitOut(ORM):
    code: str
    name: str
    aliases: list[str]


class LibraryItemOut(BaseModel):
    id: int
    description: str
    unit: str | None
    unit_raw: str | None
    boq_count: int
    latest_rate: Decimal | None
    min_rate: Decimal | None
    median_rate: Decimal | None
    max_rate: Decimal | None
    latest_channel: str | None
    product_make: str | None
    needs_check: bool
    check_note: str | None
    is_excluded: bool
    excluded_reason: str | None
    is_competitor: bool
    # The rate to offer when pricing: EESPL's latest (or median) rate. Never set for
    # competitor or excluded items.
    suggested_rate: Decimal | None = None

    @model_validator(mode="after")
    def _suggested(self):
        if self.is_competitor or self.is_excluded:
            self.suggested_rate = None
        elif self.latest_rate is not None:
            self.suggested_rate = self.latest_rate
        else:
            self.suggested_rate = self.median_rate
        return self


class MergedItemRef(BaseModel):
    id: int
    description: str
    unit: str | None


class LibraryItemDetail(LibraryItemOut):
    exclusion_source: str | None
    unit_manual: bool
    stats_from_lines: bool
    merged_into: MergedItemRef | None
    merged_items: list[MergedItemRef]


class LibraryHit(LibraryItemOut):
    score: float


class LibrarySearchOut(BaseModel):
    items: list[LibraryHit]
    took_ms: float
    has_more: bool
    next_offset: int
    cut_applied: bool


class LibraryLineOut(ORM):
    id: int
    library_item_id: int | None
    channel: str | None
    file: str
    sheet: str | None
    row: int | None
    item_no: str | None
    parent_item: str | None
    description: str
    unit_raw: str | None
    unit: str | None
    qty: Decimal | None
    qty_note: str | None
    rate: Decimal | None
    product_make: str | None
    remarks: str | None
    from_eespl_file: bool
    needs_check: bool
    check_note: str | None
    is_excluded: bool
    excluded_reason: str | None
    is_competitor: bool


class LibraryItemUpdate(BaseModel):
    """Hide/unhide (is_excluded + excluded_reason) and/or change the unit."""

    is_excluded: bool | None = None
    excluded_reason: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _reason(self):
        if self.is_excluded and not (self.excluded_reason or "").strip():
            raise ValueError("Give a reason for hiding this item")
        return self


class MergeIn(BaseModel):
    into_id: int


# --- T&C ---


class ClauseIn(BaseModel):
    text: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=50)
    default_include: bool = False
    sort_order: int | None = None


class ClauseUpdate(BaseModel):
    """Saving a changed text also clears needs_review."""

    text: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    default_include: bool | None = None
    sort_order: int | None = None


class ClauseVariant(ORM):
    id: int
    text: str
    own_usage_count: int


class ClauseOut(ORM):
    id: int
    text: str
    category: str
    usage_count: int
    own_usage_count: int
    default_include: bool
    sort_order: int
    status: str
    hidden_reason: str | None
    merged_into_id: int | None
    needs_review: bool
    review_note: str | None
    variant_count: int = 0
    variants: list[ClauseVariant] = []


HiddenReason = Literal["not_a_clause", "client_checklist", "project_specific", "manual"]


class HideIn(BaseModel):
    reason: HiddenReason = "manual"


class ClauseMergeIn(BaseModel):
    into_id: int


class OrderIn(BaseModel):
    ids: list[int] = Field(min_length=1)


class TemplateIn(BaseModel):
    name: Name
    is_default: bool = False
    clause_ids: list[int] = []


class TemplateUpdate(BaseModel):
    name: Name | None = None
    is_default: bool | None = None
    clause_ids: list[int] | None = None  # when given, replaces the clauses in this order


class TemplateSummary(BaseModel):
    id: int
    name: str
    is_default: bool
    clause_count: int


class TemplateOut(BaseModel):
    id: int
    name: str
    is_default: bool
    clauses: list[ClauseOut]


# --- M1 part 2 --------------------------------------------------------------------------------

IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
ACCOUNT_RE = re.compile(r"^[0-9]{6,18}$")
TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")

CategoryKind = Literal[CATEGORY_KINDS]  # type: ignore[valid-type]
TagModule = Literal[TAG_MODULES]  # type: ignore[valid-type]
VendorType = Literal[VENDOR_TYPES]  # type: ignore[valid-type]


def validate_ifsc(value: str) -> str:
    value = value.strip().upper().replace(" ", "")
    if not IFSC_RE.match(value):
        raise ValueError("IFSC must look like HDFC0001234 (4 letters, 0, then 6 letters/digits)")
    return value


def validate_account_number(value: str) -> str:
    value = value.strip().replace(" ", "").replace("-", "")
    if not ACCOUNT_RE.match(value):
        raise ValueError("Account number must be 6 to 18 digits")
    return value


def _pattern(regex: re.Pattern, example: str):
    def check(value: str | None) -> str | None:
        value = _blank_to_none(value)
        if value is None:
            return None
        value = value.upper().replace(" ", "")
        if not regex.match(value):
            raise ValueError(f"must look like {example}")
        return value

    return check


class CategoryIn(BaseModel):
    kind: CategoryKind
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    sort_order: int = 0
    is_active: bool = True


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    parent_id: int | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class CategoryOut(ORM):
    id: int
    kind: str
    name: str
    parent_id: int | None
    sort_order: int
    is_active: bool
    product_count: int = 0


class TagIn(BaseModel):
    module: TagModule
    name: str = Field(min_length=1, max_length=100)
    is_archived: bool = False


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_archived: bool | None = None


class TagOut(ORM):
    id: int
    module: str
    name: str
    is_archived: bool


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    aliases: list[str] | None = None


class ConversionIn(BaseModel):
    from_unit: str
    to_unit: str
    factor: Decimal = Field(gt=0, max_digits=18, decimal_places=8)
    product_id: int | None = None


class ConversionUpdate(BaseModel):
    factor: Decimal = Field(gt=0, max_digits=18, decimal_places=8)


class ConversionOut(BaseModel):
    id: int
    from_unit: str
    to_unit: str
    factor: Decimal
    product_id: int | None
    product_name: str | None


class ConvertOut(BaseModel):
    qty: Decimal
    from_unit: str
    to_unit: str
    product_id: int | None
    result: Decimal


# vendors


class BankAccountIn(BaseModel):
    account_name: Name
    account_number: str
    ifsc: str
    bank: str | None = Field(default=None, max_length=100)
    branch: str | None = Field(default=None, max_length=100)
    is_primary: bool = False

    _number = field_validator("account_number")(validate_account_number)
    _ifsc = field_validator("ifsc")(validate_ifsc)


class BankAccountOut(BaseModel):
    """account_number and ifsc are None (and masked True) for callers without settings.company
    or finance.view."""

    id: int
    account_name: str
    bank: str | None
    branch: str | None
    is_primary: bool
    account_number: str | None
    ifsc: str | None
    masked: bool


class VendorProductIn(BaseModel):
    product_id: int
    last_rate: NonNegative | None = None
    lead_time_days: int | None = Field(default=None, ge=0, le=3650)


class VendorProductOut(BaseModel):
    id: int
    product_id: int
    product_code: str
    product_name: str
    unit: str
    last_rate: Decimal | None
    lead_time_days: int | None


class VendorIn(ClientFields):
    name: Name
    type: VendorType = "material_supplier"
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool = True
    contacts: list[ContactIn] = []

    @model_validator(mode="after")
    def _contacts(self):
        _one_primary(self.contacts)
        return self


class VendorUpdate(ClientFields):
    name: Name | None = None
    type: VendorType | None = None
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    is_active: bool | None = None
    contacts: list[ContactIn] | None = None  # when given, replaces all contacts

    @model_validator(mode="after")
    def _contacts(self):
        _one_primary(self.contacts)
        return self


class VendorOut(BaseModel):
    id: int
    name: str
    type: str
    gstin: str | None
    pan: str | None
    address: str | None
    city: str | None
    state: str | None
    payment_terms_days: int | None
    notes: str | None
    is_active: bool
    created_at: datetime
    contacts: list[ContactOut]
    bank_accounts: list[BankAccountOut]
    products: list[VendorProductOut]


# company settings


class CompanyProfileIn(BaseModel):
    legal_name: str | None = Field(default=None, max_length=200)
    trade_name: str | None = Field(default=None, max_length=200)
    pan: str | None = None
    tan: str | None = None
    tds_percent: Percent | None = None
    cin: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    website: str | None = Field(default=None, max_length=200)
    default_gst_percent: Percent | None = None
    # auto-pricing: suggestions scoring below this stay unpriced
    pricing_threshold: Decimal | None = Field(default=None, ge=0, le=1, decimal_places=3)
    rate_policy: str | None = None  # app.masters.rate_policy.POLICIES

    @field_validator("rate_policy")
    @classmethod
    def _policy(cls, v):
        from app.masters.rate_policy import POLICIES

        if v is not None and v not in POLICIES:
            raise ValueError(f"Choose one of: {', '.join(POLICIES)}")
        return v

    _pan = field_validator("pan")(validate_pan)
    _tan = field_validator("tan")(_pattern(TAN_RE, "AHMA12345B"))
    _cin = field_validator("cin")(_pattern(CIN_RE, "U74999GJ2019PTC123456"))

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, v):
        return _blank_to_none(v) if isinstance(v, str) else v


class CompanyProfileOut(ORM):
    legal_name: str | None
    trade_name: str | None
    pan: str | None
    tan: str | None
    tds_percent: Decimal | None
    cin: str | None
    email: str | None
    phone: str | None
    website: str | None
    default_gst_percent: Decimal
    pricing_threshold: Decimal
    rate_policy: str
    has_logo: bool = False
    updated_at: datetime


class GstinIn(BaseModel):
    gstin: str
    state: str = Field(min_length=1, max_length=100)
    address: str = Field(min_length=1)
    is_default: bool = False

    @field_validator("gstin")
    @classmethod
    def _gstin(cls, v):
        value = validate_gstin(v)
        if value is None:
            raise ValueError("GSTIN is required")
        return value


class GstinUpdate(BaseModel):
    state: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, min_length=1)
    is_default: bool | None = None


class GstinOut(ORM):
    id: int
    gstin: str
    state: str
    address: str
    is_default: bool


class CompanyBankIn(BaseModel):
    account_name: Name
    account_number: str
    ifsc: str
    bank: str | None = Field(default=None, max_length=100)
    branch: str | None = Field(default=None, max_length=100)
    is_default: bool = False

    _number = field_validator("account_number")(validate_account_number)
    _ifsc = field_validator("ifsc")(validate_ifsc)


class CompanyBankUpdate(BaseModel):
    account_name: Name | None = None
    bank: str | None = Field(default=None, max_length=100)
    branch: str | None = Field(default=None, max_length=100)
    is_default: bool | None = None


class CompanyBankOut(ORM):
    id: int
    account_name: str
    account_number: str
    ifsc: str
    bank: str | None
    branch: str | None
    is_default: bool


# --- channels ---

ChannelType = Literal["salesperson", "partner", "manufacturer", "other"]


class ChannelIn(BaseModel):
    name: Name
    type: ChannelType = "other"
    is_active: bool = True
    notes: str | None = None


class ChannelUpdate(BaseModel):
    name: Name | None = None
    type: ChannelType | None = None
    is_active: bool | None = None
    notes: str | None = None


class ChannelOut(ORM):
    id: int
    name: str
    type: str
    is_active: bool
    notes: str | None
    library_lines: int = 0
    tenders: int = 0
