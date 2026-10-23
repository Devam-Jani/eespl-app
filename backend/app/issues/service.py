# ruff: noqa: E501
"""The issue log book's rules: one row per problem (the same error, on the same page, grouped),
nothing secret ever stored (passwords, tokens, keys are taken out of what is kept), the helper's
AI fed only what it may see, the nightly list of open bugs for the developer agent (no personal
data), the weekly summary, and fixes marked released when a deploy carries their commit."""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.issues.models import Issue, IssueEvent

SECRET_KEY = re.compile(r"pass|token|secret|key|authori[sz]ation|cookie|otp|totp|two.?step|pin\b|cvv|card", re.I)
SECRET_TEXT = [
    (re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"), "[token]"),  # a JWT
    (re.compile(r"(?i)bearer\s+[\w.\-~+/=]{8,}"), "Bearer [token]"),
    (re.compile(r"(?i)(password|passwd|pwd|secret|api[_-]?key|token)(\s*[=:]\s*)\S+"), r"\1\2[hidden]"),
    (re.compile(r"\bsk-[\w-]{12,}"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}"), "[long value]"),
]
PERSONAL_TEXT = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[email]"),
    (re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"), "[phone]"),
]
LOCATION_TEXT = re.compile(r"-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,}")  # lat, lng
# for a client user: every amount, then the rest of a clause about cost, rate, price or margin (to
# the end of the sentence: a dot followed by a space, not the dot of "Rs.")
MONEY_AMOUNT = re.compile(r"(?i)(₹|\brs\.?|\binr\b)\s*\d[\d,]*(\.\d+)?|\b\d[\d,]*(\.\d+)?\s*(₹|rs\b\.?|inr\b|lakhs?\b|crores?\b|%)")
MONEY_TEXT = re.compile(r"(?i)\b(costs?|margins?|rates?|prices?|profit|mark-?up|gross)\b(?:(?!\.\s)[^;\n])*")
STACK_LINES = 40


def scrub(text: str | None, personal: bool = False, limit: int = 4000) -> str | None:
    """No secret ever kept: tokens, passwords, keys out; personal data too when asked (the nightly
    list for the developer)."""
    if not text:
        return text
    out = text
    for pat, rep in SECRET_TEXT:
        out = pat.sub(rep, out)
    if personal:
        for pat, rep in PERSONAL_TEXT:
            out = pat.sub(rep, out)
        out = LOCATION_TEXT.sub("[location]", out)
    return out[:limit]


def scrub_values(values: dict | None) -> dict | None:
    """What the user typed (only when they agreed), without anything that looks secret."""
    if not values:
        return None
    out: dict[str, Any] = {}
    for k, v in list(values.items())[:60]:
        if SECRET_KEY.search(str(k)):
            continue
        out[str(k)[:80]] = scrub(str(v), limit=300) if v is not None else None
    return out or None


def trim_stack(stack: str | None) -> str | None:
    if not stack:
        return None
    lines = scrub(stack, limit=20000).splitlines()
    return "\n".join(lines[-STACK_LINES:])


def page_pattern(page: str | None) -> str | None:
    """/sites/471/takeoff?file=12 -> /sites/:id/takeoff (repeats on other records group)."""
    if not page:
        return page
    p = page.split("?")[0].split("#")[0]
    p = re.sub(r"/\d+(?=/|$)", "/:id", p)
    return re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{27,}(?=/|$)", "/:id", p)[:200]


def normalise(error: str | None) -> str:
    e = (error or "").lower()
    e = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27,}", "<id>", e)
    e = re.sub(r"\d+", "#", e)
    return re.sub(r"\s+", " ", e).strip()[:300]


def fingerprint(kind: str, page: str | None, error: str | None, status_code: int | None) -> str:
    key = "|".join([kind if kind != "nightly" else "error", page_pattern(page) or "", str(status_code or ""), normalise(error)])
    return hashlib.sha1(key.encode()).hexdigest()


def record(db: Session, kind: str, *, page: str | None, error: str | None, status_code: int | None = None, stack: str | None = None,
           request_id: str | None = None, role: str | None = None, client: bool = False, user_id: uuid.UUID | None = None,
           action: str | None = None, browser: str | None = None, words: str | None = None, values: dict | None = None,
           found_by: str = "user", group: bool = True) -> tuple[Issue, IssueEvent]:  # fmt: skip
    """One more time a problem happened: its issue (made the first time, else counted) and the
    event. A mistake the user was guided through is "guided" at once; a report without an error
    is its own issue (people's reports are not merged)."""
    error = scrub(error, limit=2000)
    fp = fingerprint(kind, page, error, status_code) if group else uuid.uuid4().hex
    # locked and read afresh (another request may have counted it or marked it fixed)
    issue = db.scalar(select(Issue).where(Issue.fingerprint == fp).with_for_update().execution_options(populate_existing=True))
    now = datetime.now(UTC)
    if issue is None:
        title = (error or words or "A problem reported").strip().splitlines()[0][:290]
        issue = Issue(fingerprint=fp, kind=kind, status="guided" if kind == "mistake" else "new", title=title, page=page_pattern(page),
                      roles=[role] if role else [], error=error, stack=trim_stack(stack), status_code=status_code,
                      found_by=found_by, first_seen=now, last_seen=now, count=1)  # fmt: skip
        db.add(issue)
        db.flush()
    else:
        issue.count += 1
        issue.last_seen = now
        if role and role not in (issue.roles or []):
            issue.roles = [*(issue.roles or []), role]
        if stack:
            issue.stack = trim_stack(stack)
        if issue.status in ("fixed",) and kind != "mistake":
            issue.status = "new"  # it came back after the fix: look again
    ev = IssueEvent(issue_id=issue.id, user_id=user_id, role=role, client=client, page=(page or "")[:300] or None, action=(action or "")[:300] or None,
                    request_id=request_id, browser=(browser or "")[:200] or None, status_code=status_code, error=error, stack=trim_stack(stack),
                    words=scrub(words, limit=2000), values=scrub_values(values), found_by=found_by)  # fmt: skip
    db.add(ev)
    db.flush()
    return issue, ev


# --- what the helper's AI may see -------------------------------------------------------------------


def for_ai(text: str | None, client: bool) -> str:
    """Never a secret or a place; for a client user no cost, rate or margin either."""
    out = scrub(text, personal=True, limit=3000) or ""
    if client:
        out = MONEY_TEXT.sub("[not shown]", MONEY_AMOUNT.sub("[amount]", out))
    return out


# --- the developer's list, the director's week, the release -------------------------------------------


def open_bugs(db: Session) -> list[Issue]:
    """Errors not fixed yet, and anything (a user's report too) the log book's keepers marked a bug."""
    errors = Issue.kind.in_(("error", "nightly")) & Issue.status.in_(("new", "bug", "fixing"))
    marked = Issue.status.in_(("bug", "fixing"))
    return list(db.scalars(select(Issue).where(errors | marked).order_by(Issue.count.desc(), Issue.last_seen.desc())))


def open_md(db: Session) -> str:
    """docs/issues/open.md: the open bugs for the developer agent, grouped, with their request
    ids and stack traces: no names, emails, phone numbers, places or what users typed."""
    lines = ["# Open bugs from the issue log", "", f"Written {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from the app's issue log book. No personal data: roles only, no user's words or values.",
             "For each: reproduce it with a failing test, fix it, open a pull request that names the issue (\"Fixes issue #N\"). Never merge, deploy or touch production data.", ""]  # fmt: skip
    bugs = open_bugs(db)
    if not bugs:
        lines.append("Nothing open.")
    for i in bugs:
        reqs = list(db.scalars(select(IssueEvent.request_id).where(IssueEvent.issue_id == i.id, IssueEvent.request_id.is_not(None)).order_by(IssueEvent.at.desc()).limit(5)))
        # a user's report is titled by their words: never copied here (the keepers' cause says what it is)
        title = scrub(i.title, personal=True) if i.kind in ("error", "nightly") else f"A user's report on {i.page or 'a page'}"
        lines += [f"## Issue #{i.id}: {title}", "",
                  f"- status: {i.status}; found by: {i.found_by}; seen {i.count} time(s), first {i.first_seen:%Y-%m-%d %H:%M}, last {i.last_seen:%Y-%m-%d %H:%M} UTC",
                  f"- page: `{i.page or '?'}`; HTTP status: {i.status_code or '-'}; roles: {', '.join(i.roles or []) or '-'}",
                  f"- request ids: {', '.join(r for r in reqs if r) or '-'}", ""]  # fmt: skip
        if i.cause:
            lines += [f"Cause (from the log book): {scrub(i.cause, personal=True)}", ""]
        if i.error and i.kind in ("error", "nightly"):
            lines += ["Error:", "```", scrub(i.error, personal=True) or "", "```", ""]
        if i.stack:
            lines += ["Stack (last lines):", "```", scrub(i.stack, personal=True) or "", "```", ""]
    return "\n".join(lines) + "\n"


def weekly(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=7)
    new = db.scalar(select(func.count()).select_from(Issue).where(Issue.first_seen >= since)) or 0
    fixed = db.scalar(select(func.count()).select_from(Issue).where(Issue.fixed_at >= since)) or 0
    released = db.scalar(select(func.count()).select_from(Issue).where(Issue.released_at >= since)) or 0
    happened = db.scalar(select(func.count()).select_from(IssueEvent).where(IssueEvent.at >= since)) or 0
    by_kind = dict(db.execute(select(Issue.kind, func.count()).where(Issue.last_seen >= since).group_by(Issue.kind)).all())
    pages = db.execute(select(IssueEvent.page, func.count()).where(IssueEvent.at >= since, IssueEvent.page.is_not(None)).group_by(IssueEvent.page).order_by(func.count().desc()).limit(5)).all()
    open_bug_count = len(open_bugs(db))
    return {"from": since.date().isoformat(), "to": now.date().isoformat(), "new_issues": new, "times_happened": happened, "fixed": fixed, "released": released,
            "open_bugs": open_bug_count, "by_kind": by_kind, "top_pages": [{"page": page_pattern(p), "times": n} for p, n in pages]}  # fmt: skip


def released(db: Session, commits: list[str], at: datetime | None = None) -> list[int]:
    """A deploy carried these commits: the issues fixed by one of them are released (and fixed,
    when they were not marked so yet). Short or full hashes both match."""
    at = at or datetime.now(UTC)
    full = [c.strip().lower() for c in commits if len(c.strip()) >= 7]
    done = []
    for i in db.scalars(select(Issue).where(Issue.commit.is_not(None), Issue.released_at.is_(None))):
        c = (i.commit or "").strip().lower()
        if len(c) >= 7 and any(x.startswith(c) or c.startswith(x) for x in full):
            i.released_at = at
            i.status = "fixed"
            i.fixed_at = i.fixed_at or at
            done.append(i.id)
    return done
