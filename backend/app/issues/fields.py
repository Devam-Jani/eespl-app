# ruff: noqa: E501
"""A wrong entry, said plainly beside its field: what is wrong and how to fix it, from the field's
rule (no AI). Every 422 the API's checks give goes through here, so the helper card shows
"Quantity must be 0 or more. Type a number of 0 or more (not a negative one)." instead of
"body.qty: Input should be greater than or equal to 0"."""

import re
from typing import Any

WORDS = {"qty": "Quantity", "sqm": "Area (sqm)", "rmt": "Running metres", "gst": "GST", "gstin": "GSTIN", "pan": "PAN", "hsn": "HSN code", "po": "PO", "grn": "GRN",
         "ra": "RA", "wo": "Work order", "dpr": "Daily report", "id": "", "m": "(m)", "mm": "(mm)", "pct": "%", "pr": "Pull request", "url": "link", "uom": "Unit"}  # fmt: skip


def label(loc: list | tuple) -> str:
    """('body', 'lines', 1, 'qty') -> 'Line 2: Quantity'."""
    parts = [p for p in loc if p not in ("body", "query", "path")]
    out = []
    for i, p in enumerate(parts):
        if isinstance(p, int):
            prev = str(parts[i - 1]) if i else "item"
            out.append(f"{prev.rstrip('s').replace('_', ' ').capitalize()} {p + 1}")
            continue
        words = [WORDS.get(w, w) for w in str(p).split("_") if WORDS.get(w, w) != ""]
        text = " ".join(words).strip()
        if text and (i + 1 >= len(parts) or not isinstance(parts[i + 1], int)):
            out.append(text[:1].upper() + text[1:])
    return ": ".join(out) or "This field"


def _num(v: Any) -> str:
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


def plain(err: dict) -> tuple[str, str]:
    """(what is wrong, how to fix it) for one pydantic error."""
    t = err.get("type", "")
    ctx = err.get("ctx") or {}
    f = label(err.get("loc") or [])
    if t == "missing":
        return f"{f} is needed.", "Fill it in."
    if t == "string_too_short":
        n = ctx.get("min_length", 1)
        return (f"{f} is empty.", "Fill it in.") if n == 1 else (f"{f} is too short.", f"Type at least {n} characters.")
    if t == "string_too_long":
        return f"{f} is too long.", f"Shorten it to {ctx.get('max_length')} characters or fewer."
    if t in ("greater_than_equal", "greater_than"):
        v = _num(ctx.get("ge", ctx.get("gt")))
        if t == "greater_than_equal":
            return f"{f} must be {v} or more.", f"Type a number of {v} or more" + (" (not a negative one)." if v == "0" else ".")
        return f"{f} must be more than {v}.", f"Type a number above {v}."
    if t in ("less_than_equal", "less_than"):
        v = _num(ctx.get("le", ctx.get("lt")))
        return (f"{f} must be {v} or less.", f"Type a number up to {v}.") if t == "less_than_equal" else (f"{f} must be less than {v}.", f"Type a number below {v}.")
    if t in ("int_parsing", "int_type", "float_parsing", "float_type", "decimal_parsing", "decimal_type", "int_from_float"):
        whole = t.startswith("int")
        return f"{f} must be a {'whole ' if whole else ''}number.", "Type digits only, like " + ("12" if whole else "12.5") + " (no letters, units or commas)."
    if t in ("decimal_max_digits", "decimal_max_places", "decimal_whole_digits"):
        return f"{f} has too many digits.", "Shorten it (up to " + str(ctx.get("decimal_places", ctx.get("max_digits", "a few"))) + " digits after the point)." if "places" in t else f"{f} is too large."
    if t in ("date_parsing", "date_from_datetime_parsing", "date_type", "datetime_parsing", "datetime_type", "date_from_datetime_inexact"):
        return f"{f} is not a date.", "Pick a date, or type it as 2026-10-22."
    if t in ("bool_parsing", "bool_type"):
        return f"{f} must be yes or no.", "Tick or untick it."
    if t in ("enum", "literal_error"):
        return f"{f} is not one of the choices.", "Pick one of: " + str(ctx.get("expected", "the listed values")).replace("'", "") + "."
    if t == "string_pattern_mismatch":
        return f"{f} is not in the right form.", _pattern_hint(str(ctx.get("pattern", "")))
    if t in ("url_parsing", "url_scheme", "url_type"):
        return f"{f} is not a web address.", "Paste the full link, starting with https://."
    if t in ("value_error", "assertion_error"):
        msg = re.sub(r"^(Value error|Assertion failed),\s*", "", str(err.get("msg", ""))).strip()
        return (f"{f}: {msg}" if f != "This field" else msg).rstrip(".") + ".", "Correct it as the message says."
    if t in ("json_invalid", "model_attributes_type", "dict_type", "list_type", "model_type"):
        return "The form could not be read.", "Reload the page and try again."
    if t == "uuid_parsing":
        return f"{f} is not a known record.", "Pick it from the list again."
    msg = str(err.get("msg", "is not valid"))
    return f"{f}: {msg}.", "Check it and try again."


def _pattern_hint(pattern: str) -> str:
    if "a-f" in pattern and "0-9" in pattern:  # a hex value: a commit, a colour
        return "Use digits and the letters a to f only, like b89a83c."
    if "0-9" in pattern and not re.search(r"[a-zA-Z]-[a-zA-Z]", pattern):
        return "Use digits only."
    if "https://github" in pattern:
        return "Paste the pull request's link, like https://github.com/owner/repo/pull/12."
    if "{15}" in pattern or "GSTIN" in pattern.upper():
        return "A GSTIN has 15 letters and digits, like 24AAACE1234A1Z1."
    return "Check the format against the example beside the field."


def to_detail(errors: list[dict]) -> list[dict]:
    """Each error with its field's label, what is wrong and how to fix it; msg is the plain text
    (what older screens show), the original kept as raw."""
    out = []
    for e in errors:
        what, fix = plain(e)
        loc = list(e.get("loc") or [])
        field = next((str(p) for p in reversed(loc) if isinstance(p, str) and p not in ("body", "query", "path")), None)
        out.append({"loc": loc, "type": e.get("type"), "field": field, "label": label(loc), "msg": f"{what} {fix}", "plain": what, "fix": fix, "raw": str(e.get("msg", ""))})
    return out


def db_problem(exc: Exception) -> tuple[int | None, str]:
    """(HTTP status, plain message) for a database refusal caused by what was entered: a number
    out of range, a record that does not exist, a duplicate, a missing value. (None, "") for
    anything else (a bug: it stays a 5xx)."""
    code = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
    if code.startswith("22"):  # data exception: out of range, bad text for a number or a date
        return 422, "A value is out of range (a number too large, or text where a number or date belongs). Check the numbers and try again."
    if code == "23503":
        return 422, "It refers to a record that does not exist or was removed. Pick it from the list again."
    if code == "23505":
        return 409, "This already exists. Open the existing one, or change the name or number."
    if code == "23502":
        return 422, "A required value is missing. Fill in every field marked *."
    if code == "23514":
        return 422, "A value is not allowed here. Check the numbers (negative values, percentages over 100) and try again."
    return None, ""
