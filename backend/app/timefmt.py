"""Times are stored in UTC and shown in Indian time everywhere (pages, PDFs, Excel, alerts).
One place for the conversion so a delivery shows the same time on every page."""

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def local(dt: datetime | None) -> datetime | None:
    """The moment in Indian time (a naive value is taken as UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        from datetime import UTC  # noqa: PLC0415

        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def label(dt: datetime | None, fmt: str = "%d %b %Y, %H:%M") -> str:
    """'09 Oct 2026, 17:31' in Indian time; '' for no value."""
    value = local(dt)
    return value.strftime(fmt) if value else ""
