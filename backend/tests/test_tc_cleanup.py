"""T&C library cleanup: duplicate keys, classification, the clean_tc run, templates, merges."""

import pytest
from sqlalchemy import select

from app.masters.importers import strip_list_number
from app.masters.models import TcClause, TcTemplate, TcTemplateClause
from app.masters.tc import (
    REVIEW_NOTE_LOST_NUMBER,
    clause_key,
    clean_tc,
    hidden_reason_for,
    needs_review_note,
)
from app.models import AuditLog

LABOUR = "Labour accommodation, water & electricity shall be provided by the Client."
LABOR = "Labor accommodation, water & electricity shall be provided by the Client."
LABOUR_NO_STOP = "Labour accommodation, water & electricity shall be provided by the Client"
EJ = (
    "The Technical Specification and Commercial Offer proposed in this BOQ does not cover "
    "treatment of expansion joints{}; any other work not specified above; in the structure, If "
    "any of these treatments is insisted on us to be done, separate orders should be placed "
    "with us for such treatment."
)
EJ_GROUTING = EJ.format(", grouting ")
EJ_PLAIN = EJ.format("")
EJ_SPACED = EJ.format(" ")


# --- normaliser ----------------------------------------------------------------------------


def test_labour_labor_and_full_stop_variants_share_a_key():
    assert clause_key(LABOUR) == clause_key(LABOR) == clause_key(LABOUR_NO_STOP)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Scaffolding and lifting shifting arrangement shall be provided by Client.",
         "Scaffolding and lifting shifting arrangement shall be provided by Client scope."),
        ("Scaffolding and lifting shifting arrangement shall be provided by Client.",
         "Scaffolding and lifting shifting arrangement shall be provided by Client"),
        ("All Samples / Mock-up will be in Contractor's Scope Aggree",
         "All Samples / Mock-up will be in Contractor's Scope Agree"),
        ("Treated area will be considerd for billing.",
         "Treated area will be considered for billing."),
        ("Rate inclusive of chemicals and application charges.",
         "Rate inclusive of chemicals and application charges"),
        ("GST @18% shall be charged extra at actual.", "GST @18% shall be charged extra at actual"),
        ("Scaffolding with eraction will be provide by Client.",
         "Scaffolding with erection will be provide by Client"),
        (EJ_PLAIN, EJ_SPACED),
    ],
)  # fmt: skip
def test_spelling_spacing_and_punctuation_variants_share_a_key(a, b):
    assert clause_key(a) == clause_key(b)


def test_with_and_without_grouting_are_different_clauses():
    assert clause_key(EJ_GROUTING) != clause_key(EJ_PLAIN)


# --- classifier ----------------------------------------------------------------------------

NOT_A_CLAUSE = [
    "Sr No. Description Remarks",
    "Technically Sound (YES OR NO)",
    "Transportation Charges",
    "Electricity Charges",
    "Scaffolding Work",
    "Other specific Requirements",
    "Labour Colony Facility",
    "Force Majeure / Exceptional Circumstances",
    "Prepared By - A Person HOD - Boughtout - Another Person Management",
    "Note Approve make: Asian Product",
    "0mm x 4.00mm Thik Hindalco or banco make powder coated aluminium expansion joint work fixed "
    "by 2nos M10 screw with washer @ 300mm center to center",
    "0mm x 1.50mm Thik Hindalco or banco make powder coated aluminium profile expansion joint",
    "x 15 Expansion Joint filling of Choksey Chemical Polysulphide sealant with backer rod "
    "Rs.850.00 R/Mt.",
]
CLIENT_CHECKLIST = [
    "Other Agencies Executed Work Protection will be in Contractor's Scope Aggree",
    "All Samples / Mock-up will be in Contractor's Scope Agree",
    "Labour License / Insurance of workers will be in Contractor's Scope Not Applicable",
    "Labor Colony will not be provided by the Client, Contractor has to Manage. In Civil "
    "Contractor Scope",
    "During the Guarantee Period Contractor has to do Free Service with Material & Scaffolding "
    "as Required. Aggree only for Waterproofing Scope",
    "Scaffolding will be in Contractor Scope with All the Materials Required if Any Scaffolding "
    "and lifting shifting arrangement shall be provided by Client.",
    "Material Unloading, Lifting and Shifting will be in Contractor's Scope Material lifting "
    "shifting arrangement (material hoist, crane, etc) shall be provided by the Client.",
]
PROJECT_SPECIFIC = [
    "Cement, Sand, Concrete, Brick bat shall be provided by PSP.",
    "Project time line: Project is planned to complete by Sept'25",
    "All Civil Material in our scope. (Rate Considered as per given : Cement : 280 per bag + "
    "GST, Sand : 800 per Tone + GST, Aggregate : 800 Rs per Tone + GST)",
    "Labour Colony Facility is provided at a cost of 1% of bill value",
]
REAL_CLAUSES = [
    "Rate inclusive of chemicals and application charges.",
    "Treated area will be considered for billing.",
    "No price escalation is allowed.",
    "GST @18% shall be charged extra at actual.",
    LABOUR,
    EJ_GROUTING,
    "Payment will be made based on actual work measured at site.",
    "Removing of PVC Pipe shall be done by Civil Contractor.",
    "Sufficient manpower to be provided by contractor For Speedy Execution PMC Engg in Charge "
    "will Decide the Required Manpower As per work front on site.",
    "Totally waterproof: all joints shall be sealed.",
    "% Retention Money To Be Deducted From All Running Bills.",  # flagged, not hidden
]


