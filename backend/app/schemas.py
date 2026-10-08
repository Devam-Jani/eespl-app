import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.auth.security import MIN_PASSWORD_LENGTH

Scope = Literal["all", "assigned", "own"]
PasswordStr = Annotated[str, Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)]


def _lower(value: str | None) -> str | None:
    return value.strip().lower() if value is not None else None


# --- auth ---


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=256)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str


class MeUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    full_name: str
    phone: str | None


class MeOut(BaseModel):
    user: MeUser
    roles: list[RoleRef]
    permissions: dict[str, Scope]


# --- users ---


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str | None
    full_name: str
    phone: str | None
    job_title: str | None = None
    kylas_user_id: int | None = None
    pan: str | None = None
    uan: str | None = None
    esi_no: str | None = None
    bank_account_masked: str | None = None
    bank_ifsc: str | None = None
    has_password: bool = False
    is_active: bool
    locked_until: datetime | None
    last_login_at: datetime | None
    created_at: datetime
    roles: list[RoleRef]


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    password: PasswordStr
    role_ids: list[int] = []

    _email = field_validator("email")(_lower)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    job_title: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    kylas_user_id: int | None = Field(default=None, gt=0)  # admin.settings only
    pan: str | None = Field(default=None, pattern=r"^[A-Z]{5}[0-9]{4}[A-Z]$")
    uan: str | None = Field(default=None, pattern=r"^[0-9]{12}$")
    esi_no: str | None = Field(default=None, pattern=r"^[0-9]{10,17}$")
    bank_account: str | None = Field(default=None, pattern=r"^[0-9]{6,34}$")
    bank_ifsc: str | None = Field(default=None, pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")

    _email = field_validator("email")(_lower)


class PasswordResetIn(BaseModel):
    password: PasswordStr


class RoleIdsIn(BaseModel):
    role_ids: list[int]


# --- roles & permissions ---


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    module: str
    description: str | None


class RoleOut(BaseModel):
    id: int
    code: str
    name: str
    description: str | None
    is_system: bool
    permissions_locked: bool
    permissions: dict[str, Scope]
    user_count: int


class RoleCreate(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    permissions: dict[str, Scope] = {}


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None


class RolePermissionsIn(BaseModel):
    permissions: dict[str, Scope]


# --- audit ---


class AuditOut(BaseModel):
    id: int
    at: datetime
    user_id: uuid.UUID | None
    user_email: str | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
