# Implementation roadmap

> **Status:** Planning. Phase 0 has not started. This document is the agreed sequencing for Release 1;
> each phase updates it with actual status on completion.
> Last reviewed: 2026-09-01

## How phases are sequenced

Three principles shaped the order:

Release 1 is Phases 0–9. Phase 10 is listed for continuity and is explicitly outside Release 1.

1. **De-risk the integration seams early.** The cookie/CSRF/same-origin proxy flow and the Hebrew RTL
   shell are the two things most likely to force rework, so a thin vertical slice (login, end to end,
   in the real browser) lands in Phase 3 rather than after all backend work.
2. **Every phase is independently reviewable and leaves the repository green.** No phase ends with a
   half-migrated schema, a failing test, or a placeholder endpoint.
3. **Data modelling comes before the features that depend on it**, because migrations are the most
   expensive thing to get wrong.

Each phase carries the same definition of done: code + migrations + tests + green quality gates +
documentation updated + a report of what changed.

## Phase 0 — Foundation and toolchain

**Goal:** a running, empty, fully linted monorepo that any developer can start in one command.

- Monorepo layout (`apps/api`, `apps/web`, `docs`, `infra`, `scripts`), npm workspaces for the web
  side, `uv` + `pyproject.toml` for the API, pinned language and image versions.
- `docker-compose.yml` with `db`, `azurite`, `api`, `web`; named volumes; healthchecks; the
  `/api/v1/*` same-origin proxy configured in Next.js.
- `.env.example` documenting every variable; `.gitignore`; git repository initialised.
- Quality gates wired and passing on an empty codebase: `ruff` (format + lint), `mypy`,
  `import-linter` contract, `pytest` (one smoke test), `eslint`, `prettier`, `tsc --noEmit`, `vitest`.
- `scripts/` (or `Makefile`) entry points: `dev`, `check`, `test`, `migrate`, used identically by CI.
- GitHub repository and GitHub Actions workflow running exactly the same gates as `scripts/check`
  (decided during planning).

**Exit criteria:** `docker compose up` serves a Hebrew RTL "hello" page and a `/healthz` API response;
`scripts/check` passes; no application logic exists yet.

## Phase 1 — Backend platform

**Goal:** the API skeleton every later phase plugs into.

- `Settings` via `pydantic-settings`, including `CASE_INACTIVITY_THRESHOLD_DAYS`, upload limits,
  session lifetimes, Argon2 parameters; production start-up guards.
- Async SQLAlchemy engine and session dependency; declarative base with the constraint naming
  convention; unit-of-work/transaction boundary helper.
- Alembic configured for async with the first migration: `pg_trgm` extension, `users`,
  `user_identities`, `sessions`, `activity_log` and its append-only trigger.
- `audit/` recorder and action catalogue; `core/errors.py` with the error envelope and exception
  handlers; `structlog` JSON logging with `request_id` middleware; security headers; `/healthz`,
  `/readyz`.
- Integration test harness: test database created by `alembic upgrade head`,
  transaction-per-test isolation, factories.

**Exit criteria:** migrations up and down cleanly; an audit row can be written and cannot be updated
or deleted (test proves the trigger fires); error envelope and logging verified by tests.

## Phase 2 — Identity and authorization

**Goal:** real authentication and the authorization primitives, fully tested.

- Argon2id hashing; `AuthenticationProvider` protocol + `PasswordAuthenticationProvider`.
- Server-side sessions, cookie issuance, CSRF double-submit bound to the session, idle/absolute
  expiry, revocation on logout and password change.
- Login throttling and identity lockout; uniform failure responses; authentication audit events.
- `auth/policies.py`, `get_current_user`, `require_role`; user management endpoints; staff directory
  endpoint; own-password change.
- Temporary-password issuance shown once at user creation, `must_change_password` gating every other
  endpoint until rotation, and admin re-issue for lockouts (ADR-0026).
- Admin bootstrap: `scripts/create_admin.py` (interactive/env-driven, never a hardcoded credential).

**Exit criteria:** tests for unauthenticated rejection, wrong password, lockout, CSRF rejection,
session revocation on logout, employee blocked from user management, and no user enumeration through
response differences.

## Phase 3 — Web shell and authentication UI

**Goal:** prove the whole browser→proxy→API→cookie loop and the Hebrew RTL foundation before building
features on top of it.

- Next.js App Router structure, `<html lang="he" dir="rtl">`, Hebrew webfont, Tailwind configured for
  logical properties, shadcn/ui initialised and RTL-verified on the primitives Release 1 needs.
- `messages/he.ts` catalog + `t()` helper; error-code → Hebrew mapper; date/number formatting helpers
  pinned to `he-IL` / `Asia/Jerusalem`.