@pytest.mark.parametrize("text", NOT_A_CLAUSE)
def test_not_a_clause(text):
    assert hidden_reason_for(text) == "not_a_clause"


@pytest.mark.parametrize("text", CLIENT_CHECKLIST)
def test_client_checklist(text):
    assert hidden_reason_for(text) == "client_checklist"


@pytest.mark.parametrize("text", PROJECT_SPECIFIC)
def test_project_specific(text):
    assert hidden_reason_for(text) == "project_specific"


@pytest.mark.parametrize("text", REAL_CLAUSES)
def test_real_clauses_stay_active(text):
    assert hidden_reason_for(text) is None


@pytest.mark.parametrize(
    ("text", "flagged"),
    [
        ("% Retention Money To Be Deducted From All Running Bills.", True),
        ("% Advance payment against material delivery and remaining after 15 days.", True),
        ("0mm x 1.50mm Thik Hindalco ...", True),
        ("x 15 Expansion Joint filling ...", True),
        ("5 % Retention Money To Be Deducted.", False),
        ("Rate inclusive of chemicals and application charges.", False),
    ],
)
def test_lost_number_flag(text, flagged):
    assert (needs_review_note(text) == REVIEW_NOTE_LOST_NUMBER) is flagged


# --- importer number strip -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("1. Store with locking", "Store with locking"),
        ("12) Store with locking", "Store with locking"),
        ("(a) Store with locking", "Store with locking"),
        ("b. Store with locking", "Store with locking"),
        ("5 % Retention", "5 % Retention"),
        ("5% Retention", "5% Retention"),
        ("20mm x 4.00mm Thick", "20mm x 4.00mm Thick"),
        ("100 mm thick screed", "100 mm thick screed"),
        ("i.e. Cement in client scope", "i.e. Cement in client scope"),
        ("GST @18% extra", "GST @18% extra"),
    ],
)
def test_importer_strips_only_list_numbers(raw, clean):
    assert strip_list_number(raw) == clean


# --- the cleanup run -----------------------------------------------------------------------


