# Contributing

## Migrations

- Test a new migration with `sh scripts/migration-roundtrip.sh`: upgrade, downgrade one step,
  upgrade again, each step only after the one before succeeded.
- When you run the steps by hand, chain them with `&&` (or `set -e` in a script) and look at
  each exit code. Never pipe a step through `tail`, `head` or `grep` inside the chain: the pipe
  returns the last command's exit code, so a failed `upgrade` is followed by a `downgrade` that
  drops tables and their rows on the dev database.
- A downgrade that drops a table loses its rows. Before running one on a database whose rows
  matter, take a dump: `docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backup.sql`
  (the file stays out of git, under `data/`).

## Tests

- The suite runs against its own `eespl_test` database, recreated at the start of each run.
- New tables go in `PER_TEST_TABLES` in `backend/tests/conftest.py` (settings rows in
  `PER_TEST_DELETES`); new permissions go in `backend/tests/test_permission_matrix.py`.
- After each test only the tables the test wrote to are emptied (foreign-key checks off for
  that transaction). Keep tests independent: never rely on another test's rows.
