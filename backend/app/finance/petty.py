"""Petty cash: an account per person, advances (top-ups), expenses with a bill photo, approval,
settlement. Replaces Powerplay's expense payments.

expense.create: spend from your own account (scope own) or anyone's (all); expense.approve gives
advances, approves or rejects expenses and takes back cash. An approved expense is charged to its
site's budget head (by category; mostly "other").
"""

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.auth.deps import CurrentPrincipal, Principal
from app.db import DbSession
from app.execution.common import names, record, save_upload, send_file
from app.execution.service import today
from app.finance import service as svc
from app.finance.models import ExpenseCategory, PettyCashAccount, PettyCashEntry
from app.masters.models import CompanyBankAccount
from app.models import User
from app.sites.models import Site

router = APIRouter(prefix="/api/finance", tags=["finance"])


def _scope(principal: Principal) -> tuple[str | None, str | None]:
    return principal.permissions.get("expense.create"), principal.permissions.get("expense.approve")


def _can_see(principal: Principal, acc: PettyCashAccount) -> bool:
    create, approve = _scope(principal)
    return (
        approve is not None
        or create == "all"
        or (create is not None and acc.user_id == principal.user.id)
    )


def _account(db, aid: int, principal) -> PettyCashAccount:
    acc = db.get(PettyCashAccount, aid)
    if acc is None or not _can_see(principal, acc):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Petty cash account not found")
    return acc


def _entry_out(db, e: PettyCashEntry, who: dict) -> dict:
    site = db.get(Site, e.site_id) if e.site_id else None
    return {
        "id": e.id,
        "number": e.number,
        "kind": e.kind,
        "on_date": e.on_date,
        "amount": e.amount,
        "site_id": e.site_id,
        "site_code": site.code if site else None,
        "category_id": e.category_id,
        "category": e.category.name if e.category else None,
        "paid_to": e.paid_to,
        "mode": e.mode,
        "has_photo": bool(e.photo_path),
        "remark": e.remark,
        "status": e.status,
        "approved_by_name": who.get(e.approved_by),
        "reject_reason": e.reject_reason,
    }


def _account_out(db, acc: PettyCashAccount, with_entries=True) -> dict:
    user = db.get(User, acc.user_id)
    out = {
        "id": acc.id,
        "user_id": str(acc.user_id),
        "user_name": user.full_name,
        "is_active": acc.is_active,
        **svc.petty_balance(db, acc.id),
    }
    if with_entries:
        entries = list(
            db.scalars(
                select(PettyCashEntry)
                .where(PettyCashEntry.account_id == acc.id)
                .order_by(PettyCashEntry.on_date.desc(), PettyCashEntry.id.desc())
            )
        )
        who = names(db, [e.approved_by for e in entries])
        out["entries"] = [_entry_out(db, e, who) for e in entries]
    return out


@router.get("/expense-categories")
def categories(db: DbSession, _: CurrentPrincipal) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "budget_head": c.budget_head}
        for c in db.scalars(
            select(ExpenseCategory).where(ExpenseCategory.is_active).order_by(ExpenseCategory.name)
        )
    ]


