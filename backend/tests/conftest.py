"""Test setup: every test run uses a fresh `eespl_test` database, never the dev database.

The database URL is switched before any app module that opens connections is imported.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.orm import Session

from app.config import settings

TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "eespl_test")  # a second run alongside: its own name
DEV_DB_NAME = make_url(settings.database_url).database
_test_url = make_url(os.environ.get("TEST_DATABASE_URL") or settings.database_url).set(
    database=TEST_DB_NAME
)
assert _test_url.database != DEV_DB_NAME, "tests must not run against the dev database"
# Tests never reach the real Kylas, whatever .env holds: Kylas is off and has no key. Tests
# that need it switch it on with a fake key and a mock transport (tests/test_crm.py).
settings.kylas_enabled = False
settings.kylas_api_key = None
settings.database_url = _test_url.render_as_string(hide_password=False)

from app.auth.security import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User  # noqa: E402

PER_TEST_TABLES = [
    "refresh_tokens", "audit_log", "user_roles", "password_links", "system_status", "help_texts",
    "building_models", "helper_answers", "issue_events", "issues",
    "variation_requests",
    "measure_billed", "measure_lines", "measure_sheets", "measure_items", "measure_edges",
    "measure_areas",
    "security_settings",
    "client_contacts", "clients", "library_lines", "library_items",
    "tc_template_clauses", "tc_templates", "tc_clauses",
    "tags", "company_gstins", "company_bank_accounts",
    "vendor_contacts", "vendor_bank_accounts", "vendor_products", "vendors",
    "boq_line_candidates", "boq_lines", "boq_sections", "boq_imports", "tender_tc",
    "tender_members", "tender_revisions", "tenders", "tender_sequences", "channels",
    "task_photos", "tasks", "area_scopes", "drawing_revisions", "drawings", "site_nodes",
    "site_members", "sites", "site_sequences",
    "kylas_outbox", "lead_activities", "leads", "lead_sequences", "kylas_cursors",
    "doc_sequences", "stock_ledger", "freight_entries", "site_issue_lines", "site_issues",
    "transfer_lines", "transfers", "grn_photos", "grn_lines", "grns", "po_charges", "po_lines",
    "po_indents", "purchase_orders", "rfq_quotes", "rfq_vendors", "rfq_lines", "rfq_indents",
    "rfqs", "indent_lines", "indents", "stores", "company_profile",
    "dpr_lines", "dpr_photos", "dprs", "attendance", "staff_attendance", "labour",
    "wo_measurements",
    "wo_lines",
    "work_orders", "inspections", "mom_points", "moms", "equipment_usage", "asset_movements",
    "assets", "site_budgets", "site_costs",
    "tally_exports", "labour_advances", "labour_wage_payments", "staff_advances", "payslips",
    "payroll_runs", "salary_structures", "petty_cash_entries", "petty_cash_accounts",
    "subcon_retention_releases", "subcon_bill_lines", "subcon_bills", "payment_allocations",
    "payments", "vendor_bill_lines", "vendor_bill_grns", "vendor_bills", "retention_releases",
    "receipt_allocations", "receipts", "invoice_lines", "tax_invoices", "ra_bill_lines", "ra_bills",
    "contract_lines", "client_contracts", "finance_settings",
    "notification_outbox", "notifications", "comments", "snag_photos", "snags", "site_documents",
    "site_portal", "portal_invites", "client_user_sites", "client_users",
    "alert_recipients", "alerts", "site_summaries", "monthly_summaries", "invoice_summaries",
    "progress_snapshots", "kpi_snapshots", "weekly_reports", "demo_rows", "analytics_settings",
    "ai_calls", "survey_boq_links", "survey_photos", "survey_areas", "surveys", "survey_settings",
    "quotation_followups", "quotation_files", "quotation_lines", "quotation_items", "quotations",
    "offer_item_lines", "offer_item_specs", "offer_items", "offer_lines", "spec_blocks",
    "quotation_references", "library_versions", "quotation_settings", "letterheads",
    "letter_templates", "offer_presets",
    "delivery_discrepancies", "delivery_note_lines", "debit_notes", "delivery_notes",
    "rate_contract_versions", "rate_contracts", "ready_to_bill", "new_area_requests",
    "productivity_norms", "sitecontrol_settings",
    "user_grants", "job_assignments", "site_visits", "negotiations", "measurements",
    "tender_bidders", "team_settings", "client_system_choices",
    "process_preferences", "process_events", "process_rules", "process_settings",
    "rate_group_lines", "rate_group_products", "rate_groups", "rate_workings", "freight_rates",
    "labour_bill_lines", "labour_bills", "labour_rate_cards", "costing_settings",
    "material_lot_lines", "material_lots", "project_plan_lines", "site_stage_days",
    "product_prices", "cad_areas", "cad_files", "cad_layer_maps", "takeoff_settings",
    "field_claim_extras", "field_claim_days", "field_claims", "field_gang_workers",
    "field_gang_visits", "field_points", "field_stops", "field_days", "field_travel_rates",
    "field_profiles", "field_consents", "field_settings", "field_holidays", "product_consumptions",
    "knowledge_matches", "knowledge_fixes", "knowledge_lines", "knowledge_templates",
    "knowledge_files",
    "knowledge_settings", "knowledge_product_reviews",
    "material_tests", "pond_tests", "prebid_queries", "methodology_files", "methodology_versions",
    "methodology_items", "methodologies", "standard_contradictions", "standard_rules",
    "standard_documents", "client_standards", "method_system_changes", "method_systems",
    "method_products",
    "tender_customers", "wo_deviations", "client_work_order_lines", "client_work_orders",
    "measurement_changes", "measurement_sets", "rfi_zones", "client_billing_cycles",
    "bill_tracking_steps", "payment_followups", "issue_comments", "issue_log", "labour_claims",
    "work_completions", "closeout_settings",
]  # fmt: skip
# seeded rows of truncated tables, put back after every test (copied once per run)
SEED_COPIES = [
    "finance_settings", "letter_templates", "letterheads", "quotation_settings",
    "security_settings",
]  # fmt: skip
# Tables that also hold seeded rows (unit conversions, categories), or are referenced by them
# (products), are cleaned with DELETE so the seed survives.
PER_TEST_DELETES = [
    "DELETE FROM unit_conversions WHERE product_id IS NOT NULL OR created_by IS NOT NULL",
    "DELETE FROM product_prices",
    "DELETE FROM stage_templates WHERE created_by IS NOT NULL",  # the seeded ones stay
    "DELETE FROM system_components",
    "DELETE FROM systems",
    "DELETE FROM products",
    "DELETE FROM categories WHERE id > :seeded_max_category",
    "DELETE FROM checklist_templates WHERE created_by IS NOT NULL",  # the seeded ones stay
    "DELETE FROM expense_categories WHERE created_by IS NOT NULL",  # the seeded ones stay
    "INSERT INTO finance_settings SELECT * FROM finance_settings_seed",
    "INSERT INTO letter_templates SELECT * FROM letter_templates_seed",
    "INSERT INTO letterheads SELECT * FROM letterheads_seed",
    "INSERT INTO quotation_settings SELECT * FROM quotation_settings_seed",
    "INSERT INTO security_settings SELECT * FROM security_settings_seed",
    "INSERT INTO company_profile (id) VALUES (1)",
    "INSERT INTO analytics_settings (id) VALUES (1)",
    "INSERT INTO sitecontrol_settings (id) VALUES (1)",
    "INSERT INTO team_settings (id) VALUES (1)",
    "INSERT INTO process_settings (id, wastage) VALUES "
    """(1, '{"raft": {"min": 5, "max": 7}, "footing": {"min": 12, "max": 15}}')""",
    "INSERT INTO survey_settings (id) VALUES (1)",
    "INSERT INTO costing_settings (id) VALUES (1)",
    "INSERT INTO takeoff_settings (id) VALUES (1)",
    "INSERT INTO field_settings (id) VALUES (1)",
    "INSERT INTO knowledge_settings (id, regions, old_after_months, last_run) "
    "VALUES (1, '{}', 12, '{}')",
    "DELETE FROM area_types WHERE created_by IS NOT NULL",  # the seeded ones stay
    "INSERT INTO stores (name, kind) VALUES ('Ethios Godown', 'godown')",
]

PASSWORD = "correct-horse-battery"
_PASSWORD_HASH = hash_password(PASSWORD)  # hashed once; argon2 is deliberately slow


def _recreate_database() -> None:
    admin = create_engine(_test_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        # a throwaway database: no need to wait for the disk on every commit
        conn.execute(text(f'ALTER DATABASE "{TEST_DB_NAME}" SET synchronous_commit = off'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[None]:
    _recreate_database()
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "migrations"))
    command.upgrade(cfg, "head")
    with engine.begin() as conn:  # the seeded rows, restored after every test
        for table in SEED_COPIES:
            conn.execute(text(f"CREATE TABLE {table}_seed AS SELECT * FROM {table}"))
    yield
    engine.dispose()


@pytest.fixture(scope="session")
def seeded_role_permissions(test_database) -> list[tuple]:
    with engine.connect() as conn:
        return conn.execute(
            # by role code: a migration test that downgrades and upgrades again re-creates the
            # later roles (director, planning...) with new ids
            text(
                "SELECT r.code, rp.permission_code, rp.scope FROM role_permissions rp "
                "JOIN roles r ON r.id = rp.role_id"
            )
        ).all()


@pytest.fixture(scope="session")
def seeded_max_category(test_database) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT coalesce(max(id), 0) FROM categories")).scalar_one()


@pytest.fixture(autouse=True)
def media_in_tmp(tmp_path, monkeypatch) -> Path:
    """Every test writes uploads, PDFs and delivery notes under its own temporary folder, never
    /media (CI cannot write there). A test's own media_dir monkeypatch still wins: it runs later."""
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(settings, "media_dir", str(media))
    return media


