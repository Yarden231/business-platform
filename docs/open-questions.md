# Specification review: contradictions, gaps and decisions needing a human

> **Status:** Open, with seven items decided. Produced during Release 1 architecture planning from a close
> reading of the specification. Section 2 items each carry a **recommended default** so implementation is
> never blocked for lack of an answer, but items marked **blocking** should be answered before the phase
> that needs them, because they affect data modelling that is expensive to reverse.
>
> **Decided:** Q1 archival orthogonal to status (ADR-0025) · Q2 admin-issued temporary passwords
> (ADR-0026) · Q3 enforcement *model* — workflow policy per `case_type` (ADR-0009) · Q4 person access,
> person edits and `ADMIN`-only case creation (ADR-0027, ADR-0028) · Q6 soft removal of participants and
> assignments (ADR-0029) · Q8 Excel import is Phase 8, with the legacy-numbering premise corrected ·
> Q12 GitHub + GitHub Actions.
>
> **Still open, in phase order:** Q7 (Phase 4) · Q3's graph *content* (Phase 5, does not block the design)
> · Q5 and Q9 (Phase 6) · Q8's mapping and scope, pending a real Excel export (Phase 8). Q10 and Q11 are
> needed before production, not before code.
>
> Phase 1 note: the provisional answers to Q9c (25 MiB) and Q10 (8 hours idle, 12 hours absolute) are
> now `Settings` defaults — `MAX_UPLOAD_SIZE_BYTES`, `SESSION_IDLE_TIMEOUT_SECONDS`,
> `SESSION_ABSOLUTE_TIMEOUT_SECONDS` — so answering either is an environment variable, not a code
> change.
>
> Phase 2 note: **Q10 is now enforced from that configuration**, so it is answered in the only sense
> that matters to the code — the numbers are a deployment decision the owner can still revise without
> a release. Uploads (Q9c) remain unenforced until Phase 6.
> Last reviewed: 2026-09-06

---

## 1. Contradictions and gaps found in the specification

These are places where the specification says two things that cannot both be implemented literally, or
where it requires a behaviour without defining it. Each has a proposed resolution; the ones that are
genuinely the owner's call are cross-referenced to Section 2.

### C1 — `ARCHIVED` is both a status and a timestamp

§12 lists `ARCHIVED` in the status enum. §10 and §18 require `archived_at`. That is two sources of truth
for one fact, and they can disagree: a case could carry `status = 'CLOSED'` with `archived_at` set, or
`status = 'ARCHIVED'` with `archived_at` null. Every "active cases" query would then depend on which
column the author happened to trust.

Additionally, `CLOSED` and `ARCHIVED` are both listed as statuses without a stated distinction. The
natural reading is "closed = work finished, archived = removed from the working set", but that is an
inference, not a specification. → **Q1.**

**Resolved (ADR-0025).** `ARCHIVED` is dropped from the status enum. `archived_at` alone determines
whether a case is in the working set, `status` keeps its workflow meaning and is never touched by
archiving, and `CLOSED` is the terminal workflow state. This deviates from §12 on purpose: it preserves
*how a case ended*, which the original enum would have overwritten.

### C2 — Soft-delete policy versus `PARTICIPANT_REMOVED`

§18 requires archive/soft-delete semantics for important business data, but §7 and §9 define
`CaseParticipant` and `CaseAssignment` with no archival field, while §17 defines a `PARTICIPANT_REMOVED`
audit action. Taken literally, removing a participant hard-deletes a row whose existence the audit log
asserts — and "who represented party B in 2026" becomes unanswerable. → **Q6.**

**Resolved (ADR-0029).** `removed_at` / `removed_by` on both tables, no application hard delete, and
partial unique indexes scoped to active rows so a person or employee can be re-added after removal.

### C3 — Password login is required, but email sending is out of scope

§5 requires email + password authentication and §6 gives `ADMIN` the ability to create employees. §27
excludes all email automation. There is therefore no defined way for a new employee to receive
credentials, and no possible self-service password reset in Release 1. This is an operational gap, not a
coding detail. → **Q2.**

**Resolved (ADR-0026).** Admin-issued one-time temporary password, displayed exactly once at creation and
never retrievable afterwards, with `must_change_password` forcing rotation at first login. Self-service
reset waits for transactional email in Release 2.

### C4 — Payment-related statuses with no payment domain

