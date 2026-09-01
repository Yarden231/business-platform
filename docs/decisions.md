# Architecture decision records

> **Status:** These are the decisions taken during Release 1 planning. All are `Accepted` as the plan
> of record but none is yet reflected in code; a decision that turns out wrong during implementation is
> superseded by a new record rather than edited away.
> Last reviewed: 2026-09-01

Format: context → decision → consequences (including the cost we accept). Decisions the specification
already fixed (Next.js, FastAPI, PostgreSQL, Azure, Hebrew RTL, monorepo) are not re-litigated here;
only the choices left open are recorded.

---

## ADR-0001 — Monorepo with npm workspaces and `uv`

**Context.** One repository holds a TypeScript app and a Python service. We need reproducible installs,
one place to run every quality gate, and no heavyweight build orchestration for two applications.

**Decision.** npm workspaces for the JavaScript side (npm 11 is already available; no extra tool to
install) and `uv` with `pyproject.toml` + `uv.lock` for the API. Cross-cutting commands live in
`scripts/` and are called identically by developers and CI. No Nx/Turborepo/Bazel in Release 1.

**Consequences.** Trivial onboarding and fast CI. We give up cross-language task caching, which is
worthless at two applications. If a shared TypeScript package appears later, `packages/` slots into the
existing workspace configuration.

---

## ADR-0002 — Async SQLAlchemy 2.x with `asyncpg`

**Context.** FastAPI supports both sync and async data access. Release 1 is not I/O-bound, but the
roadmap is: Microsoft Graph, Azure Blob, AI providers and webhooks are all network-latency work, and
mixing sync ORM code into an async service layer later is a painful, wide-reaching migration.

**Decision.** Async end to end: `create_async_engine` + `asyncpg`, `AsyncSession`, async Alembic env,
`pytest-asyncio` and `httpx.ASGITransport` for tests.

**Consequences.** Slightly more ceremony (`await`, async fixtures, careful lazy-loading — relationships
are loaded explicitly with `selectinload`, never lazily). In exchange, no future rewrite and no
thread-pool workarounds when integrations arrive. Lazy-load accidents are caught in tests because the
async driver raises rather than silently blocking.

---

## ADR-0003 — Explicit layering with enforced dependency direction

**Context.** The specification asks for `api`, `services`, `repositories`, `models`, `domain`, and
warns against folders with no purpose. Layer conventions that are not mechanically enforced erode.

**Decision.** The layering in [`architecture.md`](architecture.md) §4, with the dependency rules
verified in CI by an `import-linter` contract from Phase 1 onward. `domain` is pure (no SQLAlchemy, no
FastAPI); services own transactions; repositories own queries; routers own HTTP only.

**Consequences.** A violation fails the build instead of being caught in review, or not at all. Small
cost: some entities get thin repositories. The payoff is concrete — business rules are unit-testable
without a database, and authorization scoping has exactly one home.

---

## ADR-0004 — Opaque server-side sessions, not JWTs

**Context.** Cookie-based auth is required. The usual alternatives are a stateless JWT (plus refresh
token rotation) or a server-side session row.

**Decision.** Opaque 256-bit random tokens in an `HttpOnly` cookie; only the SHA-256 hash is stored, in
a `sessions` table with idle and absolute expiry and a `revoked_at` column.

**Consequences.** Immediate, reliable revocation — logout, password change and deactivation take effect
on the next request, which matters for a system holding legal and financial data and for incident
response. No refresh-token rotation complexity, no key-rotation problem, no "valid until expiry" stolen
tokens. Cost: one indexed lookup per request, and sessions do not survive a database loss. Both are
acceptable; a cache can be introduced behind the session store if load ever justifies it.

---

## ADR-0005 — Same-origin browser access via a Next.js proxy, plus session-bound CSRF tokens

**Context.** Cookies plus a cross-origin API force `SameSite=None`, which weakens the strongest
built-in CSRF defence and complicates local development.

**Decision.** The browser only talks to the web origin; Next.js rewrites `/api/v1/*` to the API. In
production the same shape is produced by path-based routing at the ingress. Cookies are therefore
first-party with `SameSite=Lax`, and a double-submit CSRF token whose hash is stored on the session row
is required on every unsafe method.

**Consequences.** No `SameSite=None`, no CORS credentials, identical topology in development and
production. The CSRF token is session-bound, so an attacker who can set cookies still cannot forge a
valid pair. Cost: uploads and downloads pass through the web tier when the Next.js rewrite is used
(the ingress-routing option avoids that and is preferred in production).

