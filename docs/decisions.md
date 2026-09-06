# Architecture decision records

> **Status:** All records are `Accepted`. ADR-0001 to ADR-0029 were taken during Release 1 planning;
> ADR-0030 onwards were taken during implementation and say which phase produced them. A decision that
> turns out wrong is superseded by a new record rather than edited away.
> Last reviewed: 2026-09-06

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

**Context.** `internal_case_number` is `YYYY-NNNN`, resets yearly, and must be concurrency-safe.
`MAX(n)+1` is explicitly forbidden and race-prone. This scheme is **introduced by this application** —
the firm has no internal numbering system today, so there is no legacy series to preserve or seed from,
and the number will be the firm's own reference on opinions, correspondence and invoices.

**Decision.** A `case_number_sequences (year, last_value)` table incremented with a single
`INSERT … ON CONFLICT (year) DO UPDATE SET last_value = last_value + 1 RETURNING last_value` inside the
case-creation transaction, with a `UNIQUE` constraint on `cases.internal_case_number` as the backstop.

**Consequences.** Correct under concurrency (row lock serialises allocation) and **gapless**, because a
rolled-back transaction returns the number — unlike a PostgreSQL sequence, which would burn it and leave
unexplained holes in a professional numbering series. One statement covers both the first and the nth
case of a year, with no runtime DDL. Cases imported from Excel draw numbers from this same allocator, so
there is no separate import numbering path. Cost: concurrent case creations for the same year serialise
briefly, which is irrelevant at this volume.

---

## ADR-0009 — One transition service, with workflow policy resolved per `case_type`

**Context.** Status drives the firm's workflow and future automation must not reimplement the rules, so
transition logic scattered across routers is the debt to avoid. But only `RESOURCE_BALANCING` has a
defined process today. Enforcing its graph on business valuations, damages work or municipal guidance
would invent constraints the business has not agreed to, and staff would route around them by picking
whatever status the validator happened to accept. Conversely, dropping validation entirely for those
types would leave the resource-balancing process unprotected.

**Decision.** `CaseWorkflowService.change_status` remains the **only** code permitted to assign
`Case.status`, and it always performs authorization, writes `case_status_history`, emits the audit
event and updates `last_activity_at` in one transaction. What varies is *validation*, resolved from the
case's type through a `WorkflowPolicy` protocol in `domain/case_workflow.py`:

- `GraphWorkflowPolicy` — registered for `RESOURCE_BALANCING`, holding the documented transition graph.
  An out-of-graph transition is rejected for everyone except `ADMIN`, and an admin override requires a
  non-empty `reason`, which is persisted on the history row and in the audit event as an override.
- `OpenWorkflowPolicy` — the default for every other case type in Release 1. Any status may follow any
  status, because the business has no defined sequence for those engagements yet. No-op transitions
  (same status to same status) are rejected regardless of policy.

A registry maps `case_type` to policy, with `OpenWorkflowPolicy` as the fallback. Both policies are pure
and unit-tested without a database.

**Consequences.** The one process the firm has actually defined is protected, and the others are recorded
faithfully instead of being forced through a fictional sequence. Automation, scheduled jobs and future AI
agents inherit authorization, validation, history and audit by calling the same method. Defining a real
workflow for another case type later is genuinely additive: write a graph, register it against the type,
and that type's transitions start being validated with no change to the service, the API or the UI.

Costs: two behaviours to hold in mind and to test; a status change on a non-resource-balancing case is
audited but not *validated*, so a wrong status there is a data-quality issue rather than a rejected
request; and the API cannot advertise a single transition rule, so the web app asks the server what is
permitted rather than hardcoding the graph. Whether the documented resource-balancing graph matches the
real process is still Q3 in [`open-questions.md`](open-questions.md) — the enforcement model is settled,
its content needs the owner's review.

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

## ADR-0027 — One person-access predicate governing detail reads and edits

**Context.** Employees must search the people directory to add case participants, but the directory
contains every party the firm has ever handled, including those in cases the employee is not assigned
to. Full visibility turns an operational tool into a browsable dossier; no visibility makes employees
dependent on an admin for routine work. The first version of this record covered only *reading*, which
left an inconsistency: an employee could be denied sight of a person's ID number yet still be permitted
to overwrite it. Read and write scope must match. Confirmed with the owner during planning.

