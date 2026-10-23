# ruff: noqa: E501
"""The issue log book's API.

Everyone signed in (staff and client users) under /api/me/: report a problem (the frontend sends
crashes and failed requests by itself; "Report this" adds the user's words), see their own reports
and their status, and "Ask the helper". The log book itself under /api/issues: the director, the
office admin and the super admin (issuelog.view, issuelog.edit). Every request has an id (X-Request-ID)
and every 5xx is recorded with it, its trace kept on the server."""

import hmac
import io
import logging
import re
import traceback
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.deps import CurrentPrincipal, is_client_login, require_permission
from app.config import settings
from app.db import DbSession, SessionLocal
from app.issues import helper_ai
from app.issues import service as svc
from app.issues.models import KINDS, STATUSES, HelperAnswer, Issue, IssueEvent

log = logging.getLogger("eespl.issues")
me = APIRouter(prefix="/api/me", tags=["issues"])
router = APIRouter(prefix="/api/issues", tags=["issues"])
View = Annotated[str, Depends(require_permission("issuelog.view"))]
Edit = Annotated[str, Depends(require_permission("issuelog.edit"))]
RID = re.compile(r"^[A-Za-z0-9-]{8,40}$")


def _role(principal) -> str:
    codes = sorted(r.code for r in principal.user.roles)
    if is_client_login(principal.permissions):
        return "client"
    return codes[0] if codes else "staff"


# --- every request's id, every 5xx recorded -------------------------------------------------------------


def _record_server(path: str, method: str, auth: str | None, status_code: int, error: str, stack: str | None, rid: str) -> None:
    """A 5xx, recorded on its own session (the request's may be broken). Never raises."""
    try:
        from app.auth.security import decode_access  # noqa: PLC0415
        from app.models import User  # noqa: PLC0415

        with SessionLocal() as db:
            user_id, role = None, None
            if auth and auth.lower().startswith("bearer "):
                try:
                    uid, _iat = decode_access(auth[7:])
                    u = db.get(User, uid)
                    if u is not None:
                        user_id = u.id
                        role = sorted(r.code for r in u.roles)[0] if u.roles else None
                except Exception:  # noqa: BLE001  an expired token: the role is unknown
                    pass
            svc.record(db, "error", page=f"{method} {path}", error=error, status_code=status_code, stack=stack, request_id=rid,
                       role=role, user_id=user_id, found_by="server")  # fmt: skip
            db.commit()
    except Exception:  # noqa: BLE001  the log book must never break a response
        log.exception("could not record a %s (request %s)", status_code, rid)


