"""Container health checks that need the database.

    python -m app.ops.check worker    # the worker's heartbeat is at most three minutes old
"""

import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine, text

from app.config import settings
from app.ops.service import WORKER_STALE


def main(argv: list[str]) -> int:
    if argv[:1] != ["worker"]:
        print(__doc__)
        return 2
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        at = conn.execute(text("SELECT at FROM system_status WHERE key = 'worker'")).scalar()
    return 0 if at is not None and datetime.now(UTC) - at < WORKER_STALE else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