**Decision.** A single predicate, `PersonAccessService.has_full_access(actor, person_id)`, is true for
any `ADMIN`, and for an `EMPLOYEE` only when the person has an **active participation in a case
currently assigned to that employee**. It governs three things at once:

- **Representation** — `PersonDetail` (ID number, address, phone, workplace, notes) when true;
  `PersonSummary` (name, organisation, masked ID) when false. Directory search returns summaries to any
  authenticated user.
- **Reads** — `GET /people/{id}` degrades to a summary rather than failing, since search already
  disclosed existence.
- **Writes** — `PATCH /people/{id}` requires the predicate to hold, and returns
  `403 PERSON_ACCESS_DENIED` when it does not.

Creating a person is open to both roles, and the creation response returns `PersonDetail` because the
caller authored the values. That grant does not persist past the request. Archiving remains
`ADMIN`-only. Enforcement is in the service layer, so it applies no matter which router, script or
future automation calls it.

**Consequences.** Employees can do their work without acquiring a firm-wide personal-data export, and
because one function decides representation, read and write, those three cannot drift apart as
endpoints multiply — the usual failure being a carefully scoped read sitting next to an update that
checks only the role. Access is also self-repairing: it appears when a person is attached to the
employee's case and disappears when the participation or the assignment is removed.

Costs, accepted: two schemas plus one access check per person operation; a UI that must render a
summary which cannot be expanded, explained by a Hebrew empty state; and one genuine wrinkle — an
employee who creates a person and immediately spots a typo must attach that person to their case before
correcting it. A lingering "creator" grant would have avoided the wrinkle at the price of an invisible
standing exception to the rule, which is how authorization models rot.

---

## ADR-0028 — Case creation is restricted to `ADMIN` in Release 1

**Context.** Specification §6 left this to policy. Creating a case is not an ordinary edit: it allocates
an internal case number from a gapless per-year series, establishes the assignment set that defines who
can see the case at all, and creates the record that every deadline, document and audit event hangs off.
Confirmed with the owner during planning.

**Decision.** Only `ADMIN` may create a case. Employees receive `403` from `POST /api/v1/cases`, and the
rule is a role gate in `auth/policies.py` enforced in the service, not a hidden button. Employees retain
full operational rights on cases assigned to them: editing fields, changing status, managing
participants, creating document requirements, uploading and reviewing documents.

**Consequences.** Number allocation and initial visibility stay under one pair of hands, and an employee
cannot create a case that no one is assigned to — the shape of orphaned record that quietly disappears
from every scoped list. Cost: the owner is in the loop for every new engagement, which is realistic at
this firm's size but would need revisiting as the team grows. Relaxing it later is a one-line change to
the policy plus its tests, because nothing else infers "can create" from a role.

---

## ADR-0029 — Participants and assignments are soft-removed

**Context.** Specification §18 requires archive semantics for important business data, but §7 and §9
defined `CaseParticipant` and `CaseAssignment` without any archival field while §17 defined a
`PARTICIPANT_REMOVED` audit action — so a literal reading hard-deleted a row whose existence the audit
log asserts. "Who represented party B in 2026?" and "who worked this case?" are questions this firm will
be asked years later, sometimes under professional scrutiny. Confirmed with the owner during planning.

**Decision.** Both tables carry `removed_at` and `removed_by`. Removal is an update, never a `DELETE`;
the application exposes no hard-delete path for either. Active-row constraints are partial indexes
scoped by `removed_at IS NULL`, so a person or employee can be removed and later re-added without
tripping uniqueness. Queries return active rows by default and full history on request
(`include_removed=true`).

**Consequences.** Historical participation and assignment remain queryable, and the audit log's
references always resolve to a row that still exists. Re-adding after removal works naturally. Costs:
every query must filter on `removed_at`, centralised in repository methods so it cannot be forgotten one
endpoint at a time; uniqueness has to be expressed as partial indexes rather than plain unique
constraints; and the UI needs an explicit "show removed" affordance so history is discoverable without
cluttering the default view.

---

## ADR-0030 — `activity_log.case_id` is an unconstrained UUID until cases exist (Phase 1)