# which of the per-test tables hold rows: one query instead of truncating ~260 empty tables
_NONEMPTY = " UNION ALL ".join(
    f"SELECT '{t}' WHERE EXISTS (SELECT 1 FROM {t})" for t in PER_TEST_TABLES
)
_PERMS = (
    "SELECT md5(string_agg(r.code || '/' || rp.permission_code || '/' || rp.scope, ',' "
    "ORDER BY r.code, rp.permission_code, rp.scope)) FROM role_permissions rp "
    "JOIN roles r ON r.id = rp.role_id"
)


@pytest.fixture(scope="session")
def seeded_permissions_md5(seeded_role_permissions) -> str:
    with engine.connect() as conn:
        return conn.execute(text(_PERMS)).scalar_one()


@pytest.fixture(scope="session")
def referenced_by(test_database) -> dict[str, set[str]]:
    """{table: the per-test tables with a foreign key to it}: TRUNCATE needs them in the same
    statement, even when they are empty."""
    out: dict[str, set[str]] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ref.relname, src.relname FROM pg_constraint c "
                "JOIN pg_class src ON src.oid = c.conrelid "
                "JOIN pg_class ref ON ref.oid = c.confrelid "
                "WHERE c.contype = 'f'"
            )
        ).all()
    per_test = set(PER_TEST_TABLES)
    for ref, src in rows:
        if src in per_test and src != ref:
            out.setdefault(ref, set()).add(src)
    return out