---

## ADR-0006 — Pluggable identity through a `user_identities` table

**Context.** Release 1 is email + password; Entra ID is a stated near-term requirement. The naive
approach — `users.password_hash` — makes federated users a nullable-column special case and invites a
messy migration.

**Decision.** `users` holds no credential. `user_identities` holds one row per
`(user_id, provider, provider_subject)` with a nullable `secret_hash`, plus the per-identity lockout
counters. All authentication goes through an `AuthenticationProvider` protocol; session issuance is
provider-independent.

**Consequences.** Adding Entra ID is an insert, not a migration of `users`; a user can hold both a
password and a federated identity during a transition; lockout state is per credential, not per person.
Cost: one extra join at login, and slightly more code than a single column.

---

## ADR-0007 — Argon2id for password hashing

**Context.** Passwords must never be recoverable, and the algorithm must be tunable as hardware
improves.

**Decision.** Argon2id via `argon2-cffi`, parameters in configuration (starting point 64 MiB / t=3 /
p=4), with automatic rehash-on-login when the stored parameters are below the current policy.

**Consequences.** Memory-hard resistance to GPU cracking; parameters can be raised without a migration.
Cost: deliberate CPU and memory per login, which is the point, and a bound on how aggressively login can
be hammered (mitigated by throttling).

---

## ADR-0008 — Gapless per-year case numbers from a counter table

**Context.** `internal_case_number` is `YYYY-NNNN`, resets yearly, appears in court documents, and must
be concurrency-safe. `MAX(n)+1` is explicitly forbidden and race-prone.

**Decision.** A `case_number_sequences (year, last_value)` table incremented with a single
`INSERT … ON CONFLICT (year) DO UPDATE SET last_value = last_value + 1 RETURNING last_value` inside the
case-creation transaction, with a `UNIQUE` constraint on `cases.internal_case_number` as the backstop.

**Consequences.** Correct under concurrency (row lock serialises allocation) and **gapless**, because a
rolled-back transaction returns the number — unlike a PostgreSQL sequence, which would burn it and leave
holes in a court-visible numbering scheme. One statement covers both the first and the nth case of a
year, with no runtime DDL. Cost: concurrent case creations for the same year serialise briefly, which is
irrelevant at this volume.

---

## ADR-0009 — One central case-transition service with a declarative graph

**Context.** Status drives the firm's workflow, and future automation must not reimplement the rules.
Transition logic scattered across routers is exactly the debt to avoid.

**Decision.** `domain/case_workflow.py` holds the allowed-transition graph; `CaseWorkflowService.
change_status` is the only code permitted to assign `Case.status`. It validates, writes
`case_status_history`, emits the audit event and updates `last_activity_at` in one transaction.

**Consequences.** Automation, scheduled jobs and future AI agents inherit validation, history and audit
for free. Per-case-type workflows later become a lookup keyed by `case_type` in a single module. Cost:
one indirection for a trivial column update, accepted deliberately. How strictly the graph is enforced
in Release 1 is Q3 in [`open-questions.md`](open-questions.md).

---

## ADR-0010 — Transactional, trigger-protected audit log

**Context.** The audit trail is business evidence, not telemetry. It must never disagree with the data,
and must not be editable through normal operation.

**Decision.** Audit rows are written by services in the **same transaction** as the change. A
`BEFORE UPDATE OR DELETE` trigger on `activity_log` and `case_status_history` raises an exception, and in
production the runtime database role is granted only `INSERT`/`SELECT` on them while migrations run as a
separate role.

**Consequences.** A rollback discards data and audit together, so the log cannot drift. Immutability is
enforced by PostgreSQL rather than by convention. Cost: a slightly wider write transaction, and audit
writes cannot be moved off the request path (an outbox is the answer if that ever becomes necessary).

---

## ADR-0011 — Archive/soft-delete for all business entities

**Context.** Cases, people and documents carry legal weight; historical references must keep resolving.

**Decision.** No hard deletes through the application. `archived_at` on cases, people and document
requirements; `removed_at` on participants and assignments; `deactivated_at` on users; append-only
history tables; every foreign key `ON DELETE RESTRICT`. Expired session rows are the only prunable data.