**Context.** The audit table has to exist from Phase 1, because Phase 2's authentication events need
somewhere to land. `cases` does not exist until Phase 5. `activity_log.case_id` is meant to be a
foreign key to it, and there is no way to declare a constraint against a table that has not been
created.

**Decision.** Ship `case_id` as a plain nullable `UUID`, indexed exactly as it will be later
(`(case_id, occurred_at DESC)`). Phase 5's migration adds the constraint with a single
`ALTER TABLE … ADD CONSTRAINT … FOREIGN KEY … ON DELETE RESTRICT`.

**Consequences.** Additive and guaranteed to succeed: every row written before Phase 5 has
`case_id IS NULL`, because nothing that happens before cases exist has a case to point at. The window
in which a bad `case_id` could be written is Phases 1–4, during which no code sets the column at all.
Rejected alternatives: deferring the audit table to Phase 5, which leaves Phase 2 with nowhere to
record logins; and creating a stub `cases` table early, which is a fake entity occupying a real name
that Phase 5 would then have to migrate around.

---

## ADR-0031 — No `CHECK` constraint on `activity_log.action` and `entity_type` (Phase 1)

**Context.** ADR-0023 makes every enum-like column a `TEXT` column with a `CHECK` constraint. The
audit action catalogue is enum-like, but unlike case status or participant role it grows in *every*
remaining phase — each new feature adds verbs — and it is written on a path where failure is
particularly bad.

**Decision.** `action` and `entity_type` carry `btrim(…) <> ''` checks and nothing more. Validity is
enforced by the `AuditAction` / `AuditEntityType` `StrEnum`s and the recorder's typed signature, with
a unit test asserting the catalogue matches [`domain-model.md`](domain-model.md) §7.

**Consequences.** An audit row is never rejected because the application learned a new verb before the
database did — refusing to record that something happened, and rolling back the change it described,
is a worse outcome than recording it under an unfamiliar name. Typos are caught at import time in
Python rather than at runtime in PostgreSQL, which is earlier. Cost: a direct `INSERT` by a database
superuser could write an unknown action; that is a threat the constraint would not have stopped either,
since the same session could drop it. This is a deliberate, scoped exception to ADR-0023 and not a
precedent for business columns, where the value set is stable and the failure mode is a rejected
request rather than lost history.

---

## ADR-0032 — Request IDs are server-generated and client values are ignored (Phase 1)

**Context.** Every request needs a correlation id in logs, in the error envelope and on audit rows.
The common convention is to honour an inbound `X-Request-ID` so a trace survives across services.

**Decision.** The outermost middleware always generates a fresh UUID4, binds it to a `ContextVar` and
to structlog's context, and returns it as `X-Request-ID`. An inbound `X-Request-ID` is discarded.

**Consequences.** The id in a log line, in a `500` response and on an `activity_log` row is always one
this system minted, so correlation cannot be forged, collided, or used to inject content into a log
field. There is no upstream service to trace from in Release 1, so nothing is lost. If distributed
tracing arrives, the right answer is W3C `traceparent` with validation, which is a separate, deliberate
feature rather than trusting an arbitrary header today.

---

## ADR-0033 — Development migrates at container start-up; production migrates in the pipeline (Phase 1)

**Context.** A developer switching branches should not have to remember a migration command, and a
one-container development stack has no deployment pipeline to run one from. Production is the opposite
case: several replicas start at once.

**Decision.** The Compose `api` service runs `alembic upgrade head` before `uvicorn`. Production will
not: the deployment runs the upgrade once as its own step, before the new revision starts, under a
database role that holds `CREATE`/`DROP` while the runtime role does not.

**Consequences.** Development is one command and always consistent with the branch. Production avoids
replicas racing through the same DDL, and a failed migration fails the deployment before traffic moves
rather than taking containers down one at a time. The cost is a real constraint on how migrations are
written: during a rollout the old revision is still serving, so a migration has to be compatible with
it — additive first, destructive changes in a later release. That constraint exists in any zero-downtime
deployment and is better stated now than discovered in Phase 10.

## ADR-0034 — Authentication providers return an outcome; they do not raise (Phase 2)

