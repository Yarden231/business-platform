# Security model

> **Status:** Planning. Describes the controls Release 1 will implement and the ones deliberately
> deferred. Updated at the end of every phase to reflect what is actually enforced in code.
> Last reviewed: 2026-09-01

## 1. What we are protecting

The system holds material that is sensitive under Israeli privacy law and under professional
obligations: national ID numbers, salary and pension data, bank statements, tax assessments, family
and divorce information, and expert opinions that carry legal weight. A leak is not a technical
embarrassment, it is a legal event for the firm and a personal harm to the parties.

Working assumptions for Release 1: all users are trusted internal staff; there is no public traffic
and no external tenant; the application is single-organisation. Every control below is designed on
the assumption that "internal" still means least privilege, because the realistic threats are a
compromised staff credential, a curious employee, a malicious uploaded file, and accidental
over-sharing — not an anonymous internet attacker.

## 2. Authentication

### Release 1: email + password

- Passwords are hashed with **Argon2id** (`argon2-cffi`), parameters set in configuration and tuned on
  the target hardware (starting point: 64 MiB memory cost, time cost 3, parallelism 4). Hashes are
  self-describing, so parameters can be raised later and hashes upgraded transparently on next login.
- Plaintext passwords exist only in the request body of `POST /api/v1/auth/login` and the
  password-change endpoint. They are never logged, never stored, never included in audit metadata,
  and never returned.
- Password policy: minimum 12 characters, rejected against a small denylist of obvious values, no
  composition gymnastics (length beats character-class rules). Enforced in `domain`, so it is unit
  tested independently of HTTP.
- Login responses are uniform for "unknown email" and "wrong password" (`401`,
  `AUTH_INVALID_CREDENTIALS`) so the endpoint is not a user-enumeration oracle. Timing is levelled by
  always performing a hash verification against a dummy hash when the identity does not exist.
- **Brute-force protection**: per-identity counters (`user_identities.failed_attempt_count`,
  `locked_until`) plus per-IP throttling. After a configurable number of consecutive failures the
  identity is locked for a cooling period; locked attempts return the same `401` to the client and
  emit `USER_LOGIN_FAILED` audit events. Counters live in the database rather than in process memory
  so the control still works with more than one API instance (no Redis dependency in Release 1).
- Every authentication outcome — success, failure, lockout, logout — is an audit event with IP and
  user agent.

Account provisioning and recovery work without an email service (decided; ADR-0026): an admin creates
the account, the generated temporary password is shown to the admin exactly once and is never
retrievable afterwards, and `must_change_password` blocks every other endpoint until the user rotates
it. An admin can re-issue a temporary password for a locked-out user. There is deliberately **no**
self-service reset until Release 2 provides transactional email — the known cost is that the admin is a
single point of failure for lockouts, mitigated by keeping more than one `ADMIN` account, and that the
temporary password travels out of band (phone/WhatsApp).

### Future: Microsoft Entra ID

Handled by adding an `EntraIdAuthenticationProvider` behind the same protocol and a
`MICROSOFT_ENTRA` row in `user_identities`. Session issuance, CSRF, authorization and audit are
provider-independent and do not change. MFA arrives with Entra ID; the session model already supports
the pieces step-up authentication needs (server-side session rows that can record how a session was
authenticated).

## 3. Sessions

Release 1 uses **opaque server-side sessions**, not JWTs (ADR-0004):

- On login the API generates a 256-bit random token, stores only its SHA-256 hash in `sessions`, and
  sets it in a cookie: `HttpOnly`, `Secure` (always in production; relaxed only for plain-HTTP local
  development), `SameSite=Lax`, `Path=/`, no `Domain` attribute, no expiry attribute (session cookie).
- No token, user object or role is ever written to `localStorage` or `sessionStorage`, and the session
  cookie is unreadable from JavaScript.
- Lifetime: sliding idle timeout plus a hard absolute cap (proposed 8 hours idle / 12 hours absolute —
  Q10). `last_seen_at` is refreshed at most once per minute to avoid a write on every request.
- **Revocation is immediate and real**, which is the main reason for rejecting stateless tokens:
  logout, password change and user deactivation mark sessions `revoked_at`, and the next request
  fails. A stolen token cannot outlive an incident response.