**Consequences.** History always resolves — an audit row from 2027 still names a real actor and a real
person. Cost: every query and picker must filter on the archival column (centralised in repository
methods so it cannot be forgotten piecemeal), and privacy-driven erasure becomes a deliberate,
documented operation rather than a `DELETE` (see [`security.md`](security.md) §10).

---

## ADR-0012 — Storage abstraction with an Azure Blob adapter; transfers proxied through the API

**Context.** Files must never live in PostgreSQL, must be private, and business logic must not depend on
Azure SDKs. Uploading straight to blob storage with a SAS token is the scalable pattern but moves
validation and authorization to the edge of our control.

**Decision.** A `StorageService` protocol (`put_stream`, `open_stream`, `delete`, `exists`) with an
`AzureBlobStorageService` adapter (Azurite locally, Azure Blob in production, same code path) and an
in-memory fake for tests. In Release 1 uploads and downloads stream **through** the API, which validates
size, extension and magic bytes, computes the checksum, and authorizes every download. Blob write
happens before the database row, with best-effort cleanup if the commit fails.

**Consequences.** One authorization and validation point; no blob URL or SAS ever reaches a browser; no
Azure type outside `storage/` (enforced by the import contract), so a different provider is a new
adapter. Cost: API bandwidth and a practical file-size ceiling; direct SAS transfer is a contained later
change. The blob-first ordering can leave an unreferenced blob on failure — chosen over the opposite
failure mode (a row pointing at a missing file), and reconcilable by script.

---

## ADR-0013 — Authorization by actor-scoped queries, not post-filtering

**Context.** Employees may only see assigned cases. Per-object checks are easy to get right on a detail
endpoint and easy to forget on a list, aggregate or export endpoint — the classic leak.

**Decision.** Repositories expose actor-scoped methods (`list_for_actor`, `summarise_for_actor`, …) that
inject an `EXISTS (SELECT 1 FROM case_assignments …)` predicate for `EMPLOYEE` actors. Every list and
KPI query goes through them. Detail endpoints additionally use an explicit object policy.

**Consequences.** A forgotten check yields *no rows*, not leaked rows — failure is safe. Dashboard
counts are automatically scoped. Cost: the actor must be threaded into repository calls, which is
verbose but visible; broader sharing rules later change one predicate rather than dozens of endpoints.

---

## ADR-0014 — Machine-readable error codes; Hebrew copy lives in the web app

**Context.** The UI is Hebrew-only, the codebase is English-only, and localization must be addable later.
Returning Hebrew strings from the API would put user-facing copy in Python and make future locales a
backend change.

**Decision.** Every error carries a stable `code` plus an English developer `message`. The web app maps
codes to Hebrew text in its message catalog.

**Consequences.** Copy changes need no API deployment and can be reviewed by the business owner; logs
and tests stay English; adding English or Arabic later is purely frontend work. Cost: every new error
code needs a catalog entry, with a test asserting no code is unmapped.

---

## ADR-0015 — `TIMESTAMPTZ` in UTC for instants, `DATE` for business dates

**Context.** Deadlines, appointment dates and the separation date are calendar facts in Israel; audit
timestamps are moments in time. Israel observes DST, so storing a deadline as an instant risks it
displaying as the previous day.

**Decision.** Instants are `TIMESTAMPTZ` stored in UTC and rendered in `Asia/Jerusalem`. Business dates
are `DATE`, transported as `YYYY-MM-DD`, and never passed through a timezone conversion. "This week"
means Sunday→Saturday in Jerusalem, computed by one tested helper. The case-number year comes from
Jerusalem local time.

**Consequences.** No off-by-one deadlines, no DST bugs, unambiguous audit ordering. Cost: two date
handling paths in the frontend, made explicit by distinct formatter helpers and types.

---

## ADR-0016 — Offset pagination for Release 1

**Context.** The dashboard needs total counts and page numbers. Keyset pagination is faster at scale but
cannot cheaply provide a total, and the data volume here is a single consultancy's caseload.

**Decision.** `page` / `page_size` (default 25, maximum 100) with `total`, on every list endpoint.

**Consequences.** Simple, predictable clients and honest counts. Cost: deep pages get slower and
concurrent inserts can shift rows between pages — both irrelevant at this scale. Keyset pagination is a
per-endpoint change if a high-volume list (likely the audit log) ever needs it.

---

## ADR-0017 — Generate TypeScript types from OpenAPI

**Context.** Hand-written frontend types drift from the API and hide breakage until runtime, and the
specification forbids avoidable `any`.

