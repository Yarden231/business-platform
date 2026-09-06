# Implementation roadmap

> **Status:** Phases 0, 1 and 2 complete. Phases 3–10 are planned. This document is the agreed
> sequencing for Release 1; each phase updates it with actual status on completion.
> Last reviewed: 2026-09-06

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

## Phase 0 — Foundation and toolchain — **complete**

**Goal:** a running, empty, fully linted monorepo that any developer can start in one command.

- Monorepo layout (`apps/api`, `apps/web`, `docs`, `infra`, `scripts`), npm workspaces for the web
  side, `uv` + `pyproject.toml` + `uv.lock` for the API, pinned language and image versions.
- `docker-compose.yml` with `db`, `azurite`, `api`, `web`; named volumes; healthchecks on all four; the
  `/api/v1/*` same-origin proxy configured as a Next.js rewrite.
- `.env.example` documenting every variable; `.gitignore`; git repository initialised.
- Quality gates wired and passing: `ruff` (format + lint), `mypy` (strict), `import-linter`,
  `pytest`, `eslint`, `prettier`, `tsc --noEmit`, `vitest`, and the production Next.js build.
- `scripts/` entry points: `install`, `dev`, `check`, `test`, `migrate`, used identically by CI.
- GitHub repository and GitHub Actions workflow invoking `scripts/check` itself rather than restating
  the commands (decided during planning).

**Exit criteria:** `docker compose up` serves a Hebrew RTL "hello" page and a `/healthz` API response;
`scripts/check` passes; no application logic exists yet. **Met.**

What landed, precisely, so later phases do not have to guess:

- `GET /healthz` returns `{"status": "ok"}` and touches nothing. It is mounted twice from one handler:
  unversioned at `/healthz` for infrastructure probes (kept out of the OpenAPI document) and at
  `/api/v1/healthz` for the browser, which reaches it through the web origin. `/readyz` is Phase 1.
- The web application is a single Hebrew RTL page showing the organisation name, the product name and
  live API connectivity. Its Hebrew strings already live in `apps/web/src/messages/he.ts`; the `t()`
  accessor, the error-code mapper and the date/number helpers are Phase 3.
- shadcn/ui is initialised (`components.json`, `cn()`, CSS-variable theme) with one primitive, `Badge`,
  because the page uses it. The rest of the primitives arrive with the screens that need them.
- **`import-linter` deviation.** The tool was configured and ran in `scripts/check` and CI, but the
  layered contracts from [`architecture.md`](architecture.md) §4 could not be written yet — `api`,
  `services`, `repositories`, `models` and `domain` did not exist, and creating empty packages so a
  contract has something to check would be the fake structure this project avoids. Phase 0 enforced
  the one boundary that was real: `app` may never import `tests`. **Resolved in Phase 1**, which added
  the layered contracts as it created the layers.
- No database tables, no Alembic, no settings object, no authentication, no domain code. `scripts/migrate`
  existed and reported that there was nothing to migrate rather than inventing a migration.

## Phase 1 — Backend platform — **complete**

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
or deleted (test proves the trigger fires); error envelope and logging verified by tests. **Met.**

What landed, precisely:

- Revision `0001` creates `pg_trgm`, `users`, `user_identities`, `sessions` and `activity_log`, plus
  the `append_only_guard()` function and the two triggers that make `activity_log` reject `UPDATE`,
  `DELETE` and `TRUNCATE`. `upgrade`, `downgrade` and re-`upgrade` are all covered on a throwaway
  database, and a drift test fails the build if the models and the head revision disagree.
- The layer packages that exist are `api`, `audit`, `core`, `db`, `domain`, `models` and `schemas`,
  held apart by five `import-linter` contracts (architecture.md §4). `services`, `repositories`,
  `auth` and `storage` are named in the contracts but not created, so the phase that needs one starts
  with the boundary already enforced.
- 118 tests: unit tests with no database (settings and production guards, error envelope, request id,
  logging and redaction, security headers, CORS, docs policy, audit catalogue) and integration tests
  against real PostgreSQL (schema shape, migrations, readiness including the database-down path, audit
  immutability, transaction atomicity).