§12 requires `WAITING_FOR_ADVANCE_PAYMENT` and `WAITING_FOR_FINAL_PAYMENT`; §27 excludes payments and
invoicing entirely. These are compatible only if the statuses are understood as pure workflow signals.

**Resolution taken.** The statuses exist and are recorded; no payment, invoice, amount or due-date entity
appears anywhere in the schema, and nothing computes or displays money. This is stated explicitly in
[`domain-model.md`](domain-model.md) §5.3 so a later reader does not mistake the omission for an oversight.

### C5 — `DocumentRequirement.status` has no defined values or semantics

§15 specifies submission statuses precisely (`UPLOADED`, `UNDER_REVIEW`, `APPROVED`, `REJECTED`) but gives
the requirement a `status` field with no value set, and does not say whether it is derived from its
submissions or set by hand. The two designs behave very differently — a derived status can never
contradict the submissions, a manual one can, and each implies a different UI. → **Q5.**

Related gap: with multiple submissions per requirement, the specification does not say what happens to
`v1` (still `UPLOADED`, awaiting review) when `v2` arrives. Without a `SUPERSEDED` value, the
"documents pending review" KPI double-counts obsolete submissions.

### C6 — `DocumentRequirement.participant_id` is ambiguous

§15 lists `participant_id`, which could reference `people` or `case_participants`. Referencing `people`
would allow a requirement to be addressed to a person who is not a participant in that case — a
cross-case data-integrity hole.

**Resolution taken.** `case_participant_id`, with a composite foreign key `(case_id, case_participant_id)`
→ `case_participants (case_id, id)`, so the database itself refuses a participant from another case.

### C7 — Dashboard KPIs versus employee scoping

§19 requires KPI cards ("active cases", "stuck cases", "documents requiring review") and §6 restricts
employees to assigned cases, but the specification never says whether an employee's KPIs count the whole
firm or only their own cases. A firm-wide count is itself an information leak (it reveals caseload volume
and, via the action-required list, case identities).

**Resolution taken.** Every KPI and list is computed inside the caller's visibility scope. An employee's
"stuck cases" counts their assigned cases only.

Two further undefined details, both resolved rather than guessed at each use site: "this week" means
Sunday→Saturday in `Asia/Jerusalem` (the Israeli working week), and "documents requiring review" counts
submissions in `UPLOADED` or `UNDER_REVIEW` on non-archived requirements.

### C8 — "Meaningful activity" and "meaningful changes" are undefined

§14 requires `last_activity_at` to be updated by meaningful actions and lists examples including "case
edited meaningfully", while §17 requires audit entries for "all meaningful changes". Left undefined, this
becomes an inconsistent judgement call at every call site.

**Resolution taken.** A single allowlist in `domain/activity.py` maps each audit action to whether it
advances `last_activity_at`, documented in [`domain-model.md`](domain-model.md) §7. Notably,
`DOCUMENT_DOWNLOADED` is audited (accountability) but does not count as activity (it is consumption, not
progress), and every field edit on a case counts, including notes.

### C9 — "No mock implementations" versus emulators and test doubles

§23 forbids mock implementations and fake APIs; §2 requires Azurite (an emulator) and §24 requires
component tests, which need test doubles.

**Interpretation taken.** The prohibition targets *product* code — no fake endpoints, no stubbed business
logic, no hardcoded sample data in the application. Emulators for local infrastructure and test doubles
inside the test suite are explicitly in scope. The one in-repository test double that ships as product
code is `InMemoryStorageService`, which exists solely so tests need no blob service; it is never
selectable in production configuration.

### C10 — "Employee may add document requirements if permitted by service policy"

§6 both grants and withholds this capability, deferring to a "service policy" that the specification never
defines. → **Q9.**

### C11 — Employees need the people directory, which §6 does not grant

§6 gives person creation and editing to `ADMIN` and says employees may "manage case participants". Adding a
participant requires finding a person, which requires searching the global directory — exposing every
person in the firm's history, including parties to cases the employee is not assigned to. The
specification's authorization model does not address this. It is a privacy decision, not an engineering
one.

**Resolved (ADR-0027).** Employees may search the whole directory but receive a masked summary; full
detail — and the right to edit the person — requires being assigned to a case that person participates
in, decided by a single predicate so read and write scope cannot diverge. Case creation is `ADMIN`-only
(ADR-0028).