**Decision.** `openapi-typescript` generates `apps/web/src/lib/api/schema.d.ts` from the FastAPI OpenAPI
document; the file is committed and CI fails if regeneration produces a diff.

**Consequences.** A backend contract change breaks the frontend build immediately, which is where we want
to find it. No duplicated type definitions. Cost: a generation step in the workflow, and OpenAPI must
stay accurate — which is enforced by the same check.

---

## ADR-0018 — RTL-first Tailwind and a single Hebrew message catalog, with no i18n library

**Context.** Release 1 is Hebrew-only, but localization must not require rewriting the UI. Adding an i18n
framework now would be unused machinery; hardcoding Hebrew in JSX would make it impossible later.

**Decision.** `dir="rtl"` at the document root, Tailwind logical properties (`ms/me/ps/pe`,
`text-start/end`) instead of physical directions, and every string — including enum labels and error text
— in `messages/he.ts` behind a `t()` helper. No locale routing, no translation library, no English catalog.

**Consequences.** Adding `next-intl` later replaces the helper and adds catalogs without touching feature
code; an RTL/LTR flip is a Tailwind-level concern because no physical direction is hardcoded. Cost: a
lint rule and review discipline to keep Hebrew literals out of components.

---

## ADR-0019 — Optimistic concurrency on cases and document requirements

**Context.** Several staff work the same case. Last-write-wins silently destroys a colleague's edit and
makes the audit trail misleading about what changed.

**Decision.** A `version` column mapped as SQLAlchemy's `version_id_col` on `cases` and
`document_requirements`. Clients send the version they read; a mismatch returns
`409 CONCURRENT_MODIFICATION` and the UI offers to reload.

**Consequences.** No silent lost updates, and audit `changes` payloads describe real transitions. Cost:
clients must round-trip the version, and users occasionally see a conflict message — the correct
outcome. Entities with append-only semantics (submissions, history, audit) need no version.

---

## ADR-0020 — Configuration exclusively through environment variables

**Context.** Production runs on Azure with Key Vault, development runs in Compose. Reading Key Vault
directly in application code would couple business configuration to a cloud SDK and diverge the two
environments.

**Decision.** One `pydantic-settings` `Settings` object fed only by environment variables. Key Vault
values are injected as environment variables by the platform. Production start-up guards reject missing
or default secrets, non-TLS database URLs, and enabled debug/docs.

**Consequences.** Identical configuration code everywhere, no cloud SDK for config, easy testing by
overriding environment. Cost: no live secret rotation without a container restart, which is acceptable
and standard for this platform.

---

## ADR-0021 — `404` for out-of-scope resources, `403` for forbidden actions

**Context.** When an employee requests a case they are not assigned to, returning `403` confirms that the
case exists. `404` conceals it but is a slightly worse debugging and UX signal.

**Decision.** `404` when the resource is outside the actor's visibility scope (existence is not
confirmed); `403` when the actor can see the resource but may not perform the action — for example an
employee attempting to archive an assigned case, or reach a user-management endpoint. Both are asserted
by tests.

**Consequences.** No enumeration of case existence across visibility boundaries, and a consistent,
documented rule rather than per-endpoint improvisation. Cost: an employee who *should* have access sees
"not found" rather than "ask an admin"; the UI's Hebrew empty state explains how to request access.

---

## ADR-0022 — Integration tests on real PostgreSQL, migrated by Alembic

**Context.** The invariants that matter most here live in the database: partial unique indexes, check
constraints, composite foreign keys, triggers, concurrent number allocation. SQLite or mocks cannot
express any of them, and `create_all` in tests would leave migrations untested.

**Decision.** Integration tests run against a real PostgreSQL database created with
`alembic upgrade head`. Each test runs inside a transaction rolled back afterwards; the case-numbering
concurrency test deliberately uses independent sessions with real commits. Storage uses the in-memory
fake, with one Azurite-backed test covering the Azure adapter. CI also asserts that Alembic autogenerate
produces an empty diff against the models.

**Consequences.** Constraints and triggers are actually exercised, and a model change without a migration
fails the build. Cost: tests need a database (already in Compose) and are slower than pure unit tests;
domain logic is unit-tested separately to keep the fast layer fast.

---

## ADR-0023 — Enumerations as `TEXT` with `CHECK` constraints

**Context.** Case types, participant roles, document types, statuses and audit actions are all expected
to grow. PostgreSQL native enums make adding a value a type migration and removing one effectively
impossible; a lookup table adds joins and admin surface nobody asked for.

