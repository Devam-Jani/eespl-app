# EESPL App

FastAPI + PostgreSQL 16 backend, React + TypeScript (Vite) frontend, all run with Docker Compose.
Includes logins, users, roles and permissions (RBAC) and an audit log.

| Service | Container   | Host port | Container port |
|---------|-------------|-----------|----------------|
| db      | `eespl-db`  | 5434      | 5432           |
| api     | `eespl-api` | 8001      | 8000           |
| web     | `eespl-web` | 5174      | 5173           |

Ports are chosen so they don't clash with the ethios_loyalty app (5173, 8000, 5433).

## Run with Docker

```sh
cp .env.example .env        # then set a real POSTGRES_PASSWORD (same value in DATABASE_URL) and JWT_SECRET
docker compose up -d --build
```

- Frontend: http://localhost:5174
- Health check: http://localhost:8001/api/health → `{"status":"ok","db":"ok"}` (HTTP 503 with details if the database is unreachable)

The `api` container runs `alembic upgrade head` on start, then serves with auto-reload. `./backend` and `./frontend` are bind-mounted, so code changes are picked up live.

## First admin

There is no sign-up. Create the first super admin from the command line (it prompts for the password, minimum 10 characters):

```sh
docker compose exec api python -m app.cli create-admin --email admin@ethiosenviro.com --name "Admin Name"
```

Then sign in at http://localhost:5174 and create everyone else under **Administration → Users**.
If an admin is locked out or forgets their password:

```sh
docker compose exec api python -m app.cli set-password --email admin@ethiosenviro.com
```

## Auth and permissions

- `POST /api/auth/login` returns a 15-minute access token (JWT, sent as `Authorization: Bearer …`) and sets a 7-day refresh token in an httpOnly, SameSite=Lax cookie. The refresh token is stored hashed and rotated on every `POST /api/auth/refresh`. `POST /api/auth/logout` revokes it. `GET /api/auth/me` returns the user, their roles and their permissions as `{code: scope}`.
- 5 failed logins lock the account for 15 minutes. Inactive users cannot log in or refresh.
- Permissions (e.g. `tender.edit`) are granted to roles with a scope: `all`, `assigned` (only sites or tenders the user is assigned to) or `own` (only records the user created). A user with several roles gets the widest scope.
- Endpoints guard themselves with `require_permission("code")` (`backend/app/auth/deps.py`), which returns the caller's scope or responds 403. Never check role names in endpoint code.
- Nobody can grant permissions, or manage a user who holds permissions, beyond their own. Client users can never hold `tender.margin`, `finance.edit` or any `admin.*` permission.
- The permission catalogue and the 8 system roles are seeded by migration `0003`. System roles cannot be deleted, and `super_admin` always has every permission.
- Logins, failed logins, lockouts and every change to users and roles are written to `audit_log` (see **Administration → Audit log**).

## Common commands

```sh
docker compose exec api pytest -q          # backend tests (creates and migrates a separate eespl_test database)
docker compose exec api ruff check .       # lint
docker compose exec api alembic current    # current migration
docker compose exec api alembic revision -m "describe change"   # new migration
docker compose logs -f api
docker compose down                        # stop (data is kept in the eespl_pgdata volume)
```

## Running outside Docker

Start only the database with `docker compose up -d db`, then:

```sh
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8001           # settings are read from ../.env (DATABASE_URL uses localhost:5434)

cd ../frontend
npm install
npm run dev -- --port 5174                          # proxies /api to http://localhost:8001
npm run lint
```

## Layout

```
backend/    FastAPI app (app/), Alembic migrations (migrations/), tests (tests/)
frontend/   Vite + React + TypeScript
.github/    CI: ruff, alembic check, pytest against Postgres; frontend lint and build
```