### C12 — Testing the numbering invariant conflicts with the standard test isolation pattern

§24 requires a test proving duplicate case numbers cannot occur. The usual transaction-per-test isolation
cannot express concurrency, since two sessions in one transaction do not contend.

**Resolution taken.** One deliberately non-isolated integration test uses independent sessions with real
commits and truncates afterwards, documented as an exception in [`architecture.md`](architecture.md) §11.

### C13 — Layer names `models`, `domain` and `services` overlap

§3 asks for all three while warning against purposeless folders; without explicit rules, business logic
scatters across them.

**Resolution taken.** Explicit rules and a machine-enforced `import-linter` contract
([`architecture.md`](architecture.md) §4, ADR-0003): `domain` is pure logic with no ORM or framework
imports, `models` is ORM mapping only, `services` orchestrates and owns transactions.

### C14 — API error language is unspecified

The UI is Hebrew-only (§4) and the codebase is English-only (§4), but §21 does not say which language API
error messages use.

**Resolution taken.** Stable English machine-readable codes plus English developer messages; all Hebrew
copy in the web message catalog (ADR-0014).

---

## 2. Decisions that need a human answer

Each has a recommended default that will be implemented if no other answer is given. **Blocking** means
the answer shapes a migration or a security control that is costly to change afterwards.

Five were answered by the owner on 2026-09-01 and are marked **Decided** below, with the resulting
records in [`decisions.md`](decisions.md). They are kept here rather than deleted so the reasoning
behind them stays visible.

### Q1 — Archive semantics — **Decided**

**Answer:** archival is orthogonal to status. `ARCHIVED` is dropped from the status enum entirely;
`archived_at` alone determines whether a case is in the working set, and `status` keeps its real
workflow meaning. Archive and unarchive are `ADMIN`-only and audited. Recorded as **ADR-0025**; the
schema in [`domain-model.md`](domain-model.md) §5 reflects it.

This is a deliberate deviation from specification §12, taken because it is strictly more informative:
an archived case still records whether it ended at `OPINION_PUBLISHED` or `CLOSED`, which the original
enum would have overwritten.

### Q2 — Account provisioning and password recovery without email — **Decided**

**Answer:** the admin creates the account and sees a generated temporary password exactly once;
`must_change_password` forces rotation at first login; the admin can re-issue for lockouts; no
self-service reset until Release 2 provides email. Recorded as **ADR-0026**.

Still useful to know (does not block anything): roughly how many employees will use Release 1, which
tells us how painful admin-mediated recovery will be in practice.

### Q3 — Status transition enforcement (**enforcement model Decided; graph content open, Phase 5**)

**Decided (enforcement model):** workflow validation is resolved per `case_type`, because only
`RESOURCE_BALANCING` has a defined business process today. That type is governed by the documented
graph, with an `ADMIN` out-of-graph override that requires a mandatory `reason` and is recorded as an
override in status history and audit. All other case types use an open policy in Release 1 — any status
may follow any status — while still passing through `CaseWorkflowService` for authorization, status
history and audit. Recorded as **ADR-0009**. Since Q1 removed `ARCHIVED` from the enum, `CLOSED` is the
terminal status, and reopening a closed resource-balancing case is exactly such an override.