**Decision.** `TEXT` columns with `CHECK` constraints, mirrored by Python `StrEnum` and validated by
Pydantic at the boundary. Hebrew labels live in the web catalog.

**Consequences.** Adding a value is a one-line constraint migration and an enum addition; values are
readable in raw SQL and in exports; validation still happens at three layers. Cost: no database-level
type identity, so every enum column needs its constraint written explicitly — done once per column in
the migration.

---

## ADR-0024 — Hebrew search via `pg_trgm` and `ILIKE`

**Context.** Staff search by partial Hebrew names, organisation names, ID numbers and case names. Hebrew
has no letter case, and PostgreSQL full-text search has no Hebrew dictionary/stemmer worth relying on.

**Decision.** GIN trigram indexes (`pg_trgm`) on the searched columns with `ILIKE '%term%'` predicates,
behind repository search methods.

**Consequences.** Fast substring matching that works correctly for Hebrew and for partial ID numbers,
with no external search service. Cost: no relevance ranking, stemming or fuzzy matching; if that becomes
necessary, `similarity()` ranking or a dedicated search service replaces the repository method without
touching callers.

---

## ADR-0025 — Archival is orthogonal to case status

**Context.** The specification defines `ARCHIVED` both as a value in the status enum (§12) and as an
`archived_at` timestamp (§10, §18) — two sources of truth for one fact, which can disagree and which
would make every "active cases" query depend on which column its author trusted. Confirmed with the
owner during planning.

**Decision.** `ARCHIVED` is removed from the status enum. `archived_at` is the sole authority for
whether a case is in the working set; `status` retains only workflow meaning and is never modified by
archiving. `CLOSED` is the terminal workflow state. Archive and unarchive are `ADMIN`-only service
operations, audited as `CASE_ARCHIVED` / `CASE_UNARCHIVED`.

**Consequences.** No possible divergence between two columns, and — the real win — an archived case
still records how it *ended*: an archived case that reached `OPINION_PUBLISHED` is distinguishable from
one abandoned at `WAITING_FOR_DOCUMENTS`, which the specification's enum would have overwritten.
Unarchiving needs no status restoration from history. Cost: a deliberate, documented deviation from
§12, and every default query must filter `archived_at IS NULL` — centralised in repository methods so
it cannot be forgotten one endpoint at a time.

---

## ADR-0026 — Admin-issued one-time temporary passwords; no self-service reset in Release 1

**Context.** Release 1 requires password authentication and admin-created employees, but excludes all
email automation (§27), so there is no channel for delivering credentials or reset links. Confirmed
with the owner during planning.

**Decision.** Creating a user generates a cryptographically random temporary password, returned in the
creation response exactly once and never retrievable afterwards (only its Argon2id hash is stored).
`must_change_password` forces rotation at first login, before any other endpoint is usable. An admin
can re-issue a temporary password for a locked-out user. No "forgot password" flow exists until
transactional email arrives in Release 2.

**Consequences.** Onboarding and recovery work with zero external dependencies, and no password is
ever stored or transmitted in a recoverable form. Cost: recovery requires an admin, so the owner is a
single point of failure for lockouts — mitigated by allowing more than one `ADMIN` account. The
temporary password is delivered out of band by the admin (phone/WhatsApp), which is a documented
operational weakness that Release 2 removes.

---

## ADR-0027 — Two person representations: directory summary and full detail

**Context.** Employees must search the people directory to add case participants, but the directory
contains every party the firm has ever handled, including those in cases the employee is not assigned
to. Full visibility turns an operational tool into a browsable dossier; no visibility makes employees
dependent on an admin for routine work. Confirmed with the owner during planning.

**Decision.** Two response schemas. `PersonSummary` (name, organisation, masked ID number) is returned
by directory search to any authenticated user. `PersonDetail` (ID number, address, phone, workplace,
notes) is returned only to an `ADMIN`, or to an `EMPLOYEE` for a person participating in a case they
are assigned to. The distinction is enforced by the service selecting the schema, not by the client
choosing fields.

**Consequences.** Employees can do their job without gaining a firm-wide personal-data export, and the
sensitive-field boundary is one testable decision rather than a per-endpoint judgement. Cost: two
schemas and a visibility check per person read, plus a UI that must handle a summary that cannot be
expanded — the Hebrew empty state explains that full detail requires assignment to a shared case.