- `scripts/migrate` runs `alembic upgrade head`; `scripts/check` and `scripts/test` load `.env` and
  refuse to start without a reachable database; CI runs a PostgreSQL service and calls both scripts.
- **Factories deviation.** The phase plan listed test factories. None were written: with four tables
  and no business entities, the two rows the tests need are three lines of constructor each, and a
  factory layer built before there is anything to vary would be guessed API rather than extracted
  API. Phase 4 introduces them with `people`, the first entity with enough optional fields to warrant
  one.
- **No authentication.** `users`, `user_identities` and `sessions` were persistence only: nothing read
  or wrote them, and there was no hashing, no cookie, no login endpoint and no bootstrap admin. Phase
  2 supplied all of it.

## Phase 2 — Identity and authorization — **COMPLETE**

**Goal:** real authentication and the authorization primitives, fully tested.

- Argon2id hashing; `AuthenticationProvider` protocol + `PasswordAuthenticationProvider`.
- Server-side sessions, cookie issuance, CSRF double-submit bound to the session, idle/absolute
  expiry, revocation on logout and password change.
- Login throttling and identity lockout; uniform failure responses; authentication audit events.
- `auth/policies.py`, `get_current_user`, `require_role`; user management endpoints; staff directory
  endpoint; own-password change.
- Temporary-password issuance shown once at user creation, `must_change_password` gating every other
  endpoint until rotation, and admin re-issue for lockouts (ADR-0026).
- Admin bootstrap: `scripts/create-admin` (interactive/env-driven, never a hardcoded credential).

**Exit criteria — met.** 362 tests were added (483 in the API suite, from 121), covering
unauthenticated rejection, wrong password, lockout, CSRF rejection, session revocation on logout,
employee blocked from user management, and no user enumeration through response differences — plus
the six end-to-end flows in `tests/integration/test_auth_flows.py`.

**Delivered as designed, with these notes:**

- **No migration.** The Phase 1 schema already carried the lockout counters, the CSRF hash and
  everything else this phase needed, so `0001` is still the head. A test asserts the models and the
  migration have not drifted.
- Per-IP throttling counts `USER_LOGIN_FAILED` rows in `activity_log` rather than introducing a table
  or Redis; its proxy-related limitation is documented in [`security.md`](security.md) §2.
- Q10 (session lifetimes) is now implemented from configuration at the proposed 8h idle / 12h
  absolute, so it is no longer an open question.
- Two fixes to Phase 1 code were needed and made: `UUIDPrimaryKeyMixin` now assigns the primary key at
  construction rather than at flush, which is what lets a service build a user, its identity and its
  audit row in one graph; and the shared test client can be built over `https`, without which
  production cookie behaviour could not be exercised at all.
- **No login UI**, by design: the browser screens are Phase 3, and this phase changed nothing in
  `apps/web`.

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
- `PersonAccessService.has_full_access` plus the `PersonSummary` / `PersonDetail` split, used to decide
  representation, detail reads **and** edit rights from one predicate (ADR-0027).
- Authorization tests, all release-blocking:
  - employee searching the directory receives `PersonSummary` with a masked ID, never `PersonDetail`;
  - employee reading a person outside their cases receives `PersonSummary`, not `403`/`404`;
  - employee `PATCH` on a person outside their cases → `403 PERSON_ACCESS_DENIED`, and the row is
    unchanged afterwards;
  - employee `PATCH` succeeds once that person participates in a case assigned to them;
  - access disappears again when the participation or the assignment is removed;
  - employee creating a person receives `PersonDetail` in the response but cannot `PATCH` it until it is
    attached to one of their cases;
  - admin reads and edits any person;
  - employee cannot archive a person (`403`).
- Other tests: Israeli ID validation, duplicate ID (`409`), archived people excluded from pickers but
  still resolvable from historical cases.

**Exit criteria:** the same person can be reused across cases in Phase 5 without duplication; every
endpoint has an authorization test; no code path can serialise `PersonDetail` without passing the
predicate; invariant 14 in [`domain-model.md`](domain-model.md) §9 is covered. Requires Q7.

