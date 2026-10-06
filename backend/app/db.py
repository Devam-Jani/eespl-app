from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)


def get_engine() -> Engine:
    return engine