- Session fixation is prevented by issuing a fresh session (and CSRF token) on every successful
  authentication and on password change.

### CSRF

Because authentication rides on a cookie, cross-site request forgery is a real risk and `SameSite=Lax`
alone is treated as one layer, not the answer:

1. The browser only ever talks to the web origin; the API is reached through a same-origin
   `/api/v1/*` proxy (ADR-0005). There is no legitimate cross-site credentialed request, so
   `SameSite=None` is never needed.
2. Double-submit token: login also sets a non-`HttpOnly` `csrf_token` cookie whose hash is stored on
   the session row. Every `POST`/`PATCH`/`PUT`/`DELETE` must echo it in an `X-CSRF-Token` header; the
   API compares the header against the hash bound to *that* session. Because the token is
   session-bound rather than a bare cookie/header equality check, an attacker who can only set
   cookies still cannot forge a valid pair.
3. Failures return `403 CSRF_TOKEN_INVALID` and are audited.

## 4. Authorization

Server-side, always, with three complementary mechanisms (details in
[`architecture.md`](architecture.md) §6). Release 1 role matrix:

| Capability | `ADMIN` | `EMPLOYEE` |
| --- | --- | --- |
| Log in, change own password | yes | yes |
| Create / edit / deactivate users | yes | no |
| Read the staff directory (id, name, role) | yes | yes (needed to display assignees) |
| Create / edit people | yes | yes, for operational work |
| Search people directory | yes, full detail | yes, masked summary only (ADR-0027) |
| Archive a person | yes | no |
| Create a case | yes | no in Release 1 — **(open: Q4)** |
| View a case | any case | assigned cases only |
| Edit case operational fields | any case | assigned cases only |
| Change case status | any case | assigned cases only |
| Manage participants | any case | assigned cases only |
| Manage assignments | yes | no |
| Archive / unarchive a case | yes | **no** |
| Create document requirements | yes | assigned cases — **(open: Q9)** |
| Upload submissions | yes | assigned cases |
| Review (approve/reject) submissions | yes | assigned cases |
| Download a document | any case | assigned cases only |
| View a case's activity timeline | any case | assigned cases only |
| Query the global audit log | yes | no |

Two rules make this enforceable rather than aspirational:

- **Deny by default in queries.** List and aggregate endpoints call actor-scoped repository methods;
  an `EMPLOYEE` query is scoped by an `EXISTS` predicate over active assignments. Dashboard KPIs are
  computed inside that same scope, so an employee's "stuck cases" count only reflects their own cases.
- **404 for out-of-scope, 403 for forbidden action** (ADR-0021). If an employee requests a case they
  are not assigned to, the API answers `404` — the response does not reveal whether the case exists.
  `403` is reserved for "you can see this resource but may not perform this action" (for example, an
  employee attempting to archive an assigned case). This distinction is asserted by tests.

The web app hides controls the current user cannot use, purely for usability. Every one of those
controls has a backend test proving the endpoint refuses the request when called directly.

## 5. Input validation and error handling

- Every request body, query parameter and path parameter is a typed Pydantic v2 model; unvalidated
  values never reach a service. Unknown fields are rejected rather than silently ignored.
- All database access goes through SQLAlchemy with bound parameters. No string-interpolated SQL, and
  no user-controlled `ORDER BY`/column names — sort keys are validated against an enum and mapped to
  columns in code.
- Errors return a single envelope (`{"error": {"code", "message", "details", "request_id"}}`) with
  stable machine-readable codes. Internal exception text, stack traces, SQL, driver messages and
  library versions are never returned; a `500` carries only a generic message and the `request_id`
  that appears in the server log.
- Hebrew user-facing wording lives in the web app and is selected by `code`, so error copy is
  reviewable by the business owner without touching the API (ADR-0014).

## 6. File upload and download security

Defence in depth, since attacker-controlled files are the most dangerous input in the system:

