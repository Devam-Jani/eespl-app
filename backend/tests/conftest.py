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

TEST_DB_NAME = "eespl_test"
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
    "refresh_tokens", "audit_log", "user_roles",
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
    "dpr_photos", "dprs", "attendance", "staff_attendance", "labour", "wo_measurements", "wo_lines",
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
]  # fmt: skip
# seeded rows of truncated tables, put back after every test (copied once per run)
SEED_COPIES = ["finance_settings", "letter_templates", "letterheads", "quotation_settings"]
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
    "INSERT INTO company_profile (id) VALUES (1)",
    "INSERT INTO analytics_settings (id) VALUES (1)",
    "INSERT INTO sitecontrol_settings (id) VALUES (1)",
    "INSERT INTO survey_settings (id) VALUES (1)",
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
            text("SELECT role_id, permission_code, scope FROM role_permissions")
        ).all()


@pytest.fixture(scope="session")
def seeded_max_category(test_database) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT coalesce(max(id), 0) FROM categories")).scalar_one()


@pytest.fixture(autouse=True)
def clean_state(seeded_role_permissions, seeded_max_category) -> Iterator[None]:
    yield
    with engine.begin() as conn:
        # Not TRUNCATE users CASCADE: every master table references users (created_by), and
        # that would also wipe the seeded units table.
        conn.execute(text(f"TRUNCATE {', '.join(PER_TEST_TABLES)}"))
        for statement in PER_TEST_DELETES:
            conn.execute(text(statement), {"seeded_max_category": seeded_max_category})
        conn.execute(text("DELETE FROM users"))
        conn.execute(text("DELETE FROM roles WHERE NOT is_system"))
        conn.execute(text("DELETE FROM role_permissions"))
        conn.execute(
            text("INSERT INTO role_permissions VALUES (:r, :p, :s)"),
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
