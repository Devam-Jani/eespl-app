from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError

from app import search
from app.analytics import home
from app.analytics import routers as analytics
from app.auth import account as account_routes
from app.auth.router import router as auth_router
from app.building import routes as building
from app.closeout import portal_routes as closeout_portal
from app.closeout import routes as closeout
from app.closeout import screen_routes as closeout_screens
from app.config import settings
from app.costing import labour as labour_rates
from app.costing import prices as price_list
from app.costing import working_routes as rate_working
from app.crm import routers as crm
from app.db import get_engine
from app.execution import assets as ex_assets
from app.execution import budget as ex_budget
from app.execution import dpr as ex_dpr
from app.execution import inspections as ex_inspections
from app.execution import labour as ex_labour
from app.execution import subcon as ex_subcon
from app.field import routes as field
from app.finance import billing as fin_billing
from app.finance import payables as fin_payables
from app.finance import payroll as fin_payroll
from app.finance import petty as fin_petty
from app.finance import reports as fin_reports
from app.issues import routes as issues
from app.issues.fields import db_problem
from app.knowledge import routes as knowledge
from app.masters.routers import (
    admin_settings,
    channels,
    clients,
    library,
    products,
    systems,
    tc,
    vendors,
)
from app.material import routers as material
from app.methodology import routes as methodology
from app.ops import routes as ops
from app.ops.exports import ExportAudit
from app.portal import routers as portal
from app.portal import staff as portal_staff
from app.process import routers as process
from app.quotations import routers as quotations
from app.routers import audit, permissions, roles, users
from app.schedule import routes as schedule
from app.sitecontrol import routers as sitecontrol
from app.sites import routers as sites
from app.survey import routers as survey
from app.takeoff import routes as takeoff
from app.team import routers as team
from app.tenders import routers as tenders

app = FastAPI(title="EESPL App")

# every download (Excel, PDF ...) in the audit log


@app.exception_handler(RequestValidationError)
async def wrong_entry(request: Request, exc: RequestValidationError) -> JSONResponse:
    """A wrong entry: each field's problem and its fix in plain words (app.issues.fields)."""
    from app.issues.fields import to_detail  # noqa: PLC0415

    detail = to_detail(list(exc.errors()))
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": detail}))


@app.exception_handler(DataError)
async def out_of_range(request: Request, exc: DataError) -> JSONResponse:
    """A number too large for its column, or a value the database cannot take: a wrong entry."""
    return JSONResponse(status_code=422, content={"detail": db_problem(exc)[1]})


@app.exception_handler(IntegrityError)
async def broken_reference(request: Request, exc: IntegrityError) -> JSONResponse:
    """A record that does not exist (or was removed), a duplicate, a missing value: said
    plainly. Anything else stays a 5xx (recorded in the issue log)."""
    code, message = db_problem(exc)
    if code is None:
        raise exc
    return JSONResponse(status_code=code, content={"detail": message})


app.add_middleware(ExportAudit)
app.add_middleware(issues.RequestIds)  # every request's id; every 5xx in the issue log book

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(search.router)
app.include_router(home.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(permissions.router)
app.include_router(audit.router)
app.include_router(clients.router)
app.include_router(channels.router)
app.include_router(products.router)
app.include_router(systems.router)
app.include_router(library.router)
app.include_router(library.units_router)
app.include_router(tc.router)
app.include_router(vendors.router)
app.include_router(admin_settings.router)
app.include_router(tenders.router)
app.include_router(sites.router)
app.include_router(sites.templates_router)
app.include_router(crm.router)
app.include_router(crm.settings_router)
app.include_router(material.router)
for _module in (
    ex_dpr,
    ex_labour,
    ex_subcon,
    ex_inspections,
    ex_assets,
    ex_budget,
    fin_billing,
    fin_payables,
    fin_petty,
    fin_payroll,
    fin_reports,
    portal,
):
    app.include_router(_module.router)
for _r in (
    survey.router,
    quotations.router,
    sitecontrol.router,
    sitecontrol.public,
    team.router,
    process.router,
    price_list.router,
    rate_working.router,
    labour_rates.router,
    schedule.router,
    takeoff.router,
    building.router,
    building.tiles,
    issues.me,
    issues.router,
    field.router,
    knowledge.router,
    methodology.router,
    closeout.router,
    closeout_portal.router,
    closeout_screens.router,
    ops.router,
    account_routes.router,
    analytics.dashboard,
    analytics.router,
    portal_staff.router,
    portal_staff.snags_router,
    portal_staff.comments_router,
    portal_staff.notes_router,
):
    app.include_router(_r)


@app.get("/api/health")
def health(engine: Annotated[Engine, Depends(get_engine)]):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": "error", "detail": str(exc.__cause__ or exc)},
        )
    return {"status": "ok", "db": "ok"}