| Control | Implementation |
| --- | --- |
| Size limit | Streaming enforcement against `MAX_UPLOAD_SIZE_BYTES` (proposed 25 MiB — Q9); `413` on exceed; never buffer a whole file in memory |
| Type allowlist | Extension **and** magic-byte sniffing must both agree; allowlist starts at PDF, JPEG/PNG/TIFF, DOCX/XLSX (legacy DOC/XLS and all archives/executables excluded pending Q9) |
| Declared content type | Client-supplied `Content-Type` is recorded but never trusted; the sniffed type is authoritative |
| Path safety | Storage keys are built only from server-generated UUIDs; the original filename is metadata, never a path component |
| Filename handling | Sanitised (control characters, path separators, RTL-override characters stripped) before use in `Content-Disposition`, with an RFC 5987 `filename*` for Hebrew names |
| No public exposure | Blob containers are private; no SAS or blob URL is ever returned to a browser in Release 1; downloads stream through an authorized API endpoint |
| Download hardening | `Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, explicit server-chosen `Content-Type` |
| Integrity | SHA-256 computed during upload and stored; enables tamper detection and future de-duplication |
| Accountability | Every download emits a `DOCUMENT_DOWNLOADED` audit event with actor, document and IP |
| Immutability | Files are never overwritten or deleted; a replacement is a new versioned submission |

Malware scanning is **not** implemented in Release 1 and this is stated as a known limitation, not
hidden. The design keeps it a contained addition: an Azure Defender / scanning hook on the blob
container plus an additive `scan_status` column consulted before download.

## 7. Audit integrity

- Audit rows are written in the same transaction as the change they describe, so the log cannot
  disagree with the data.
- `activity_log` and `case_status_history` are append-only, enforced by a database trigger that raises
  on `UPDATE`/`DELETE`. In production the runtime role holds only `INSERT`/`SELECT` on those tables
  while Alembic runs under a separate migration role, so even a compromised application credential
  cannot rewrite history.
- `changes` payloads carry an **allowlist** of business fields only. Never recorded: password hashes,
  session or CSRF tokens, file contents. Recorded as "changed" without values: `people.id_number` and
  any future high-sensitivity identifier — the audit trail proves *that* an identifier was edited
  without duplicating the identifier across thousands of rows.
- Application logs are operational telemetry and are explicitly not the business audit trail.

## 8. Transport, headers and CORS

- HTTPS everywhere in production, terminated at the platform ingress; HSTS enabled there.
- Response headers set by middleware: `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `X-Frame-Options: DENY` (the app is never framed), and a
  Content-Security-Policy for the web app tightened during Phase 9.
- CORS: with the same-origin proxy the application needs no cross-origin credentialed requests. A
  strict, explicitly listed development origin (`http://localhost:3000`) is allowed for direct API
  access during development; wildcard origins with credentials are impossible by configuration, and
  production defaults to no cross-origin allowance.
- Interactive API documentation (`/docs`) is enabled outside production only.

## 9. Secrets and configuration

- No secret is ever committed. `.env.example` contains documented placeholders only; `.env` is
  git-ignored; Azurite's well-known development credentials are the sole exception and exist only in
  local Compose configuration.
- Production secrets live in Azure Key Vault and are injected as environment variables, so no
  application code depends on a secret store (ADR-0020).
- The application refuses to start in production with an unset or default `SESSION_SECRET`, a
  non-TLS database URL, or debug/docs enabled.
- Database credentials are per-environment; the runtime role has no `CREATE`/`DROP` rights in
  production, and migrations run as a separate role in a separate step.

## 10. Privacy and compliance notes

These require business and legal input rather than engineering decisions, and are recorded so they are
not forgotten (Q11):

- Israeli Privacy Protection Law obligations for a database of this nature: retention periods,
  data-subject access and correction requests, and whether the database must be registered.
- ID numbers are already masked for employees in directory search (ADR-0027). Still to confirm: whether
  they should also be masked inside case screens, and whether revealing a full ID number should itself
  raise an audit event.
- Retention of audit rows and of documents after a case closes, and whether archived cases must
  eventually be exported and purged.
- Data residency: the Azure region choice must satisfy client expectations (recommendation: an
  Israel or EU region, decided with the owner).

## 11. Deliberately deferred

Not in Release 1, by explicit scope decision, and none of them is blocked by the design: MFA and
Entra ID federation; malware scanning; field-level encryption beyond what the database and storage
provide at rest; security monitoring/alerting beyond structured logs and Application Insights;
penetration testing; client and lawyer access (which is the point at which the authorization model
must be re-reviewed, because it changes the trust boundary from "all users are staff" to "some users
are outsiders").
