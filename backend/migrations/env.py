from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.analytics.models  # noqa: F401  (registers the analytics tables and indexes)
import app.building.models  # noqa: F401  (the X-ray 3D building model)
import app.closeout.models
import app.costing.models  # noqa: F401  (rate working, freight, labour rates and bills)
import app.crm.models  # noqa: F401  (registers the CRM tables)
import app.execution.models  # noqa: F401  (registers the execution tables)
import app.field.models  # noqa: F401  (field tracking and the travel claim)
import app.finance.models  # noqa: F401  (registers the finance tables)
import app.issues.models  # noqa: F401  (the issue log book)
import app.knowledge.models  # noqa: F401  (the BOQ knowledge library)
import app.masters.models  # noqa: F401  (registers the master tables)
import app.material.models  # noqa: F401  (registers the material tables)
import app.methodology.models  # noqa: F401  (the methodology builder)
import app.ops.models  # noqa: F401  (work orders, billing, close-out)
import app.portal.models  # noqa: F401  (registers the portal tables)
import app.process.models  # noqa: F401  (registers the process tables)
import app.quotations.models  # noqa: F401  (registers the quotation tables)
import app.schedule.models  # noqa: F401  (project plan, lots, stage days)
import app.sitecontrol.models  # noqa: F401  (registers the site control tables)
import app.sites.models  # noqa: F401  (registers the site tables)
import app.survey.models  # noqa: F401  (registers the survey tables)
import app.takeoff.models  # noqa: F401  (AutoCAD takeoff)
import app.team.models  # noqa: F401  (registers the team tables)
import app.tenders.models  # noqa: F401  (registers the tender tables)
from app.config import settings
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
