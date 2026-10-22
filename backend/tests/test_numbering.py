# ruff: noqa: E501
"""Numbered documents under load: numbers taken at the same moment from parallel connections are
distinct and gap-free (a transaction that fails gives its number back), for every series."""

import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.closeout.common import next_code as closeout_code
from app.closeout.common import today
from app.closeout.models import ClientWorkOrder, SiteIssueLog, WorkCompletion
from app.costing.labour import _number as labour_number
from app.db import SessionLocal
from app.finance import service as fsvc
from app.main import app
from app.material.service import next_code as material_code
from tests.test_finance import boss, contract, world  # noqa: F401  (fixtures)

ON = date(2026, 10, 22)
SERIES = {
    "invoice": lambda s: fsvc.invoice_number(s, ON),
    "credit note": lambda s: fsvc.next_number(s, "CN", ON),
    "work completion certificate": lambda s: closeout_code(s, WorkCompletion, "WCC"),
    "issue log": lambda s: closeout_code(s, SiteIssueLog, "ISU"),
    "client work order": lambda s: closeout_code(s, ClientWorkOrder, "CWO"),
    "labour bill": lambda s: labour_number(s, ON),
    "purchase order": lambda s: material_code(s, "PO", ON),
    "GRN": lambda s: material_code(s, "GRN", ON),
    "quotation": lambda s: material_code(s, "QTN", ON),
}


def _take_at_once(take, threads: int = 25, failing: int = 5) -> list[str]:
    """`threads` connections take a number at the same moment; `failing` of them roll back."""
    start = threading.Barrier(threads)
    got: list[str] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def one(i: int) -> None:
        try:
            with SessionLocal() as s:
                start.wait()
                number = take(s)
                time.sleep(0.02)  # hold the counter while the others queue on it
                if i < failing:
                    s.rollback()  # the document was not saved: its number goes back
                    return
                s.commit()
                with lock:
                    got.append(number)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    ts = [threading.Thread(target=one, args=(i,)) for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors, errors
    return got


@pytest.mark.parametrize("series", list(SERIES))
def test_20_numbers_taken_at_once_are_distinct_and_gap_free(db, series):
    got = _take_at_once(SERIES[series])
    assert len(got) == 20 and len(set(got)) == 20, got
    tails = sorted(int(n.replace("/", "-").rsplit("-", 1)[1]) for n in got)
    assert tails == list(range(1, 21)), tails  # 1 to 20: none skipped by the 5 that failed
    assert _take_at_once(SERIES[series], threads=1, failing=0)[0].endswith("0021")  # and the next follows on


def test_two_ra_bills_started_at_once_give_one_bill_and_one_refusal(boss, world):  # noqa: F811
    client, h = boss
    c = contract(client, h, world)
    start = threading.Barrier(2)
    codes: list[int] = []

    def one() -> None:
        tc = TestClient(app)
        start.wait()
        codes.append(tc.post(f"/api/finance/contracts/{c['id']}/ra-bills", json={"period_to": str(today())}, headers=h).status_code)

    ts = [threading.Thread(target=one) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(codes) == [201, 409], codes  # never two drafts, never a 500 on the unique seq