**Still open (the graph's content), and this is a business question rather than a technical one:**

- Is the path in [`domain-model.md`](domain-model.md) §5.3 actually how a resource-balancing engagement
  runs, in that order?
- Which transitions do you consider illegal rather than merely unusual — for example, returning from
  `OPINION_PUBLISHED` to `WAITING_FOR_DOCUMENTS`, or skipping `WAITING_FOR_ADVANCE_PAYMENT` when a
  client has already paid?
- Are there steps missing from the list entirely (a court hearing, a client meeting, a draft sent for
  comment)?

Answering this changes the graph's contents, not the design, so Phase 5 can be built while it is
settled — but the sooner it lands, the less status data needs correcting afterwards.

### Q4 — People directory access and case creation — **Decided**

**Decided (directory and person edits):** employees may search all people but see only a masked summary
— name, organisation and a masked ID number. Full `PersonDetail`, **and the right to edit a person**, are
available to admins for anyone, and to an employee only for a person participating in a case currently
assigned to them. One predicate governs representation, reads and writes. Recorded as **ADR-0027**.

**Decided (case creation):** only `ADMIN` may create a case in Release 1. Employees work on cases
assigned to them but cannot create them, because creation allocates a case number and establishes the
assignment set that determines visibility. Recorded as **ADR-0028**.

### Q5 — Document requirement status, and superseded submissions (**blocking, Phase 6**)

- **Recommended:** requirement status is **derived** from its submissions —
  `PENDING` (no submission) → `SUBMITTED` (an unreviewed submission exists) → `APPROVED` (a submission
  approved) → `REJECTED` (latest submission rejected, awaiting a replacement) — with two manual admin
  overrides, `WAIVED` (no longer needed) and `CANCELLED` (created in error). Derivation means the status
  can never contradict the file history.
- Recommended also: add `SUPERSEDED` to the submission statuses so that uploading `v2` closes out an
  unreviewed `v1`, keeping the "pending review" KPI honest. This extends the specification's enum by one
  value and needs a nod.
- Alternative: fully manual requirement status (more flexible, can lie about the documents).

### Q6 — Participant and assignment removal — **Decided**

**Decided:** soft removal. `case_participants` and `case_assignments` both carry `removed_at` and
`removed_by`; the application permits no hard delete of either, and historical participation and
assignment stay queryable (`include_removed=true`). Active-row uniqueness is expressed as partial
indexes, so a person or employee can be removed and later re-added. Recorded as **ADR-0029**.

### Q7 — `id_number`: validation, uniqueness, and non-Israeli identifiers (**blocking, Phase 4**)

- **Recommended:** when provided, validate as an Israeli ID (9 digits + check digit) and enforce global
  uniqueness among non-null values; keep the field nullable so a person can be created before their ID is
  known.
- Needs confirmation: do you handle parties without an Israeli ID (foreign nationals, passport holders,
  corporate entities)? If yes, the clean answer is an `id_type` column (`ISRAELI_ID`, `PASSPORT`,
  `COMPANY_NUMBER`) added now rather than retrofitted, because validation and uniqueness rules differ per
  type. Retrofitting is possible but touches existing rows.

### Q8 — Legacy data import (**partly decided; specifics open, Phase 8**)

**Decided:** existing cases must be imported from Excel, and that import is its own phase — now
**Phase 8** in [`roadmap.md`](roadmap.md), sequenced after documents and the dashboard so the result can
be reviewed in the real UI.

**Corrected premise.** An earlier draft of this document assumed the firm already had internal case
numbers in use, and specified seeding `case_number_sequences` above them. That was wrong.
`internal_case_number` is introduced by this application; there is no legacy internal series to
preserve, so nothing is seeded from spreadsheet data. Imported cases are allocated new numbers by the
ordinary allocator, and `court_case_number` is imported wherever the export has one.

**Still needed, before Phase 8 can be specified (a real Excel export answers most of it):**

- A sample export of the current spreadsheet(s), including the header row and a few representative rows.
  Everything below is easier to answer from the file than from memory.
- Roughly how many cases, people and years are involved, and which years are in scope.
- Which year should an imported case draw its number from — the year the engagement actually opened (so
  a 2024 case becomes `2024-00NN`, which keeps the scheme meaningful) or the import year? The first is
  the recommendation, and it needs the export to contain a reliable opening date.
- Does the spreadsheet contain an identifier the firm actually refers to (a row key quoted in emails or
  filenames)? If so it is worth retaining in a traceability column; if not, nothing is retained.
- How are the parties and their lawyers recorded today (separate columns, one free-text cell, a separate
  contacts sheet)? This determines how much can be mapped automatically versus needs review.
- How should legacy statuses map onto the Release 1 status list, and what should happen to rows whose
  status has no clean equivalent?
- Are historical documents in shared folders also in scope? If yes, that is a second import path (files
  plus a folder-to-case mapping) and should be its own sub-phase, since file matching is far less
  reliable than row mapping.
- For closed legacy cases, is a minimal record (number, name, parties, dates, final status) sufficient,
  or is the full document history required?

### Q9 — Document policy: permissions, file types, size, and the type list (**Phase 6**)

- **9a — Recommended:** employees **may** create document requirements in cases they are assigned to
  (this is ordinary case work, and every action is audited). Confirm, since §6 leaves it to policy.
- **9b — Recommended:** allow PDF, JPEG, PNG, TIFF, DOCX and XLSX. Legacy `.doc`/`.xls`, all archives
  (`.zip`, `.rar`) and anything executable are rejected — macro-capable legacy formats and archives are the
  highest-risk uploads and there is no malware scanning in Release 1. Confirm whether the firm actually
  receives legacy Office files from lawyers, because that is the one likely friction point.
- **9c — Recommended:** 25 MiB per file. Confirm against reality — scanned pension clearinghouse reports
  and bank statement bundles can exceed this.
- **9d:** please review the starting `document_type` list in [`domain-model.md`](domain-model.md) §6.1 and
  the Hebrew labels; you know the real document vocabulary and the list is much easier to get right now
  than after data exists.

### Q10 — Session lifetime (**Implemented from configuration in Phase 2**)

- **Implemented:** 8 hours idle timeout and 12 hours absolute maximum, from
  `SESSION_IDLE_TIMEOUT_SECONDS` and `SESSION_ABSOLUTE_TIMEOUT_SECONDS`, with immediate revocation on
  logout, password change, admin reset and deactivation. That covers a working day without leaving a
  machine logged in overnight. Changing either number is an environment variable and a restart.
- One deliberate departure from the recommendation: sessions are **per browser, not one per user**.
  Logging in on a second machine does not end the first session, because silently logging somebody out
  of their desktop when they open their laptop is a support call, not a security control — and the
  controls that matter (revocation, idle expiry, the absolute cap) apply to each session
  independently. A user who wants every session ended changes their password, which revokes all of
  them.
- **Still worth confirming with the owner:** whether staff work from shared or personal machines, and
  whether a shorter idle timeout (say 30 minutes) is wanted given the sensitivity of the data. This is
  now a configuration conversation rather than a code one.

### Q11 — Privacy, retention and data residency (**needed before production, not before code**)

Legal and business input rather than engineering:

- Israeli Privacy Protection Law obligations for this database — registration, retention limits,
  data-subject access and correction handling.
- How long documents and audit rows are retained after a case closes, and whether archived cases must
  eventually be exported and purged (this interacts with the no-hard-delete policy, which is why it matters
  early even though nothing is deployed).
- Azure region: recommendation is an Israel or EU region. Confirm that no client contract demands
  otherwise.
- ID numbers are masked for employees in directory search (ADR-0027). Confirm whether they should also be
  masked inside case screens, and whether revealing one should raise its own audit event.

### Q12 — Repository hosting and CI (**Decided**), Azure ownership (**open, Phase 10**)

**Decided:** the repository lives on GitHub, with GitHub Actions running exactly the same gates as
`scripts/check`. Reflected in [`roadmap.md`](roadmap.md) Phase 0.

**Still open, and not blocking any Release 1 code:** who owns the Azure subscription and tenant that
will host this, and whether there is an existing Microsoft 365 tenant to federate with later. It
determines naming, region and identity choices in the Phase 10 blueprint.

---

## 3. Assumptions made without asking

Recorded so they can be corrected cheaply if any is wrong. These were judged low-risk and reversible.

1. **Single organisation, single tenant.** No multi-tenancy in the schema; no organisation/tenant column.
2. **All Release 1 users are trusted internal staff.** The authorization model must be re-reviewed when
   client and lawyer portals arrive, because that changes the trust boundary.
3. **Hebrew is the only UI language, `Asia/Jerusalem` the only display timezone, ILS the implied currency**
   (no currency is stored in Release 1).
4. **Desktop-first usage** by a small team (single-digit to low-double-digit users), with responsive layout
   as a convenience rather than a mobile-first requirement.
5. **`case_name` is entered by the user** (typically "פלוני נ' פלונית") rather than generated from
   participants; the UI may suggest a value, but the field is authoritative and editable.
6. **No email, SMS or notification of any kind is sent** by Release 1, including deadline reminders. Stuck
   and overdue cases surface only on the dashboard.
7. **No scheduled/background jobs.** Stuck-case detection is a query at read time, not a nightly job, so
   there is no scheduler in Release 1.
8. **Documents are uploaded by staff**, not by clients or lawyers. Every submission has an internal
   `uploaded_by`.
9. **`court_case_number` is not unique** — related or consolidated proceedings may share it.
10. **A person's `email` is not unique** — spouses and family members legitimately share an address.
