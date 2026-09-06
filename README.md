# Cohen Financial Balancing — Case Management Platform

Internal case management platform for **כהן איזונים פיננסיים** (Cohen Financial Balancing), an Israeli
financial/actuarial consultancy. The platform replaces the current Excel + Outlook + shared-folder
workflow with a single system of record for cases, people, deadlines, documents and activity history.

> **Project status: Phase 2 complete — authentication, sessions and internal user administration.**
> Phase 0 built the stack (PostgreSQL, Azurite, FastAPI, Next.js, the Hebrew RTL shell page, the
> same-origin `/api/v1/*` proxy and every quality gate). Phase 1 built the backend platform (typed
> settings, async SQLAlchemy, Alembic, the four infrastructure tables, a database-enforced append-only
> audit log, structured logging with request IDs, the error envelope, `/readyz`, integration tests
> against real PostgreSQL).
>
> Phase 2 makes those tables live. Working today, over the API: Argon2id password hashing behind an
> `AuthenticationProvider` boundary; opaque server-side sessions in HttpOnly cookies with
> session-bound CSRF tokens, idle and absolute expiry and immediate revocation; per-identity lockout
> and per-IP login throttling with a single uniform login failure; `ADMIN`/`EMPLOYEE` role gates;
> admin-provisioned staff accounts with a one-time temporary password and forced rotation;
> deactivation and reactivation; the staff directory; and audited authentication and
> user-administration events. A first administrator is created with `./scripts/create-admin`.
>
> **There is no login UI yet** — Phase 2 is API behaviour, and the browser screens are Phase 3. Also
> still absent: people, cases, documents and the dashboard.
>
> Documents marked _Planned_ describe the target design that later phases will implement; they are
> updated at the end of each phase so they always describe what is actually in the repository. See
> [`docs/roadmap.md`](docs/roadmap.md).
>
> Last reviewed: 2026-09-06

## What Release 1 delivers

An internal-only web application for the business owner (`ADMIN`) and employees (`EMPLOYEE`):

- Hebrew, RTL-first web UI (desktop-first, usable on smaller screens)
- Email + password authentication behind a provider abstraction (Entra ID comes later)
- People directory reused across cases (no duplicated contacts per case)
- Cases with typed statuses, full status history, and an internal case number (`YYYY-NNNN`) introduced by
  this application — allocated automatically, gapless and safe under concurrent creation
- Flexible case participants (parties, lawyers, others) and employee assignments
- Document requirements vs. document submissions, with immutable submission history and review outcomes
- File storage in Azure Blob Storage (Azurite locally) behind a storage abstraction — never in PostgreSQL
- Append-only business audit trail for every meaningful action
- Operational dashboard with real KPI queries, filters and sorting, including stuck/inactive cases
- A re-runnable import of the firm's existing cases and contacts from Excel, so this becomes the system
  of record rather than a second place to type things. Imported cases receive new internal numbers from
  this system; the column mapping and exact scope are pending review of a real export

Explicitly **out of scope** for Release 1: AI/LLM/RAG/OCR, client and lawyer portals, payments and
invoicing, Outlook/Microsoft 365 sync, email/SMS/WhatsApp automation, actuarial calculations,
advanced BI, and production cloud deployment. The architecture leaves room for all of them; see
[`docs/roadmap.md`](docs/roadmap.md).

## Technology

| Layer | Choice |
| --- | --- |
| Web | Next.js 16 (App Router), TypeScript 5.9 (strict), React 19, Tailwind CSS 4, shadcn/ui |
| API | Python 3.12, FastAPI, Pydantic v2 + pydantic-settings, SQLAlchemy 2.x (async, `asyncpg`), Alembic, structlog |
| Database | PostgreSQL 18 |
| Object storage | Azure Blob Storage (Azurite for local development) |
| Tests | pytest + httpx ASGI transport (API), Vitest + React Testing Library (web), Playwright (E2E, Phase 3+) |
| Local infra | Docker, Docker Compose v2 |
| Production target | Microsoft Azure (container hosting, Azure Database for PostgreSQL, Blob Storage, Key Vault, Application Insights) — Phase 10, nothing deployed in Release 1 |

Rationale for each choice is recorded in [`docs/decisions.md`](docs/decisions.md).

## Repository layout

```text
/
  apps/
    api/                 FastAPI service (Python, uv-managed)
      app/               Application package
        api/             Routers, middleware, exception handlers, dependencies
        audit/           Action catalogue and the audit recorder
        core/            Settings, logging, errors, request context, time
        db/              Engine, session, unit of work, base metadata, health check
        domain/          Pure logic and enums — no SQLAlchemy, no FastAPI
        models/          SQLAlchemy ORM mappings
        schemas/         Pydantic request/response models
      migrations/        Alembic environment and revisions
      tests/             pytest suite: unit/ (no database) and integration/ (real PostgreSQL)
    web/                 Next.js application (TypeScript)
      src/app/           App Router
      src/components/    Components, including the shadcn/ui primitives in ui/
      src/lib/           Utilities
      src/messages/      Hebrew message catalog
      tests/             Vitest + React Testing Library suite
  docs/                  Architecture and process documentation
  infra/docker/          Dockerfiles for the local api and web images
  scripts/               install, dev, check, test, migrate, create-admin
  .github/workflows/     GitHub Actions CI
  docker-compose.yml     Local stack: db, azurite, api, web
  .env.example           Documented environment variables, no real secrets
```