@router.get("/petty-cash")
def list_accounts(db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    create, approve = _scope(principal)
    if create is None and approve is None:
        raise svc.forbidden("Missing permission: expense.create")
    q = select(PettyCashAccount)
    if approve is None and create != "all":
        q = q.where(PettyCashAccount.user_id == principal.user.id)
    return [_account_out(db, a, False) for a in db.scalars(q.order_by(PettyCashAccount.id))]


@router.get("/petty-cash/mine")
def my_account(db: DbSession, principal: CurrentPrincipal) -> dict | None:
    if _scope(principal) == (None, None):
        raise svc.forbidden("Missing permission: expense.create")
    acc = db.scalar(select(PettyCashAccount).where(PettyCashAccount.user_id == principal.user.id))
    return _account_out(db, acc) if acc else None


@router.get("/petty-cash/{aid}")
def get_account(aid: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    return _account_out(db, _account(db, aid, principal))


class AdvanceIn(BaseModel):
    user_id: str
    amount: Decimal = Field(gt=0)
    on_date: date | None = None
    mode: Literal["neft", "rtgs", "cheque", "upi", "cash"] = "cash"
    bank_account_id: int | None = None
    remark: str | None = None


@router.post("/petty-cash/advances", status_code=status.HTTP_201_CREATED)
def give_advance(
    body: AdvanceIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Money given to a person (the account is opened on the first advance)."""
    if _scope(principal)[1] is None:
        raise svc.forbidden("Advances are given with expense.approve")
    user = db.get(User, _uuid(body.user_id))
    if user is None:
        raise svc.unprocessable("User not found")
    if body.bank_account_id and db.get(CompanyBankAccount, body.bank_account_id) is None:
        raise svc.unprocessable("Bank account not found")
    acc = db.scalar(select(PettyCashAccount).where(PettyCashAccount.user_id == user.id))
    if acc is None:
        acc = PettyCashAccount(user_id=user.id, created_by=principal.user.id)
        db.add(acc)
        db.flush()
    on = body.on_date or today()
    db.add(
        PettyCashEntry(
            number=svc.next_number(db, "PC", on),
            account_id=acc.id,
            kind="advance",
            on_date=on,
            amount=body.amount,
            mode=body.mode,
            bank_account_id=body.bank_account_id,
            remark=body.remark,
            status="approved",
            approved_by=principal.user.id,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "petty.advance",
        "petty_cash_account",
        acc.id,
        after={"amount": str(body.amount)},
    )
    db.commit()
    return _account_out(db, acc)


def _uuid(v: str):
    import uuid

    try:
        return uuid.UUID(v)
    except ValueError as exc:
        raise svc.unprocessable("Not a user id") from exc


@router.post("/petty-cash/expenses", status_code=status.HTTP_201_CREATED)
async def add_expense(
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    amount: Annotated[Decimal, Form(gt=0)],
    category_id: Annotated[int, Form()],
    site_id: Annotated[int | None, Form()] = None,
    on_date: Annotated[date | None, Form()] = None,
    paid_to: Annotated[str | None, Form(max_length=200)] = None,
    mode: Annotated[str, Form(pattern="^(cash|upi|neft|rtgs|cheque)$")] = "cash",
    remark: Annotated[str | None, Form()] = None,
    user_id: Annotated[str | None, Form()] = None,  # someone else's (expense.create all)
    photo: Annotated[UploadFile | None, File()] = None,
) -> dict:
    """An expense from the spender's petty cash (multipart, so a phone can attach the bill photo).
    Above the photo limit (setting) the bill photo is required. It waits for approval."""
    create, approve = _scope(principal)
    if create is None:
        raise svc.forbidden("Missing permission: expense.create")
    uid = principal.user.id
    if user_id and user_id != str(principal.user.id):
        if create != "all" and approve is None:
            raise svc.forbidden("You can only record your own expenses")
        uid = _uuid(user_id)
    acc = db.scalar(select(PettyCashAccount).where(PettyCashAccount.user_id == uid))
    if acc is None:
        raise svc.unprocessable("No petty cash account yet: an advance opens it")
    cat = db.get(ExpenseCategory, category_id)
    if cat is None:
        raise svc.unprocessable("Category not found")
    if site_id is not None and db.get(Site, site_id) is None:
        raise svc.unprocessable("Site not found")
    has_photo = photo is not None and bool(photo.filename)
    limit = Decimal(svc.settings(db).expense_photo_limit)
    if amount > limit and not has_photo:
        raise svc.unprocessable(f"A bill photo is required above ₹{limit:,.0f}")
    on = on_date or today()
    e = PettyCashEntry(
        number=svc.next_number(db, "PC", on),
        account_id=acc.id,
        kind="expense",
        on_date=on,
        amount=amount,
        site_id=site_id,
        category_id=cat.id,
        paid_to=paid_to,
        mode=mode,
        remark=remark,
        status="submitted",
        created_by=principal.user.id,
    )
    db.add(e)
    db.flush()
    if has_photo:
        e.photo_path, _ = await save_upload(photo, f"petty/{acc.id}")
    record(
        db,
        request,
        principal,
        "petty.expense",
        "petty_cash_account",
        acc.id,
        after={"number": e.number, "amount": str(amount), "site_id": site_id},
    )
    db.commit()
    return _account_out(db, acc)


class DecisionIn(BaseModel):
    approve: bool = True
    reason: str | None = None


@router.post("/petty-cash/expenses/{eid}/decide")
def decide_expense(
    eid: int, body: DecisionIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    if _scope(principal)[1] is None:
        raise svc.forbidden("Expenses are approved with expense.approve")
    e = db.get(PettyCashEntry, eid)
    if e is None or e.kind != "expense":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    if e.status != "submitted":
        raise svc.conflict(f"{e.number} is {e.status}")
    if not body.approve and not (body.reason or "").strip():
        raise svc.unprocessable("Give the reason for rejecting")
    e.status = "approved" if body.approve else "rejected"
    e.approved_by, e.approved_at, e.reject_reason = (
        principal.user.id,
        svc.now(),
        body.reason,
    )
    record(
        db,
        request,
        principal,
        "petty.decide",
        "petty_cash_account",
        e.account_id,
        after={"number": e.number, "status": e.status},
    )
    db.commit()
    return _account_out(db, db.get(PettyCashAccount, e.account_id))


class SettleIn(BaseModel):
    amount: Decimal = Field(gt=0)
    on_date: date | None = None
    remark: str | None = None


@router.post("/petty-cash/{aid}/settle", status_code=status.HTTP_201_CREATED)
def settle(
    aid: int, body: SettleIn, request: Request, db: DbSession, principal: CurrentPrincipal
) -> dict:
    """Cash handed back to the company (settling the balance)."""
    if _scope(principal)[1] is None:
        raise svc.forbidden("Settlement is recorded with expense.approve")
    acc = _account(db, aid, principal)
    if body.amount > svc.petty_balance(db, acc.id)["balance"]:
        raise svc.unprocessable("More than the balance in hand")
    on = body.on_date or today()
    db.add(
        PettyCashEntry(
            number=svc.next_number(db, "PC", on),
            account_id=acc.id,
            kind="settlement",
            on_date=on,
            amount=body.amount,
            remark=body.remark,
            status="approved",
            approved_by=principal.user.id,
            created_by=principal.user.id,
        )
    )
    record(
        db,
        request,
        principal,
        "petty.settle",
        "petty_cash_account",
        acc.id,
        after={"amount": str(body.amount)},
    )
    db.commit()
    return _account_out(db, acc)


@router.get("/petty-cash/expenses/{eid}/photo")
def expense_photo(eid: int, db: DbSession, principal: CurrentPrincipal):
    e = db.get(PettyCashEntry, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    _account(db, e.account_id, principal)
    return send_file(e.photo_path)
