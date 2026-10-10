from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.analytics.models  # noqa: F401  (registers the analytics tables and indexes)
import app.crm.models  # noqa: F401  (registers the CRM tables)
import app.execution.models  # noqa: F401  (registers the execution tables)
import app.finance.models  # noqa: F401  (registers the finance tables)
import app.masters.models  # noqa: F401  (registers the master tables)
import app.material.models  # noqa: F401  (registers the material tables)
import app.portal.models  # noqa: F401  (registers the portal tables)
import app.quotations.models  # noqa: F401  (registers the quotation tables)
import app.sitecontrol.models  # noqa: F401  (registers the site control tables)
import app.sites.models  # noqa: F401  (registers the site tables)
import app.survey.models  # noqa: F401  (registers the survey tables)
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