## Getting started

### Prerequisites

| Tool | Version | Notes |
| --- | --- | --- |
| Docker + Docker Compose | Compose v2 | Docker Desktop on macOS/Windows, Docker Engine on Linux |
| Node.js | 24 (see [`.nvmrc`](.nvmrc)) | Needed for the quality gates and for running the web app outside Docker |
| npm | 10+ | The repository uses npm workspaces; no other package manager |
| Python | 3.12 | `uv` downloads it automatically from [`apps/api/.python-version`](apps/api/.python-version) |
| [uv](https://docs.astral.sh/uv/) | 0.11+ | Python dependency management |

### Run the stack

```bash
git clone https://github.com/Yarden231/business-platform.git
cd business-platform
cp .env.example .env
docker compose up --build
```

`./scripts/dev` does the same thing and prints the URLs first.

| What | URL |
| --- | --- |
| Web application (Hebrew RTL) | <http://localhost:3000> |
| API, direct — developer diagnostics only | <http://localhost:8000> |
| API interactive documentation (non-production only) | <http://localhost:8000/docs> |
| Health through the same-origin proxy | <http://localhost:3000/api/v1/healthz> |
| Health, direct | <http://localhost:8000/healthz> |
| Readiness (is the database reachable?) | <http://localhost:8000/readyz> |

The `api` container runs `alembic upgrade head` before starting uvicorn, so a fresh clone — or a
branch switch that adds a migration — comes up with a schema that matches the code. Production does
not work this way; see [Database and migrations](#database-and-migrations).

The browser only ever talks to the web origin: Next.js rewrites `/api/v1/*` to the API service so the
session cookie stays first-party (ADR-0005). Port 8000 is published for diagnostics,
not for the application to use.

Two environment problems account for almost every failed first run:

- **A host port is already taken** — a locally installed PostgreSQL on 5432 is the usual case. Change
  `POSTGRES_PORT`, `API_PORT`, `WEB_PORT` or `AZURITE_BLOB_PORT` in `.env`. Only the host side of the
  mapping changes; the services still reach each other on their standard ports inside the Compose
  network, so nothing else needs adjusting.
- **macOS: `docker compose up` hangs while starting `api` or `web`.** Both bind-mount the source tree
  for hot reload, and macOS blocks that silently if Docker Desktop lacks access to the folder the
  repository lives in — `~/Desktop`, `~/Documents` and `~/Downloads` are all protected. Grant it under
  System Settings → Privacy & Security → Files and Folders (or Full Disk Access), or keep the clone
  somewhere unprotected such as `~/dev`. A hung mount can wedge the daemon, so restart Docker Desktop
  afterwards.

### Run without Docker

Running the two application processes on the host is the faster edit loop, and it avoids the
bind-mount problem above. The API needs a database, so start that one container first. Run
`./scripts/install` once, then give each command its own terminal:

```bash
docker compose up -d db
./scripts/migrate
```

```bash
cd apps/api && uv run uvicorn app.main:app --reload --port 8000
```

```bash
npm run dev -w apps/web
```

`DATABASE_URL` in `.env` is the host's view of that container, so nothing else needs configuring.
Both servers reload on save, and the URLs are the same as above. `next dev` reads `.env` files from
`apps/web/` rather than the repository root, so `API_INTERNAL_URL` stays unset and the rewrite falls
back to `http://localhost:8000` — where uvicorn is listening. Stop each server with `Ctrl+C`.

### Create the first administrator

The database ships with no accounts, and nothing seeds a default one — a known credential in a
repository is a vulnerability, not a convenience. Create the first `ADMIN` yourself, once, against a
migrated database:

```bash
./scripts/create-admin
```

It prompts for an email address, a full name and a password (twice, never echoed), applies the
password policy, stores an Argon2id hash and records a `USER_CREATED` audit event. For a scripted
environment, set `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_FULL_NAME` and `BOOTSTRAP_ADMIN_PASSWORD`
instead and it runs without prompting.

It only ever creates the *first* administrator: run it again and it reports the existing account and
changes nothing, so it is safe in a startup script and cannot quietly overwrite a password. Every
account after this one is created by that administrator through `POST /api/v1/users`. Use obviously
fake credentials locally, and never commit them.

There is no login page yet (Phase 3), so exercise the API directly:

```bash
curl -i -c jar.txt -X POST http://localhost:3000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.test","password":"…"}'

curl -s -b jar.txt http://localhost:3000/api/v1/auth/me
```

Mutating requests additionally need the CSRF token: read `csrf_token` out of the cookie jar and send
it as `X-CSRF-Token`. See [`docs/security.md`](docs/security.md) §3 and [`docs/api.md`](docs/api.md)
§4.

### Stop, and reset

```bash
docker compose down             # stop the stack, keep the data volumes
docker compose down --volumes   # also delete the PostgreSQL and Azurite volumes
```

Deleting the volumes is how you start from a clean database: the next `docker compose up` migrates an
empty one from scratch.

## Developer commands

Install the toolchain once, then use the scripts. Every one of them exits non-zero on failure.

```bash
./scripts/install   # uv sync + npm ci
./scripts/check     # every quality gate, exactly what CI runs
./scripts/test      # the API and web test suites only
./scripts/dev       # docker compose up --build
./scripts/migrate   # alembic upgrade head against DATABASE_URL
./scripts/create-admin  # create the first ADMIN account (interactive or env-driven)
```

`./scripts/check` runs, in order: Compose configuration validation, `ruff format --check`,
`ruff check`, `mypy`, `import-linter`, `pytest`, `prettier --check`, `eslint`, `tsc --noEmit`,
`vitest run` and the production Next.js build. [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
invokes the same script rather than restating the commands, so there is one definition of "passing".

`check` and `test` need PostgreSQL running (`docker compose up -d db`); they say so and stop rather
than failing halfway through. They load `.env`, so host tooling and the Compose stack read the same
configuration.

### Database and migrations

Migrations are the only way schema reaches a database. Nothing calls `Base.metadata.create_all()`,
including the tests — the test database is built by `alembic upgrade head` on every run, so a
migration that does not work from empty fails immediately rather than on the day it is deployed.

```bash
./scripts/migrate                                        # upgrade to the latest revision
cd apps/api
uv run alembic downgrade -1                              # undo the most recent revision
uv run alembic downgrade base                            # empty the schema entirely
uv run alembic current                                   # where this database is
uv run alembic revision --autogenerate -m "add cases"    # draft the next revision
```

An autogenerated revision is a starting point, not the artefact: read it, check that the downgrade is
really the inverse of the upgrade, and give constraints meaningful names. `./scripts/check` fails if
the models and the head revision disagree, so a model change without a migration cannot merge.

In development the `api` container migrates on start-up. **Production will not**: replicas must never
race each other to migrate, so the deployment pipeline runs `alembic upgrade head` once as its own
step before the new revision starts (Phase 10; see [`docs/architecture.md`](docs/architecture.md) §3).

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | System context, runtime topology, backend layering, request lifecycle, transactions, storage flow, frontend architecture, observability, environments |
| [`docs/domain-model.md`](docs/domain-model.md) | Entities, relationships, full planned schema, enums, invariants, case numbering algorithm, activity/archival semantics |
| [`docs/security.md`](docs/security.md) | Authentication, session and CSRF design, authorization model, upload security, audit immutability, secrets, privacy and compliance notes |
| [`docs/api.md`](docs/api.md) | REST conventions, error envelope, pagination, status-code policy, planned endpoint catalog |
| [`docs/roadmap.md`](docs/roadmap.md) | Phased implementation plan with deliverables and exit criteria per phase |
| [`docs/decisions.md`](docs/decisions.md) | Architecture decision records (ADRs) with context, decision and consequences |
| [`docs/open-questions.md`](docs/open-questions.md) | Specification contradictions/gaps and the decisions that need a human answer, each with a recommended default and the phase it blocks |

## Language policy

- **UI:** Hebrew only in Release 1, RTL by default, Hebrew date formatting, `Asia/Jerusalem` display timezone.
- **Code:** English only — table and column names, classes, variables, API paths, enum values, schemas,
  comments and commit messages.
- API responses carry stable machine-readable codes (e.g. `CASE_INVALID_STATUS_TRANSITION`); all
  Hebrew user-facing copy lives in the web application's message catalog (`apps/web/src/messages/he.ts`).
  This keeps future localization a frontend concern (see ADR-0014, ADR-0018).

## Secrets

No secret is ever committed. [`.env.example`](.env.example) holds documented placeholders only and
`.env` is git-ignored. The single exception is Azurite's published, well-known **emulator**
credentials, which grant access to nothing outside a local container and are labelled as such in
`.env.example`.

## Working agreement

Implementation proceeds phase by phase. Each phase must:

1. inspect the repository and the docs before changing anything;
2. implement only that phase's scope;
3. add or update automated tests, including authorization tests;
4. keep formatting, linting, type checking and tests green;
5. update the documents above so they continue to describe reality;
6. end with a report of files created/changed, migrations, tests, commands run, known limitations and
   the recommended next phase.
