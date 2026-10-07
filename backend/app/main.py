from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.auth.router import router as auth_router
from app.config import settings
from app.db import get_engine
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
from app.routers import audit, permissions, roles, users
from app.sites import routers as sites
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
