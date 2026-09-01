# Cohen Financial Balancing — Case Management Platform

Internal case management platform for **כהן איזונים פיננסיים** (Cohen Financial Balancing), an Israeli
financial/actuarial consultancy. The platform replaces the current Excel + Outlook + shared-folder
workflow with a single system of record for cases, people, deadlines, documents and activity history.

> **Project status: architecture and planning.**
> No application code exists yet. This repository currently contains only the agreed architecture,
> domain model, security model, API contract, roadmap and decision log. Every document marked
> _Planned_ describes the target design that Release 1 will implement — it does not describe existing
> code. Documents are updated at the end of each implementation phase so that they always describe
> what is actually in the repository.
>
> Last reviewed: 2026-09-01

## What Release 1 delivers

An internal-only web application for the business owner (`ADMIN`) and employees (`EMPLOYEE`):

- Hebrew, RTL-first web UI (desktop-first, usable on smaller screens)
- Email + password authentication behind a provider abstraction (Entra ID comes later)
- People directory reused across cases (no duplicated contacts per case)
- Cases with automatic, concurrency-safe internal numbers (`YYYY-NNNN`), typed statuses and full status history
- Flexible case participants (parties, lawyers, others) and employee assignments
- Document requirements vs. document submissions, with immutable submission history and review outcomes
- File storage in Azure Blob Storage (Azurite locally) behind a storage abstraction — never in PostgreSQL
- Append-only business audit trail for every meaningful action
- Operational dashboard with real KPI queries, filters and sorting, including stuck/inactive cases
- A one-time, re-runnable import of the firm's existing cases and contacts from Excel, so this becomes
  the system of record rather than a second place to type things

Explicitly **out of scope** for Release 1: AI/LLM/RAG/OCR, client and lawyer portals, payments and
invoicing, Outlook/Microsoft 365 sync, email/SMS/WhatsApp automation, actuarial calculations,
advanced BI, and production cloud deployment. The architecture leaves room for all of them; see
[`docs/roadmap.md`](docs/roadmap.md).

## Technology

| Layer | Choice |
| --- | --- |
| Web | Next.js (App Router), TypeScript (strict), React, Tailwind CSS, shadcn/ui |
| API | Python, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic |
| Database | PostgreSQL |
| Object storage | Azure Blob Storage (Azurite for local development) |
| Tests | pytest + httpx ASGI transport (API), Vitest + React Testing Library (web), Playwright (E2E) |
| Local infra | Docker, Docker Compose |
| Production target | Microsoft Azure (container hosting, Azure Database for PostgreSQL, Blob Storage, Key Vault, Application Insights) |

Rationale for each choice is recorded in [`docs/decisions.md`](docs/decisions.md).

## Planned repository layout

```text
/
  apps/
    api/                 FastAPI service (Python, uv-managed)
    web/                 Next.js application (TypeScript)
  docs/                  Architecture and process documentation (this is what exists today)
  infra/                 Dockerfiles, local infra, future Azure IaC
  scripts/               Developer and operational scripts
  docker-compose.yml     Local development stack: db, azurite, api, web
  .env.example           Documented environment variables, no real secrets
  README.md
```

`apps/api` and `apps/web` are created in Phase 0; see [`docs/roadmap.md`](docs/roadmap.md).

## Getting started

Not available yet — the development stack is created in **Phase 0** of the roadmap. Once Phase 0 is
merged, local setup will be:

```bash
git clone https://github.com/Yarden231/business-platform.git
cd business-platform
cp .env.example .env
docker compose up --build
```

with the web app on `http://localhost:3000`, the API on `http://localhost:8000`, PostgreSQL and
Azurite running as containers, and Alembic migrations applied on API start-up in development.

Until then, the only prerequisites worth verifying are Docker (with Compose v2+), Node.js 22+ and
Python 3.12+ with [`uv`](https://docs.astral.sh/uv/).

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
  Hebrew user-facing copy lives in the web application's message catalog. This keeps future
  localization a frontend concern (see ADR-0014, ADR-0018).

## Working agreement

Implementation proceeds phase by phase. Each phase must:

1. inspect the repository and the docs before changing anything;
2. implement only that phase's scope;
3. add or update automated tests, including authorization tests;
4. keep formatting, linting, type checking and tests green;
5. update the documents above so they continue to describe reality;
6. end with a report of files created/changed, migrations, tests, commands run, known limitations and
   the recommended next phase.
