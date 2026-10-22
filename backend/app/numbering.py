"""The next number of a document series: one counter row per series and period in doc_sequences,
taken and raised in one statement (INSERT ... ON CONFLICT DO UPDATE ... RETURNING). The row stays
locked until the transaction ends, so two requests never get the same number; a transaction that
fails rolls its number back with it, so no number is skipped. Every numbered table also has a
unique constraint on its number."""

from sqlalchemy import text
from sqlalchemy.orm import Session

NEXT = text(
    "INSERT INTO doc_sequences (kind, period, last_value) VALUES (:k, :p, 1) "
    "ON CONFLICT (kind, period) DO UPDATE SET last_value = doc_sequences.last_value + 1 "
    "RETURNING last_value"
)


def next_value(db: Session, kind: str, period: str) -> int:
    return db.execute(NEXT, {"k": kind[:10], "p": period[:10]}).scalar_one()
