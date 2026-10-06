import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.masters.models import CLIENT_TYPES, LABOUR_UNITS, PRODUCT_CATEGORIES

T = TypeVar("T")

ClientType = Literal[CLIENT_TYPES]  # type: ignore[valid-type]
ProductCategory = Literal[PRODUCT_CATEGORIES]  # type: ignore[valid-type]
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
    category: ProductCategory = "other"
    unit: str
    pack_size: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=3)
    gst_percent: Percent = Decimal(18)
    is_active: bool = True


class ProductUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: Name | None = None
    brand: str | None = Field(default=None, max_length=100)
    category: ProductCategory | None = None
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
    category: str
    unit: str
    pack_size: Decimal | None
    gst_percent: Decimal
    is_active: bool
    cost: ProductCost | None = None


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
    latest_client: str | None
    product_make: str | None
    needs_check: bool
    check_note: str | None


class LibraryHit(LibraryItemOut):
    score: float


class LibrarySearchOut(BaseModel):
    items: list[LibraryHit]
    took_ms: float


class LibraryLineOut(ORM):
    id: int
    client_folder: str | None
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


# --- T&C ---


class ClauseIn(BaseModel):
    text: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=50)
    default_include: bool = False
    sort_order: int | None = None
    is_active: bool = True


class ClauseUpdate(BaseModel):
    text: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    default_include: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ClauseOut(ORM):
    id: int
    text: str
    category: str
    usage_count: int
    default_include: bool
    sort_order: int
    is_active: bool


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