def _clause(db, text, usage, category="general"):
    c = TcClause(text=text, category=category, usage_count=usage, own_usage_count=usage)
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def seeded(db):
    """A small library with the same kinds of noise as the real one, and a template that
    holds two copies of the Labour clause and a header row."""
    c = {
        "labour": _clause(db, LABOUR, 366, "client_scope"),
        "labor": _clause(db, LABOR, 123, "client_scope"),
        "labour_no_stop": _clause(db, LABOUR_NO_STOP, 7, "client_scope"),
        "ej_grouting": _clause(db, EJ_GROUTING, 120, "rates"),
        "ej_plain": _clause(db, EJ_PLAIN, 59, "rates"),
        "ej_spaced": _clause(db, EJ_SPACED, 53, "rates"),
        "rate": _clause(db, "Rate inclusive of chemicals and application charges.", 399, "rates"),
        "treated": _clause(db, "Treated area will be considered for billing.", 112, "payment"),
        "header": _clause(db, "Sr No. Description Remarks", 25),
        "checklist": _clause(db, CLIENT_CHECKLIST[0], 15),
        "psp": _clause(db, PROJECT_SPECIFIC[0], 39),
        "retention": _clause(db, "% Retention Money To Be Deducted.", 25, "payment"),
    }
    template = TcTemplate(
        name="EESPL Standard",
        is_default=True,
        clauses=[
            TcTemplateClause(clause_id=c[k].id, sort_order=i)
            for i, k in enumerate(["rate", "labour", "labor", "header", "treated"], start=1)
        ],
    )
    db.add(template)
    db.commit()
    return c


def _state(db):
    rows = db.scalars(select(TcClause).order_by(TcClause.id))
    clauses = [
        (c.id, c.status, c.hidden_reason, c.merged_into_id, c.usage_count, c.needs_review)
        for c in rows
    ]
    templates = [
        (t.name, [tc.clause_id for tc in t.clauses]) for t in db.scalars(select(TcTemplate))
    ]
    return clauses, templates


def test_clean_tc_merges_hides_flags_and_fixes_the_template(seeded, db):
    summary = clean_tc(db)
    db.commit()
    c = {k: db.get(TcClause, v.id) for k, v in seeded.items()}

    assert summary.groups_merged == 2 and summary.clauses_merged == 3
    assert c["labor"].merged_into_id == c["labour_no_stop"].merged_into_id == c["labour"].id
    assert c["labour"].usage_count == 366 + 123 + 7
    assert c["ej_spaced"].merged_into_id == c["ej_plain"].id  # spacing variant
    assert c["ej_grouting"].merged_into_id is None  # grouting changes the scope
    assert summary.hidden == {"not_a_clause": 1, "client_checklist": 1, "project_specific": 1}
    assert (c["header"].hidden_reason, c["checklist"].hidden_reason, c["psp"].hidden_reason) == (
        "not_a_clause", "client_checklist", "project_specific",
    )  # fmt: skip
    assert c["retention"].needs_review and c["retention"].status == "active"
    assert summary.flagged == 1

    template = db.scalar(select(TcTemplate))
    assert [tc.clause_id for tc in template.clauses] == [
        c["rate"].id, c["labour"].id, c["treated"].id,
    ]  # fmt: skip
    assert summary.templates == {"EESPL Standard": 3}


def test_clean_tc_twice_changes_nothing_the_second_time(seeded, db):
    clean_tc(db)
    db.commit()
    before = _state(db)
    second = clean_tc(db)
    db.commit()
    assert (second.groups_merged, second.clauses_merged, second.flagged) == (0, 0, 0)
    assert sum(second.hidden.values()) == 0
    assert _state(db) == before


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def cleaned(seeded, db):
    clean_tc(db)
    db.commit()
    return {k: v.id for k, v in seeded.items()}


def test_list_hides_hidden_and_merged_and_shows_variants(cleaned, login_as):
    client, headers = login_as("sales")  # library.view
    items = client.get("/api/tc/clauses", headers=headers).json()["items"]
    ids = {i["id"] for i in items}
    assert cleaned["labor"] not in ids and cleaned["header"] not in ids
    labour = next(i for i in items if i["id"] == cleaned["labour"])
    assert labour["variant_count"] == 2
    assert {v["text"] for v in labour["variants"]} == {LABOR, LABOUR_NO_STOP}

    everything = client.get(
        "/api/tc/clauses", params={"include_hidden": "true"}, headers=headers
    ).json()["items"]
    header = next(i for i in everything if i["id"] == cleaned["header"])
    assert (header["status"], header["hidden_reason"]) == ("hidden", "not_a_clause")
    assert cleaned["labor"] not in {i["id"] for i in everything}  # variants only inside masters

    review = client.get("/api/tc/clauses", params={"needs_review": "true"}, headers=headers).json()
    assert [i["id"] for i in review["items"]] == [cleaned["retention"]]


