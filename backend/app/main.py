from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.analytics import routers as analytics
from app.auth.router import router as auth_router
from app.config import settings
from app.crm import routers as crm
from app.db import get_engine
from app.execution import assets as ex_assets
from app.execution import budget as ex_budget
from app.execution import dpr as ex_dpr
from app.execution import inspections as ex_inspections
from app.execution import labour as ex_labour
from app.execution import subcon as ex_subcon
from app.finance import billing as fin_billing
from app.finance import payables as fin_payables
from app.finance import payroll as fin_payroll
from app.finance import petty as fin_petty
from app.finance import reports as fin_reports
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
from app.portal import routers as portal
from app.portal import staff as portal_staff
from app.quotations import routers as quotations
from app.routers import audit, permissions, roles, users
from app.sites import routers as sites
from app.survey import routers as survey
from app.tenders import routers as tenders

app = FastAPI(title="EESPL App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
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