**Context.** A failed login is not a read-only event: it increments `user_identities.failed_attempt_count`
and, at the threshold, sets `locked_until`. Those writes are the brute-force control. The natural
Python shape — raise `InvalidCredentialsError` from the provider — puts the exception inside the
service's `transaction()` block, which rolls it back on the way out. The counter would never persist
and an attacker would get unlimited guesses against a lockout that silently never engaged.

**Decision.** `AuthenticationProvider.authenticate()` returns an `AuthenticationResult` carrying an
outcome enum (`SUCCESS`, `UNKNOWN_IDENTITY`, `BAD_SECRET`, `LOCKED`, `INACTIVE`) plus a
`lockout_applied` flag. The service commits the counters and the audit row, and *then* raises the
single uniform `401` from outside the transaction. Nothing about the outcome reaches the client.

**Consequences.** Failure bookkeeping is durable, which is the entire point of having it. The audit
trail keeps the precise internal reason while the response stays uniform — one type carries both,
rather than the public error being asked to describe something it must not. The cost is that a caller
of a provider has to inspect a result instead of relying on an exception, so a future
`EntraIdAuthenticationProvider` must follow the same convention; the protocol's return type makes that
unmissable, and the service is the only caller.

## ADR-0035 — Per-IP login throttling counts audit rows; no Redis in Release 1 (Phase 2)

**Context.** Per-identity lockout stops an attacker grinding one account, but not one address probing
many accounts. A throttle needs shared, durable state. A process-local dictionary is not it: two API
replicas would each keep their own count and a restart would forget everything.

**Decision.** Count `USER_LOGIN_FAILED` rows in `activity_log` for the request IP inside a
configurable window (`LOGIN_IP_MAX_FAILED_ATTEMPTS`, `LOGIN_IP_WINDOW_SECONDS`) and return
`429 TOO_MANY_REQUESTS` above the limit. The rows are already being written for audit reasons, and
PostgreSQL is already a shared dependency.

**Consequences.** The control is durable, shared across replicas and needs no new table, no new
service and no new operational surface — a real consideration for a system with one small deployment
target. Accepted costs, all documented in [`security.md`](security.md) §2: one indexed count query per
login attempt, which is negligible at this scale but is not a free rate limiter; the window is
approximate rather than a precise token bucket; and the IP is taken from the connection, so it only
becomes trustworthy once a reverse proxy is in front of the API and configured to be believed (Phase
10). Users behind one office NAT share a bucket, which is why the limit is set well above human
retyping. If load ever makes the query the wrong shape, Redis or a proxy-level limiter replaces this
module without touching the login flow.

## ADR-0036 — A lockout is metadata on the failure event, not its own audit action (Phase 2)

**Context.** "When was this account locked, and by what?" must be answerable from the audit trail. The
obvious move is a `USER_LOCKED_OUT` action.

**Decision.** No new action. The attempt that trips the lock records
`USER_LOGIN_FAILED` with `lockout_applied: true` in its metadata.

**Consequences.** The locking attempt and the lock are the same event, at the same instant, against the
same entity; two rows would describe one thing and invite the two to disagree. The question stays a
single indexed-JSONB predicate rather than a reconstruction from counting consecutive failures. The
cost is that the fact lives in metadata rather than in the action vocabulary, so a future audit UI
filtering by action alone will not surface it — acceptable, because an investigator looking at lockouts
is already looking at login failures.

## ADR-0037 — Sessions are per browser; a new login does not displace existing sessions (Phase 2)

**Context.** [`open-questions.md`](open-questions.md) Q10 proposed "single active session per browser",
which can be read as one session per *user*. Logging in would then end whatever session already
existed.

**Decision.** Each login issues an independent session. Signing in on a laptop leaves a desktop session
working. Revocation stays targeted: logout ends the current session only, while a password change,
an admin reset and deactivation each revoke *all* of the user's sessions.

**Consequences.** No support calls from staff who use two machines and keep getting logged out of the
first. The controls that actually matter are unaffected, because idle expiry, the absolute cap and
revocation apply to every session independently, and the three events that mean "this account may be
compromised" already clear the lot. A user who wants every other session ended changes their password.
The cost is that a stolen laptop's session survives until it expires or somebody acts — which is true
of any per-device scheme, and is what deactivation is for.