def test_template_never_holds_hidden_or_merged_clauses(cleaned, login_as, db):
    client, headers = login_as("estimator")
    template_id = db.scalar(select(TcTemplate.id))
    for bad in ("header", "labor"):
        r = client.patch(
            f"/api/tc/templates/{template_id}",
            json={"clause_ids": [cleaned["rate"], cleaned[bad]]},
            headers=headers,
        )
        assert r.status_code == 422, bad

    # merging a clause that is in a template swaps in the master (no duplicate)
    r = client.patch(
        f"/api/tc/templates/{template_id}",
        json={"clause_ids": [cleaned["rate"], cleaned["ej_grouting"], cleaned["ej_plain"]]},
        headers=headers,
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/tc/clauses/{cleaned['ej_grouting']}/merge",
        json={"into_id": cleaned["ej_plain"]},
        headers=headers,
    )
    assert r.status_code == 200
    template = client.get(f"/api/tc/templates/{template_id}", headers=headers).json()
    assert [c["id"] for c in template["clauses"]] == [cleaned["rate"], cleaned["ej_plain"]]

    # hiding a clause takes it out of templates
    client.post(f"/api/tc/clauses/{cleaned['rate']}/hide", json={"reason": "manual"},
                headers=headers)  # fmt: skip
    template = client.get(f"/api/tc/templates/{template_id}", headers=headers).json()
    assert [c["id"] for c in template["clauses"]] == [cleaned["ej_plain"]]


def test_unmerge_restores_usage_counts_and_sticks(cleaned, login_as, db):
    client, headers = login_as("estimator")
    r = client.post(f"/api/tc/clauses/{cleaned['labor']}/unmerge", headers=headers)
    assert r.status_code == 200
    assert (r.json()["usage_count"], r.json()["merged_into_id"]) == (123, None)
    master = db.get(TcClause, cleaned["labour"])
    db.refresh(master)
    assert master.usage_count == 366 + 7

    # a person's unmerge is not undone by the next cleanup (fresh state, as the CLI has)
    db.expire_all()
    clean_tc(db)
    db.commit()
    assert db.get(TcClause, cleaned["labor"]).merged_into_id is None

    r = client.post(f"/api/tc/clauses/{cleaned['labour_no_stop']}/unmerge", headers=headers)
    master = client.get("/api/tc/clauses", headers=headers).json()["items"]
    assert next(i for i in master if i["id"] == cleaned["labour"])["usage_count"] == 366
    actions = [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "tc_clause"))]
    assert actions.count("tc_clause.unmerge") == 2


def test_editing_text_clears_needs_review_and_hide_unhide(cleaned, login_as):
    client, headers = login_as("estimator")
    r = client.patch(
        f"/api/tc/clauses/{cleaned['retention']}",
        json={"text": "5 % Retention Money To Be Deducted."},
        headers=headers,
    )
    assert r.status_code == 200
    assert (r.json()["needs_review"], r.json()["review_note"]) == (False, None)

    r = client.post(f"/api/tc/clauses/{cleaned['header']}/unhide", headers=headers)
    assert (r.json()["status"], r.json()["hidden_reason"]) == ("active", None)
    r = client.post(f"/api/tc/clauses/{cleaned['treated']}/hide", json={"reason": "bogus"},
                    headers=headers)  # fmt: skip
    assert r.status_code == 422


def test_cleanup_actions_need_library_edit(cleaned, login_as):
    client, headers = login_as("sales")  # library.view only
    cid = cleaned["treated"]
    assert client.post(f"/api/tc/clauses/{cid}/hide", json={}, headers=headers).status_code == 403
    assert client.post(f"/api/tc/clauses/{cid}/unhide", headers=headers).status_code == 403
    assert client.post(f"/api/tc/clauses/{cid}/merge", json={"into_id": cleaned["rate"]},
                       headers=headers).status_code == 403  # fmt: skip
    assert client.post(f"/api/tc/clauses/{cid}/unmerge", headers=headers).status_code == 403
    assert client.post(f"/api/tc/clauses/{cid}/reviewed", headers=headers).status_code == 403
