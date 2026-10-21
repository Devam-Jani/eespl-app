# ruff: noqa: E501
"""The promised handover date's history on the place (the same date, not a second one): who
promised it (the client in the portal, or our engineer after talking to them) and who moved it,
to when and why. The client's promised date shows beside the moved one."""

from datetime import date

from app.closeout.common import now
from app.sites.models import SiteNode


def note(node: SiteNode, kind: str, on: date, by: str, reason: str | None = None, was: date | None = None) -> None:
    """kind: promised (the client's date) or moved (our engineer, with the reason)."""
    entry = {"kind": kind, "on": on.isoformat(), "by": by, "reason": reason, "was": was.isoformat() if was else None, "at": now().isoformat()}
    node.handover_history = [*(node.handover_history or []), entry]


def summary(node: SiteNode) -> dict:
    """The client's promised date (the last promise) and the last move, for the screens."""
    hist = node.handover_history or []
    promised = next((h for h in reversed(hist) if h["kind"] == "promised"), None)
    moved = next((h for h in reversed(hist) if h["kind"] == "moved"), None)
    if moved and promised and promised["at"] > moved["at"]:
        moved = None  # a new promise after the move: the move is history
    return {
        "client_promised_on": promised["on"] if promised else (node.handover_promised_on.isoformat() if node.handover_promised_on and not moved else None),
        "client_promised_by": promised["by"] if promised else None,
        "moved_to": moved["on"] if moved else None,
        "moved_because": moved["reason"] if moved else None,
        "moved_by": moved["by"] if moved else None,
        "history": hist,
    }