class RequestIds(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        given = request.headers.get("x-request-id") or ""
        rid = given if RID.match(given) else uuid.uuid4().hex[:16]
        request.state.request_id = rid
        path = request.url.path
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001  any crash: recorded, a plain answer with the request id
            log.exception("request %s failed", rid)
            await run_in_threadpool(_record_server, path, request.method, request.headers.get("authorization"), 500,
                                    f"{type(exc).__name__}: {exc}", traceback.format_exc(), rid)  # fmt: skip
            return JSONResponse({"detail": f"Something went wrong on our side. It is recorded (request {rid}): try again, or report what you were doing.", "request_id": rid},
                                status_code=500, headers={"X-Request-ID": rid})  # fmt: skip
        if response.status_code >= 500 and path.startswith("/api/") and not path.startswith("/api/health"):
            await run_in_threadpool(_record_server, path, request.method, request.headers.get("authorization"), response.status_code, f"HTTP {response.status_code}", None, rid)
        response.headers["X-Request-ID"] = rid
        return response


# --- everyone: report, my reports, ask the helper ------------------------------------------------------------


class ReportIn(BaseModel):
    kind: str = Field(default="error", pattern="^(error|mistake|report)$")
    page: str | None = Field(default=None, max_length=300)
    action: str | None = Field(default=None, max_length=300)
    error: str | None = Field(default=None, max_length=4000)
    status_code: int | None = Field(default=None, ge=0, le=999)
    request_id: str | None = Field(default=None, max_length=40)
    browser: str | None = Field(default=None, max_length=300)
    stack: str | None = Field(default=None, max_length=20000)
    words: str | None = Field(default=None, max_length=2000)
    include_values: bool = False  # the user agreed to send what they typed
    values: dict[str, Any] | None = None


def _event_out(e: IssueEvent, i: Issue) -> dict:
    return {"event_id": e.id, "issue_id": i.id, "at": e.at, "page": e.page, "kind": i.kind, "title": i.title, "words": e.words, "status": i.status,
            "fixed_at": i.fixed_at, "released_at": i.released_at, "fix": i.fix if i.status == "fixed" else None}  # fmt: skip


@me.post("/issues", status_code=status.HTTP_201_CREATED)
def report(body: ReportIn, request: Request, db: DbSession, principal: CurrentPrincipal) -> dict:
    """A problem from the browser: a crash, a failed request, a wrong entry the user was guided
    through, or the user's own report. What they typed only when they agreed."""
    client = is_client_login(principal.permissions)
    rid = body.request_id if body.request_id and RID.match(body.request_id) else None
    server = db.scalar(select(IssueEvent).where(IssueEvent.request_id == rid, IssueEvent.found_by == "server").limit(1)) if rid else None
    if server is not None and (server.user_id is None or server.user_id == principal.user.id):
        # the API recorded this 5xx already: the browser's side (page, action, browser) goes on that event
        server.user_id, server.role, server.client = principal.user.id, _role(principal), client
        server.action = (f"{body.page or ''} · {body.action or ''}".strip(" ·"))[:300] or server.action
        server.browser = (body.browser or "")[:200] or None
        issue = db.get(Issue, server.issue_id)
        db.commit()
        return {"issue_id": server.issue_id, "event_id": server.id, "status": issue.status if issue else "new", "request_id": rid}
    issue, ev = svc.record(db, body.kind, page=body.page, error=body.error, status_code=body.status_code, stack=body.stack,
                           request_id=rid,
                           role=_role(principal), client=client, user_id=principal.user.id, action=body.action, browser=body.browser,
                           words=body.words, values=body.values if body.include_values else None,
                           group=not (body.kind == "report" and not body.error))  # fmt: skip
    db.commit()
    return {"issue_id": issue.id, "event_id": ev.id, "status": issue.status, "request_id": getattr(request.state, "request_id", None)}


class WordsIn(BaseModel):
    words: str = Field(min_length=1, max_length=2000)
    include_values: bool = False
    values: dict[str, Any] | None = None


@me.post("/issues/{iid}/words", status_code=status.HTTP_201_CREATED)
def add_words(iid: int, body: WordsIn, db: DbSession, principal: CurrentPrincipal) -> dict:
    """"Report this": what the user was doing, in their words, on a problem they hit."""
    issue = db.get(Issue, iid)
    mine = issue is not None and db.scalar(select(IssueEvent.id).where(IssueEvent.issue_id == iid, IssueEvent.user_id == principal.user.id).limit(1))
    if not mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    _, ev = svc.record(db, issue.kind, page=issue.page, error=issue.error, status_code=issue.status_code, role=_role(principal),
                       client=is_client_login(principal.permissions), user_id=principal.user.id, words=body.words,
                       values=body.values if body.include_values else None)  # fmt: skip
    db.commit()
    return _event_out(ev, issue)


@me.get("/issues")
def my_reports(db: DbSession, principal: CurrentPrincipal) -> list[dict]:
    """The user's own reports and where each stands (never anyone else's)."""
    rows = db.execute(
        select(IssueEvent, Issue).join(Issue, Issue.id == IssueEvent.issue_id)
        .where(IssueEvent.user_id == principal.user.id, (IssueEvent.words.is_not(None)) | (Issue.kind != "mistake"))
        .order_by(IssueEvent.at.desc()).limit(200)
    ).all()  # fmt: skip
    return [_event_out(e, i) for e, i in rows]


@me.get("/helper")
def helper_status(principal: CurrentPrincipal) -> dict:
    return {"ai": helper_ai.enabled()}


class AskIn(BaseModel):
    issue_id: int | None = None
    page: str | None = Field(default=None, max_length=300)
    error: str | None = Field(default=None, max_length=4000)
    field_rules: list[str] = Field(default_factory=list, max_length=20)
    question: str | None = Field(default=None, max_length=1000)


@me.post("/helper/ask")
def ask_helper(body: AskIn, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The helper's AI explains the error and the next step (it never changes data); the answer
    is kept with the issue."""
    if not helper_ai.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, "The helper's AI is not switched on for this company.")
    client = is_client_login(principal.permissions)
    issue = db.get(Issue, body.issue_id) if body.issue_id else None
    if issue is not None and not db.scalar(select(IssueEvent.id).where(IssueEvent.issue_id == issue.id, IssueEvent.user_id == principal.user.id).limit(1)):
        issue = None  # someone else's problem: not linked
    help_text = None
    if body.page and not client:
        from app.ops.routes import _help_for  # noqa: PLC0415

        h = _help_for(db, svc.page_pattern(body.page).replace("/:id", "") or "/", [r.code for r in principal.user.roles])
        help_text = f"{h['title']}: " + " ".join(h["steps"]) if h else None
    message = helper_ai.prompt(page=svc.page_pattern(body.page), help_text=help_text, field_rules=body.field_rules, error=body.error or (issue.error if issue else None),
                               question=body.question, client=client)  # fmt: skip
    try:
        answer = helper_ai.ask(message)
    except Exception as exc:  # noqa: BLE001  the AI service is down or slow: say so plainly
        log.warning("helper ask failed: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The helper could not answer just now: try again in a minute, or use Report this.") from exc
    a = HelperAnswer(issue_id=issue.id if issue else None, user_id=principal.user.id, role=_role(principal), question=(body.question or "What went wrong?")[:1000],
                     answer=answer[:4000], model=settings.helper_ai_model)  # fmt: skip
    db.add(a)
    db.commit()
    return {"answer": a.answer, "model": a.model, "issue_id": a.issue_id}


# --- the log book ------------------------------------------------------------------------------------------


def _issue_out(i: Issue) -> dict:
    return {"id": i.id, "kind": i.kind, "status": i.status, "title": i.title, "page": i.page, "roles": i.roles, "error": i.error, "status_code": i.status_code,
            "found_by": i.found_by, "first_seen": i.first_seen, "last_seen": i.last_seen, "count": i.count, "cause": i.cause, "fix": i.fix,
            "pr_url": i.pr_url, "commit": i.commit, "fixed_at": i.fixed_at, "released_at": i.released_at}  # fmt: skip


@router.get("")
def list_issues(db: DbSession, _: View, status_: Annotated[str | None, Query(alias="status")] = None, kind: str | None = None, q: str | None = None, limit: int = 200) -> list[dict]:
    stmt = select(Issue).order_by(Issue.last_seen.desc()).limit(min(max(limit, 1), 1000))
    if status_:
        stmt = stmt.where(Issue.status == status_)
    if kind:
        stmt = stmt.where(Issue.kind == kind)
    if q:
        like = f"%{q.strip()[:100]}%"
        stmt = stmt.where(Issue.title.ilike(like) | Issue.page.ilike(like) | Issue.error.ilike(like))
    return [_issue_out(i) for i in db.scalars(stmt)]


@router.get("/weekly")
def weekly(db: DbSession, _: View) -> dict:
    return svc.weekly(db)


@router.get("/open.md")
def open_md(db: DbSession, _: View) -> Response:
    """The open bugs for the developer agent (commit it as docs/issues/open.md): no personal data."""
    return Response(svc.open_md(db), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="open.md"'})


@router.get("/export.xlsx")
def export(db: DbSession, _: View) -> Response:
    import openpyxl  # noqa: PLC0415

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Issues"
    cols = ["id", "kind", "status", "title", "page", "roles", "count", "first_seen", "last_seen", "found_by", "status_code", "cause", "fix", "pr_url", "commit", "fixed_at", "released_at"]
    ws.append(cols)
    for i in db.scalars(select(Issue).order_by(Issue.last_seen.desc())):
        row = _issue_out(i)
        ws.append([", ".join(row[c]) if c == "roles" else (row[c].replace(tzinfo=None) if isinstance(row[c], datetime) else row[c]) for c in cols])
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="issue-log.xlsx"'})


@router.get("/{iid}")
def get_issue(iid: int, db: DbSession, _: View) -> dict:
    i = db.get(Issue, iid)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
    events = db.scalars(select(IssueEvent).where(IssueEvent.issue_id == i.id).order_by(IssueEvent.at.desc()).limit(100))
    answers = db.scalars(select(HelperAnswer).where(HelperAnswer.issue_id == i.id).order_by(HelperAnswer.at.desc()))
    return {**_issue_out(i), "stack": i.stack,
            "events": [{"id": e.id, "at": e.at, "role": e.role, "client": e.client, "user_id": str(e.user_id) if e.user_id else None, "page": e.page, "action": e.action,
                        "request_id": e.request_id, "browser": e.browser, "status_code": e.status_code, "words": e.words, "values": e.values, "found_by": e.found_by} for e in events],
            "answers": [{"at": a.at, "role": a.role, "question": a.question, "answer": a.answer, "model": a.model} for a in answers]}  # fmt: skip


class IssueIn(BaseModel):
    status: str | None = Field(default=None, pattern=f"^({'|'.join(STATUSES)})$")
    cause: str | None = Field(default=None, max_length=4000)
    fix: str | None = Field(default=None, max_length=4000)
    pr_url: str | None = Field(default=None, max_length=300, pattern=r"^(https://github\.com/[\w.-]+/[\w.-]+/pull/\d+)?$")
    commit: str | None = Field(default=None, max_length=40, pattern=r"^([0-9a-fA-F]{7,40})?$")
    fixed_at: datetime | None = None


@router.put("/{iid}")
def update_issue(iid: int, body: IssueIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: Edit) -> dict:
    from app import audit  # noqa: PLC0415

    i = db.get(Issue, iid)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Issue not found")
    before = _issue_out(i)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(i, k, v or None if k != "status" else v)
    if data.get("status") == "fixed" and i.fixed_at is None:
        i.fixed_at = datetime.now(UTC)
    i.updated_by_role = _role(principal)
    audit.record(db, "issue.update", "issue", i.id, user_id=principal.user.id, before={k: str(before[k]) for k in data}, after={k: str(v) for k, v in data.items()}, ip=audit.client_ip(request))
    db.commit()
    return _issue_out(i)


# --- the nightly check (the crawler on the training company) ------------------------------------------------


class NightlyIn(BaseModel):
    findings: list[ReportIn] = Field(max_length=500)


def _crawler(given: str | None) -> None:
    token = settings.crawler_token.get_secret_value() if settings.crawler_token else None
    if not token or not given or not hmac.compare_digest(given, token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not the nightly check")


@router.post("/nightly", status_code=status.HTTP_201_CREATED)
def nightly(body: NightlyIn, db: DbSession, x_crawler_token: Annotated[str | None, Header()] = None) -> dict:
    """What the nightly crawler found on the training company, "found by the nightly check"."""
    _crawler(x_crawler_token)
    ids = []
    for f in body.findings:
        issue, _ = svc.record(db, "nightly", page=f.page, error=f.error, status_code=f.status_code, stack=f.stack, action=f.action, browser=f.browser,
                              role=(f.words or "").split(":")[0][:40] or None, found_by="nightly check")  # fmt: skip
        ids.append(issue.id)
    db.commit()
    return {"issues": sorted(set(ids))}


@router.get("/nightly/open.md")
def nightly_open_md(db: DbSession, x_crawler_token: Annotated[str | None, Header()] = None) -> Response:
    """The open bugs for the GitHub workflow (.github/workflows/fix-issues.yml), with the same token
    as the nightly check: no personal data, nothing else readable with it."""
    _crawler(x_crawler_token)
    return Response(svc.open_md(db), media_type="text/markdown; charset=utf-8")


_ = KINDS