# turning the foreign-key triggers off needs a superuser (the local and CI databases)
_CAN_SKIP_FK = [False]


@pytest.fixture(scope="session", autouse=True)
def _fk_switch(test_database) -> None:
    with engine.connect() as conn:
        _CAN_SKIP_FK[0] = bool(
            conn.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            ).scalar()
        )


def _with_referencing(used: list[str], referenced_by: dict[str, set[str]]) -> list[str]:
    todo, seen = list(used), set(used)
    while todo:
        for src in referenced_by.get(todo.pop(), ()):
            if src not in seen:
                seen.add(src)
                todo.append(src)
    return sorted(seen)


@pytest.fixture(autouse=True)
def clean_state(
    seeded_role_permissions, seeded_max_category, seeded_permissions_md5, referenced_by
) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        # Not TRUNCATE users CASCADE: every master table references users (created_by), and
        # that would also wipe the seeded units table. Only the tables the test wrote to
        # (TRUNCATE costs the same for an empty table as for a full one); the settings and
        # seed-copy tables always hold a row, so they are always reset.
        used = [r[0] for r in conn.execute(text(_NONEMPTY))]
        if used and _CAN_SKIP_FK[0]:
            # the few tables written to, emptied with their foreign-key checks off for this
            # transaction (every other per-test table is empty already): far cheaper than
            # TRUNCATE, which costs the same for every table it names
            conn.execute(text("SET LOCAL session_replication_role = replica"))
            for t in used:
                conn.execute(text(f"DELETE FROM {t}"))
            conn.execute(text("SET LOCAL session_replication_role = origin"))
        elif used:
            conn.execute(text(f"TRUNCATE {', '.join(_with_referencing(used, referenced_by))}"))
        for statement in PER_TEST_DELETES:
            conn.execute(text(statement), {"seeded_max_category": seeded_max_category})
        conn.execute(text("DELETE FROM users"))
        conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
        if conn.execute(text(_PERMS)).scalar_one() != seeded_permissions_md5:
            conn.execute(text("DELETE FROM role_permissions"))
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_code, scope) "
                    "SELECT id, :p, :s FROM roles WHERE code = :r"
                ),
                [{"r": r, "p": p, "s": s} for r, p, s in seeded_role_permissions],
            )


@pytest.fixture
def db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def make_user(db: Session) -> Callable[..., User]:
    def _make(email: str, *roles: str, is_active: bool = True, name: str | None = None) -> User:
        role_rows = list(db.scalars(select(Role).where(Role.code.in_(roles)))) if roles else []
        assert len(role_rows) == len(roles), f"unknown role in {roles}"
        user = User(
            email=email,
            full_name=name or email.split("@")[0],
            password_hash=_PASSWORD_HASH,
            is_active=is_active,
            roles=role_rows,
        )
        db.add(user)
        db.commit()
        return user

    return _make


def login(client: TestClient, email: str, password: str = PASSWORD) -> dict[str, str]:
    """Log in and return the Authorization header."""
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def login_as(make_user) -> Callable[..., tuple[TestClient, dict[str, str]]]:
    """Create a user with the given roles, log in with a fresh client, return (client, headers)."""

    def _login_as(*roles: str, email: str | None = None) -> tuple[TestClient, dict[str, str]]:
        email = email or f"{'-'.join(roles) or 'norole'}@example.com".replace("_", "-")
        make_user(email, *roles)
        c = TestClient(app)
        return c, login(c, email)

    return _login_as


def role_id(db: Session, code: str) -> int:
    return db.scalar(select(Role.id).where(Role.code == code))
