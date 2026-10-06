# EESPL App

Project skeleton: FastAPI + PostgreSQL 16 backend, React + TypeScript (Vite) frontend, all run with Docker Compose.

| Service | Container   | Host port | Container port |
|---------|-------------|-----------|----------------|
| db      | `eespl-db`  | 5434      | 5432           |
| api     | `eespl-api` | 8001      | 8000           |
| web     | `eespl-web` | 5174      | 5173           |

Ports are chosen so they don't clash with the ethios_loyalty app (5173, 8000, 5433).

## Run with Docker

```sh
cp .env.example .env        # then set a real POSTGRES_PASSWORD (and the same value in DATABASE_URL)
docker compose up -d --build
```

- Frontend: http://localhost:5174
- Health check: http://localhost:8001/api/health → `{"status":"ok","db":"ok"}` (HTTP 503 with details if the database is unreachable)

The `api` container runs `alembic upgrade head` on start, then serves with auto-reload. `./backend` and `./frontend` are bind-mounted, so code changes are picked up live.

## Common commands

```sh
docker compose exec api pytest -q          # backend tests (uses the eespl database)
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
```

## Layout

```
backend/    FastAPI app (app/), Alembic migrations (migrations/), tests (tests/)
frontend/   Vite + React + TypeScript
.github/    CI: ruff + pytest against Postgres, frontend build
```