- Typed API client, generated OpenAPI types with the CI freshness check, TanStack Query provider,
  CSRF header handling.
- Login page, forced password change, application shell (nav, user menu, logout), protected layout
  redirecting on `401`, accessible form errors in Hebrew.
- Vitest + RTL component tests; first Playwright test: log in, land on the shell, log out.

**Exit criteria:** an admin created by the Phase 2 script can log in and out in a real browser; RTL
layout reviewed; no Hebrew string outside the catalog; `tsc --noEmit` clean with no `any`.

## Phase 4 — People directory

**Goal:** the first business entity, end to end.

- Migration for `people` with the partial unique ID index and trigram indexes.
- Israeli ID validation (format + check digit) in `domain`, unit tested; duplicate detection returning
  `409`.
- Endpoints: list/search with pagination, create, read, update, archive/unarchive, person's cases.
- Audit events for create/update/archive with the redaction policy applied to `id_number`.
- UI: people list with search, create/edit forms (`react-hook-form` + `zod`), person detail, archive
  action visible only where permitted.
- `PersonSummary` / `PersonDetail` split, so an employee's directory search returns masked results and
  full detail only for people in their assigned cases (ADR-0027).
- Tests: validation, duplicate ID, archived people excluded from pickers but still resolvable, and an
  employee receiving summary-only data for a person outside their cases.

**Exit criteria:** the same person can be reused across cases in Phase 5 without duplication;
authorization tests for every endpoint. Requires Q7.

## Phase 5 — Cases, participants and assignments

**Goal:** the core domain object and its authorization boundary.

- Migration for `cases`, `case_number_sequences`, `case_participants` (with the composite
  `(case_id, id)` unique index), `case_assignments` (with both partial unique indexes),
  `case_status_history` + its append-only trigger.
- `domain/case_number.py`, `domain/case_workflow.py` (transition graph), `domain/activity.py`
  (the `last_activity_at` allowlist).
- `CaseService` (create with number allocation, update with optimistic concurrency, archive/unarchive),
  `CaseWorkflowService.change_status`, participant and assignment services — all emitting audit events
  and updating `last_activity_at` in the same transaction.
- Actor-scoped `CaseRepository` (this is where employee visibility is implemented).
- Endpoints per [`api.md`](api.md) §5; UI: case list, create form, case detail with participants,
  assignments, status change dialog and status history.
- Tests: concurrent number allocation produces no duplicates and no gaps; employee cannot reach an
  unassigned case (`404`); employee cannot archive (`403`); one primary assignee enforced by the
  database; status history and audit written for every transition; `last_activity_at` updated for
  writes and untouched by reads.

**Exit criteria:** the invariant list in [`domain-model.md`](domain-model.md) §9 items 1–5, 10–12 is
covered by passing tests. Requires answers to Q3, Q6, and the case-creation part of Q4.

## Phase 6 — Documents

**Goal:** requirements, versioned submissions and safe file handling.

- Migration for `document_requirements` (composite FK to participants) and `document_submissions`
  (version uniqueness, review-consistency check, immutability trigger).
- `StorageService` protocol, `AzureBlobStorageService`, `InMemoryStorageService`; Azurite wired in
  Compose; one Azurite-backed adapter test.
- Upload pipeline: streaming size enforcement, extension + magic-byte agreement, SHA-256, UUID-derived
  keys, blob-then-row ordering with cleanup on failure.
- Authorized download streaming with hardened headers, sanitised Hebrew filenames, and audit.
- Review endpoint with approve/reject, review metadata, and requirement status handling per Q5.
- UI: requirement list per case, create requirement, upload with progress, submission version history,
  review dialog, download.
- Tests: oversize (`413`), disallowed type (`415`), spoofed content type rejected, rejected→new
  submission chain preserved, prior blob untouched, review metadata mandatory, download authorization
  and audit, requirement cannot point at another case's participant.

**Exit criteria:** invariant list items 6–8 covered; no Azure SDK import outside `storage/` (enforced
by the import contract). Requires answers to Q5, Q9.

## Phase 7 — Dashboard and activity history

**Goal:** the operational view the firm will actually open every morning.

- Aggregate queries for the five KPI cards, computed inside the actor's scope, with supporting indexes
  and an `EXPLAIN` review of each query.
- Stuck-case detection from `last_activity_at` and the configured threshold.
- Case table with all specified columns, filters (search, status, type, assignee, deadline) and sorts
  (urgency/deadline, last activity, created), plus the action-required panel.
- Case activity timeline UI rendering Hebrew text from `action` + `metadata`; admin audit log screen
  with filters.
- Tests: KPI numbers verified against seeded fixtures; employee KPIs reflect only assigned cases;
  filter/sort combinations; timeline ordering.