## Phase 5 — Cases, participants and assignments

**Goal:** the core domain object and its authorization boundary.

- Migration for `cases`, `case_number_sequences`, `case_participants` (with the composite
  `(case_id, id)` unique index), `case_assignments` (with both partial unique indexes),
  `case_status_history` + its append-only trigger.
- `domain/case_number.py`, `domain/activity.py` (the `last_activity_at` allowlist), and
  `domain/case_workflow.py` — the `WorkflowPolicy` protocol, the `RESOURCE_BALANCING` graph, the default
  open policy, and the registry keyed by `case_type` (ADR-0009).
- `CaseService` (`ADMIN`-only creation with number allocation, update with optimistic concurrency,
  archive/unarchive), `CaseWorkflowService.change_status`, participant and assignment services with soft
  removal — all emitting audit events and updating `last_activity_at` in the same transaction.
- Actor-scoped `CaseRepository` (this is where employee visibility is implemented).
- Endpoints per [`api.md`](api.md) §5, including `allowed_next_statuses` on case detail; UI: case list,
  create form (admin only), case detail with participants, assignments, status change dialog driven by
  `allowed_next_statuses`, and status history.
- Authorization and workflow tests, all release-blocking:
  - concurrent number allocation produces no duplicates and no gaps;
  - employee cannot reach an unassigned case (`404`), cannot archive an assigned one (`403`), and cannot
    create a case (`403`, ADR-0028);
  - employee cannot manage assignments (`403`); admin can;
  - one active primary assignee per case, enforced by the database;
  - `RESOURCE_BALANCING`: an out-of-graph transition is rejected for an employee (`409`) and for an admin
    without a reason (`422`), accepted for an admin with a reason, and recorded as an override in both
    status history and audit;
  - a non-`RESOURCE_BALANCING` case accepts a transition the graph would forbid, and still writes status
    history and audit;
  - no-op transitions rejected under both policies;
  - participant and assignment removal is soft: the row survives with `removed_at`/`removed_by`, is
    excluded from active lists, returned by `include_removed=true`, and can be re-added afterwards
    (ADR-0029);
  - status history and audit written for every transition; `last_activity_at` updated for writes and
    untouched by reads.

**Exit criteria:** the invariant list in [`domain-model.md`](domain-model.md) §9 items 1–5, 10–13 and
15–16 is covered by passing tests. Requires an answer to Q3 only — whether the documented graph matches
the real resource-balancing process — which affects the graph's content, not the design.

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
- **Case numbers.** There is no legacy internal numbering to preserve — `internal_case_number` is
  introduced by this application. Every imported case is allocated a fresh number by the ordinary
  allocator, and `case_number_sequences` is never seeded from spreadsheet data. `court_case_number` is
  imported wherever the export contains one. If the real export turns out to hold a meaningful
  spreadsheet identifier (a row key the firm actually refers to), it is retained in a dedicated
  traceability column added by this phase's migration — only if the file shows one exists, not
  speculatively.
- Every imported row is audited with a distinct `metadata.source = "legacy_import"` and the import run
  id, so imported facts are always distinguishable from facts the system observed. Imported cases get
  `last_activity_at` from their real last activity date, not from the import timestamp — otherwise the
  entire back catalogue would look freshly active and the stuck-case KPI would be meaningless on day one.
- Tests: mapping unit tests over fixture spreadsheets, idempotency (running twice changes nothing),
  de-duplication behaviour, allocation of unique internal numbers across an import batch, and
  validation-failure isolation.

**Scope and mapping are pending a real Excel export** (Q8). Everything above describes the shape of the
phase; the column mapping, status mapping, participant-role inference, the year an imported case draws
its number from, and whether documents in shared folders are in scope cannot be specified from
assumptions and must not be guessed.

**Exit criteria:** a full `validate` run on the real export reports zero unresolved errors; a `commit`
run is reviewed in the UI by the owner; re-running produces no changes.

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