**Exit criteria:** every dashboard number traceable to a real query; no synthetic or hardcoded values
anywhere in the UI.

## Phase 8 — Legacy data import from Excel

**Goal:** bring the firm's existing cases, people and case history into the system so Release 1 is the
real system of record from day one rather than a parallel one.

Sequenced here deliberately: it needs every entity (people, cases, participants, assignments, document
requirements) to exist, and it needs the Phase 7 dashboard so the imported data can be reviewed in the
real UI instead of by reading SQL.

- Import specification written first from a real Excel export: column-to-field mapping, status mapping,
  participant-role inference, and the list of values that cannot be mapped and need a human decision.
- Idempotent, re-runnable importer (`scripts/import_legacy.py`) with three modes: `validate` (report
  only, no writes), `dry-run` (full transaction, rolled back), and `commit`. A row that fails
  validation never partially imports.
- Person de-duplication against `id_number` first, then name + organisation, with ambiguous matches
  reported for human resolution rather than merged automatically.
- Legacy case numbers: preserved as supplied (they are already on paper). The
  `case_number_sequences` row for each affected year is seeded above the highest imported number, so no
  newly created case can ever collide with a legacy one. Requires Q8.
- Every imported row is audited with a distinct `metadata.source = "legacy_import"` and the import run
  id, so imported facts are always distinguishable from facts the system observed. Imported cases get
  `last_activity_at` from their real last activity date, not from the import timestamp — otherwise the
  entire back catalogue would look freshly active and the stuck-case KPI would be meaningless on day one.
- Tests: mapping unit tests over fixture spreadsheets, idempotency (running twice changes nothing),
  de-duplication behaviour, number-collision impossibility after seeding, and validation-failure isolation.

**Exit criteria:** a full `validate` run on the real export reports zero unresolved errors; a `commit`
run is reviewed in the UI by the owner; re-running produces no changes. Requires Q8 and a real Excel
export to work from.

## Phase 9 — Release hardening

**Goal:** make Release 1 shippable.

- Full Playwright critical flow: admin logs in → creates two people → creates a case → assigns an
  employee → adds participants → creates a document requirement → uploads a document → reviews it →
  changes case status → sees every action in the activity history. Plus an employee-scope E2E: an
  employee sees only assigned cases and cannot archive.
- Accessibility pass (keyboard navigation, labels, focus management, contrast, RTL-correct focus
  order) on all Release 1 screens.
- Security review against [`security.md`](security.md): headers, CSP, cookie flags, upload limits,
  error leakage, dependency audit.
- Performance sanity: indexes verified against the real query plans on a seeded dataset.
- `scripts/seed_dev_data.py` (development-only, guarded by `APP_ENV`), blob/row reconciliation script,
  operational runbook, final documentation sweep, release checklist and known-limitations list.

**Exit criteria:** the full critical flow passes in CI against the Compose stack; all release-blocking
authorization tests from the specification pass; documentation matches the code.

## Phase 10 — Azure deployment blueprint (post-Release 1)

Explicitly outside Release 1 scope, listed so the sequencing is clear: infrastructure as code under
`infra/`, container build and push, Container Apps configuration, Azure Database for PostgreSQL with a
separate migration role, private blob containers, Key Vault wiring, Application Insights, and a
migration-then-deploy pipeline with rollback. No production deployment happens during Release 1.

## After Release 1

Order reflects dependency, not priority; priority is the owner's call.

| Release | Theme | Notes |
| --- | --- | --- |
| R2 | Entra ID + MFA, transactional email (real password reset, deadline reminders), notifications | Unblocks self-service account recovery and removes the temporary-password workaround |
| R2 | Payments and invoicing entities behind the existing payment-waiting statuses | First new bounded context; the statuses already exist |
| R3 | Client and lawyer portals | Requires a trust-boundary re-review: external users, per-document sharing, and consent |
| R3 | Outlook / Microsoft 365 integration, document intake from email | Uses the storage abstraction and an outbox pattern for integration events |
| R4 | Document intelligence, financial data extraction, RAG and AI agents | Consumes the immutable submission store; agents call the same `CaseWorkflowService`, so automation inherits validation and audit |
| R4+ | Actuarial calculation tooling, advanced BI | Reporting reads from the same schema, or a read replica |

## Scope guard for Release 1

Not built, not stubbed, not partially wired: AI/LLM/OCR/RAG, client or lawyer accounts, payment
gateways, invoice integrations, Outlook sync, email/SMS/WhatsApp sending, automated professional
recommendations, actuarial calculations, advanced BI, and production cloud deployment. Where the
architecture anticipates them, it does so through a documented seam (identity provider, storage
adapter, workflow service, audit log) and nothing more.
