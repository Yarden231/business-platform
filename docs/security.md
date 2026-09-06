# Security model

> **Status:** Describes the controls Release 1 will implement and the ones deliberately deferred.
> Updated at the end of every phase to reflect what is actually enforced in code.
>
> **Enforced in code today (after Phase 4):**
>
> - **§2 authentication in full** — Argon2id hashing with configured parameters and transparent
>   rehashing, the password policy, uniform login failure, the dummy-hash timing defence, per-identity
>   lockout, per-IP throttling, and admin-issued temporary passwords with forced rotation;
> - **§3 sessions and CSRF in full** — opaque server-side sessions, the cookie attributes below
>   asserted against real `Set-Cookie` headers, idle and absolute expiry, throttled `last_seen_at`
>   writes, immediate revocation on logout/password change/reset/deactivation, and the session-bound
>   double-submit CSRF check;
> - **§4 role authorization** — the `ADMIN`/`EMPLOYEE` rows of the matrix that concern login, password
>   change, user administration, the staff directory, and the people directory. Person representation
>   and `PATCH` rights come from `PersonAccessService.has_full_access` (ADR-0027). Until cases exist
>   that predicate is `ADMIN` only, so an employee always receives `PersonSummary` and cannot edit or
>   archive. The case-level rows are still design;
> - the same-origin topology of §3 — the browser reaches the API only through the web origin;
> - the error-handling rules of §5: one envelope, stable codes, and a `500` that carries nothing but a
>   generic message and a `request_id`, asserted by tests that look for the exception text, the
>   database URL, the exception class name and a traceback in the response body;
> - the audit immutability of §7 — `activity_log` refuses `UPDATE`, `DELETE` and `TRUNCATE` at the
>   database, proved by tests that go around the ORM — and the authentication events of §2 are now
>   actually written;
> - the response headers and CORS policy of §8, including interactive API documentation disabled when
>   `APP_ENV=production`;
> - the secrets and configuration rules of §9: `.env` git-ignored, `.env.example` placeholders only,
>   Azurite's emulator credentials labelled as such, and start-up guards that refuse a production
>   process with a default session secret, a non-TLS database URL, insecure session cookies, or
>   debug/docs/SQL-echo enabled.
>
> **Still design:** the case rows of §4 (authorization), and §6 (uploads).
>
> **Phase 3 added the browser screens:** login, forced password change, the application shell and
> logout. The session cookie remains `HttpOnly` and `SameSite=Lax`; the browser reads `csrf_token`
> and sends `X-CSRF-Token` on unsafe requests. Nothing authentication-related is written to
> `localStorage` or `sessionStorage`.
>
> **Phase 4 added the people directory screens** and the person-access predicate. Audit `changes` for
> `id_number` are `{before, after: "[redacted]"}`; create metadata records `identifier_present` and
> `id_type`, never the number.
> Last reviewed: 2026-09-06

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

- Passwords are hashed with **Argon2id** (`argon2-cffi`) in `app/auth/hashing.py`, parameters set in
  configuration and tuned on the target hardware (`ARGON2_MEMORY_COST` 64 MiB, `ARGON2_TIME_COST` 3,
  `ARGON2_PARALLELISM` 4). Hashes are self-describing, so parameters can be raised later: after a
  successful verification — the one moment the plaintext is in hand — `needs_rehash` upgrades the
  stored hash in place, with nothing asked of the user.
- Plaintext passwords exist only in the request body of `POST /api/v1/auth/login` and the
  password-change endpoint. They are never logged, never stored, never included in audit metadata,
  and never returned. A test sweeps every column of every table for a distinctive password after
  login, password change, provisioning and a rejected change.
- Password policy: minimum 12 characters, maximum 200, rejected against a small denylist of obvious
  values (folded for case and punctuation), whitespace-only rejected, and a new password may not equal
  the current one. No composition gymnastics — length beats character-class rules. It lives in
  `app/domain/passwords.py` as a pure function returning every violation at once, so it is unit tested
  without HTTP or a database, and violations surface as `PASSWORD_INVALID` details.
- Login responses are uniform for "unknown email", "wrong password", "malformed address", "locked
  identity" and "deactivated account" — all `401 AUTH_INVALID_CREDENTIALS` with the same message and
  no details — so the endpoint is not a user-enumeration oracle. A test asserts the responses are
  byte-identical apart from `request_id`. Note that `email` is validated as a bounded string rather
  than an `EmailStr`: a field-level `422` for a malformed address would itself answer "no account
  could exist here".
- Timing is levelled by always performing a hash verification. When no identity matches, the
  submitted password is verified against a dummy hash of a random value, computed **once per process**
  at hasher construction. This levels the dominant cost; it is not a claim of constant time.
- **Brute-force protection**, two independent controls:
  - *per-identity* (`user_identities.failed_attempt_count`, `locked_until`):
    `LOGIN_MAX_FAILED_ATTEMPTS` consecutive failures (default 5) lock the identity for
    `LOGIN_LOCKOUT_SECONDS` (default 15 minutes). Attempts during the cooling period are refused
    **without extending it**, so an attacker cannot keep a real user locked out on a schedule. The
    counters are flushed by the provider and committed by the service *before* the `401` is raised —
    a failed login that rolled its own counter back would be no counter at all, and there is a test
    that reads the committed value straight from the database.
  - *per-IP*: `LOGIN_IP_MAX_FAILED_ATTEMPTS` failures (default 20) from one address within
    `LOGIN_IP_WINDOW_SECONDS` (default 15 minutes) return `429 TOO_MANY_REQUESTS`. This catches
    spraying across many accounts, which no per-identity counter can see. The counter is the trailing
    window of `USER_LOGIN_FAILED` rows in `activity_log` — durable, shared between replicas, and
    already being written on exactly the event that needs counting, so Release 1 needs neither a new
    table nor Redis. **Known limitation:** the address is the peer as the ASGI server reports it.
    Because the browser reaches the API through the same-origin Next.js proxy, this degrades from
    per-client to per-proxy unless the deployment runs `uvicorn --proxy-headers
    --forwarded-allow-ips=<ingress>`. That is why the per-IP threshold is deliberately generous and
    the per-identity lockout is the primary control.
- Every authentication outcome is an audit event with request id, IP and user agent:
  `USER_LOGGED_IN`, `USER_LOGIN_FAILED` (carrying the internal outcome and a `lockout_applied` flag
  so "when was this account locked, and by what" is one row), `USER_LOGGED_OUT`,
  `USER_PASSWORD_CHANGED`. A failure against an address with **no account records no address** —
  otherwise the audit log would become the enumeration oracle the endpoint refuses to be. The cost is
  deliberate: such an attempt is auditable as an event and by source IP, but not by the address tried.
  Session-related events carry the session row's `session_id`, which is what makes a logout traceable
  to the login that preceded it; it is the primary key, **not** the token and not the token's hash, and
  it grants nothing to anybody who reads it. Neither the raw nor the hashed session token, and neither
  the raw nor the hashed CSRF token, is ever written to an audit row — a test asserts it over every
  row produced by a full login, rotation and logout cycle.

Account provisioning and recovery work without an email service (decided; ADR-0026): an admin creates
the account, the generated temporary password is shown to the admin exactly once and is never
retrievable afterwards, and `must_change_password` blocks every other endpoint until the user rotates
it. An admin can re-issue a temporary password for a locked-out user. There is deliberately **no**
self-service reset until Release 2 provides transactional email — the known cost is that the admin is a
single point of failure for lockouts, mitigated by keeping more than one `ADMIN` account, and that the
temporary password travels out of band (phone/WhatsApp).

The temporary password is 20 characters from `secrets.choice` over a 57-character alphabet (~116 bits)
with `0/O` and `1/l/I` removed and grouped in fives, because it is read aloud over the phone. Only its
Argon2id hash is stored, and a unit test asserts it satisfies the policy above — otherwise
provisioning could hand out a password the change endpoint refuses.

**Forced rotation.** While `must_change_password` is true, exactly three endpoints work: `GET
/auth/me`, `POST /auth/password` and `POST /auth/logout`. Everything else answers `403
PASSWORD_CHANGE_REQUIRED`. The gate is applied by depending on the *gated* actor, and those three
endpoints opt out explicitly — so a new authenticated endpoint is gated by default, which is the safe
direction for an omission to fall in. The public operational probes are unauthenticated and were never
in scope for the gate.

**Admin bootstrap.** The first `ADMIN` cannot be created through the API, so `scripts/create-admin`
(driving `app/cli/create_admin.py` and `app/services/admin_bootstrap.py`) creates it out of band from
interactive input or `BOOTSTRAP_ADMIN_*` environment variables. There is **no default account, no
seeded email and no seeded password**: supply nothing and nothing is created. It refuses to create a
second admin (further admins go through the audited API), refuses an address that already belongs to
an account, and re-running it for the existing bootstrap admin reports that and changes nothing —
which makes it safe in a provisioning script that runs twice, and stops a re-run being a silent
credential rotation. The password goes through the same policy and the same hasher as every other; the
bootstrap is not a back door with weaker rules. `created_by` is `NULL` because nobody created it, and
the audit row has a `NULL` actor for the same reason.

### Future: Microsoft Entra ID

Handled by adding an `EntraIdAuthenticationProvider` behind the same protocol and a
`MICROSOFT_ENTRA` row in `user_identities`. Session issuance, CSRF, authorization and audit are
provider-independent and do not change. MFA arrives with Entra ID; the session model already supports
the pieces step-up authentication needs (server-side session rows that can record how a session was
authenticated).

## 3. Sessions

Release 1 uses **opaque server-side sessions**, not JWTs (ADR-0004):

- On login the API generates a 256-bit random token (`secrets.token_urlsafe(32)`), stores only its
  SHA-256 hash in `sessions.token_hash`, and sets the raw value in a cookie named `session`:
  `HttpOnly`, `Secure` (always in production; relaxed only for plain-HTTP local development),
  `SameSite=Lax`, `Path=/`, no `Domain` attribute, no expiry attribute (session cookie). Every one of
  those attributes is asserted against the real `Set-Cookie` header, in development *and* against a
  production-configured application.
  SHA-256 with no salt or stretching is correct here and would be wrong for a password: the input is
  already 256 bits of uniform randomness, so there is no guessable plaintext to recover. The reason to
  hash at all is that a database read — a backup, a leaked dump, a compromised reporting credential —
  must not yield anything replayable as a cookie.
- **`SameSite=Lax`, not `Strict`** (ADR-0005). `Strict` withholds the cookie on any cross-site
  navigation, so following a link to the application from an email lands on a logged-out page despite
  a valid session. `Lax` still withholds it from cross-site `POST`, and CSRF protection here does not
  rest on the attribute anyway — it rests on the session-bound token below.
- No token, user object or role is ever written to `localStorage` or `sessionStorage`, and the session
  cookie is unreadable from JavaScript. Nothing authentication-related ever appears in a URL.
- Lifetime: sliding idle timeout plus a hard absolute cap, `SESSION_IDLE_TIMEOUT_SECONDS` (8 hours)
  and `SESSION_ABSOLUTE_TIMEOUT_SECONDS` (12 hours) — Q10, now implemented from configuration rather
  than proposed. A settings validator refuses an absolute cap below the idle window, which would make
  the idle timeout unreachable. `last_seen_at` is refreshed at most once per
  `SESSION_LAST_SEEN_REFRESH_SECONDS` (60) to avoid a write on every authenticated read; the cost is
  that the effective idle window is the configured one plus up to one refresh interval.
- The four reasons a session is unusable — revoked, past its absolute expiry, idle too long, or the
  user deactivated — are one pure function in `app/domain/sessions.py`, unit tested one second either
  side of each boundary instead of by waiting out an eight-hour timeout.
- **Revocation is immediate and real**, which is the main reason for rejecting stateless tokens:
  logout, password change, admin password reset and user deactivation set `revoked_at`, and the next
  request fails. Revocation is checked *before* expiry, because it is the control incident response
  depends on. A stolen token cannot outlive an incident response.
- Session fixation is prevented by issuing a fresh session (and CSRF token) on every successful
  authentication and on password change. A password change revokes every existing session and *then*
  issues the replacement — the reverse order would log the caller out of the request that just
  succeeded.

### CSRF

Because authentication rides on a cookie, cross-site request forgery is a real risk and `SameSite=Lax`
alone is treated as one layer, not the answer:

1. The browser only ever talks to the web origin; the API is reached through a same-origin
   `/api/v1/*` proxy (ADR-0005). There is no legitimate cross-site credentialed request, so
   `SameSite=None` is never needed.
2. Double-submit token: login also sets a non-`HttpOnly` `csrf_token` cookie whose SHA-256 hash is
   stored on the session row. Every `POST`/`PATCH`/`PUT`/`DELETE` must echo it in an `X-CSRF-Token`
   header; the API hashes the header value and compares it against `sessions.csrf_token_hash` for
   *that* session, with `secrets.compare_digest`. The cookie is **never read server-side**: comparing
   cookie against header would prove only "the sender could set both", which is exactly what an
   attacker able to write cookies can do. Because the token is session-bound, a token from another
   session — or another user — is refused, and there are tests for both, plus one proving each token
   still works with its own session so the refusals are not a blanket failure.
   The CSRF token is a separate random value from the session token, so the `HttpOnly` session token
   is never exposed to the script that has to read the CSRF cookie.
3. Safe methods (`GET`/`HEAD`/`OPTIONS`) are not checked at all. Authentication is resolved *before*
   CSRF, so an unauthenticated `POST` is `401` rather than `403`: "who are you" precedes "prove this
   was intentional". Login itself needs no token — there is no session to bind one to yet.
4. Failures return `403 CSRF_TOKEN_INVALID` and emit a `CSRF_VALIDATION_FAILED` audit event, because
   a rejected token is either an attack or a client bug and both are worth seeing afterwards. Neither
   the submitted token nor the expected hash is recorded — the event is that verification failed, not
   what was offered. A failed check does not revoke the session; it is not a reason to log somebody
   out.

## 4. Authorization

Server-side, always, with three complementary mechanisms (details in
[`architecture.md`](architecture.md) §6). Release 1 role matrix — the login, user-administration and
people-directory rows are **enforced in code today**; the case and document rows are still design:

| Capability | `ADMIN` | `EMPLOYEE` |
| --- | --- | --- |
| Log in, change own password | yes | yes |
| Create / edit / deactivate users, reset another user's password | yes | no |
| Read the staff directory (id, name, role) | yes | yes (needed to display assignees) |
| Create a person | yes | yes |
| Search the people directory | yes, full detail | yes, masked summary only (ADR-0027) |
| Read full person detail | any person | only a person participating in a case currently assigned to them (ADR-0027) |
| Edit a person | any person | only a person participating in a case currently assigned to them (ADR-0027) |
| Archive a person | yes | no |
| Create a case | yes | **no** (ADR-0028) |
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

The role gate is a pure function over an `AuthenticatedActor` (`app/auth/policies.py`), applied as a
router dependency **and** re-checked inside the service, so neither layer is the only thing standing
between an employee and user management. The actor carries five fields — id, email, name, role and
`must_change_password` — and no session id, token or hash: raw session ORM rows never travel into the
application.

Two rules exist purely to stop an administrator locking the firm out of its own instance, and both
answer `409`:

- an admin cannot deactivate **themselves** (`USER_SELF_DEACTIVATION`) — doing so mid-request is
  never what was meant;
- the **last active admin** cannot be deactivated or demoted (`USER_LAST_ADMIN`), because with no
  self-service password reset an instance with no admin has nobody who can create one. A deactivated
  admin does not count towards the survivors.

Three rules make the rest enforceable rather than aspirational:

- **Deny by default in queries.** List and aggregate endpoints call actor-scoped repository methods;
  an `EMPLOYEE` query is scoped by an `EXISTS` predicate over active assignments. Dashboard KPIs are
  computed inside that same scope, so an employee's "stuck cases" count only reflects their own cases.
- **404 for out-of-scope, 403 for forbidden action** (ADR-0021). If an employee requests a case they
  are not assigned to, the API answers `404` — the response does not reveal whether the case exists.
  `403` is reserved for "you can see this resource but may not perform this action" (for example, an
  employee attempting to archive an assigned case). This distinction is asserted by tests.
- **One predicate governs both reading and writing a person.** Read access to `PersonDetail` and the
  right to `PATCH` a person are decided by the *same* function,
  `PersonAccessService.has_full_access(actor, person_id)`, which is true for any `ADMIN` and for an
  `EMPLOYEE` only when the person has an active participation in a case currently assigned to that
  employee. Because both paths call one predicate, read and write scope cannot drift apart as the code
  grows — the classic version of this bug is a carefully scoped read endpoint next to an update
  endpoint that only checks the role.

An employee therefore cannot edit a person they can merely find in the masked directory: the directory
tells them the person exists so they can attach them to their case, and attaching them is what grants
edit rights. A person visible only as a `PersonSummary` returns `403 PERSON_ACCESS_DENIED` on `PATCH`
(the person's existence is already disclosed by search, so `404` would be dishonest rather than
protective — this is the "visible but not permitted" case in the rule above).

One consequence is deliberate and worth stating: an employee who creates a person and then spots a typo
must attach that person to their case before they can correct it. The creation response returns
`PersonDetail` because the employee authored those values, but the grant does not persist beyond the
request. The alternative — a lingering "creator" permission — would accumulate quiet, invisible
exceptions to the rule above, which is precisely what makes authorization models rot.

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
  that appears in the server log. The full exception, with traceback, goes to the log under that same
  `request_id`, which is how a support question is answered without the response ever carrying it.
- Validation failures report the field and a machine-readable issue (`{"field": "count", "issue":
  "int_parsing"}`) but never the rejected value. Pydantic's own `input` and `msg` are dropped on
  purpose: echoing what was rejected is how a password or an ID number ends up in a log aggregator,
  a browser console and a screenshot in a support ticket.
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
- Application logs are operational telemetry and are explicitly not the business audit trail. They
  pass through a redaction processor that blanks a fixed set of keys — `password`, `token`,
  `session_token`, `csrf_token`, `secret`, `session_secret`, `authorization`, `cookie`, `set-cookie`,
  `database_url`, `id_number` — regardless of the call site. That is a backstop for a mistake, not a
  reason to pass credentials to a logger. Request and response bodies are never logged, and neither is
  the query string, which from Phase 4 carries search terms over personal data.

## 8. Transport, headers and CORS

- HTTPS everywhere in production, terminated at the platform ingress; HSTS enabled there.
- Response headers set by API middleware, on every response including error responses:
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `X-Frame-Options: DENY` (the app is never framed).

  **Responsibility boundary.** These three are set by the API because they are properties of an API
  response and must hold even when a request never reaches the web tier — a direct call to port 8000,
  or a `500` rendered above the router. Three headers are deliberately *not* set here:
  Content-Security-Policy and Permissions-Policy, which govern what a document may load and are
  meaningless on a JSON response, belong to the Next.js layer and are tightened in Phase 9; and
  Strict-Transport-Security, which is a property of the origin's TLS termination, belongs to the
  ingress. Setting HSTS from the application would be inert in development (plain HTTP) and duplicated
  in production, where the ingress is the only component that knows the real scheme.
- CORS: with the same-origin proxy the application needs no cross-origin credentialed requests. The
  allowlist is explicit and environment-driven, defaulting to `http://localhost:3000` for direct API
  access during development. `*` is rejected by a settings validator rather than by convention, and a
  production process refuses to start with any origin configured at all, so credentialed wildcard CORS
  is not a mistake this codebase can make.
- Interactive API documentation (`/docs`, `/redoc`, `/openapi.json`) is enabled outside production
  only. An explicit `API_DOCS_ENABLED=true` under `APP_ENV=production` is refused at start-up rather
  than silently ignored, so the mistake surfaces in a deployment log instead of on the internet.

## 9. Secrets and configuration

- No secret is ever committed. `.env.example` contains documented placeholders only; `.env` is
  git-ignored; Azurite's well-known development credentials are the sole exception and exist only in
  local Compose configuration.
- Production secrets live in Azure Key Vault and are injected as environment variables, so no
  application code depends on a secret store (ADR-0020). `SESSION_SECRET` is held as a `SecretStr`, so
  it does not appear in a `repr()`, a validation error or a log line.
- The application refuses to start when `APP_ENV=production` and any of the following is true: the
  session secret is still the development placeholder, or shorter than 32 characters; the database URL
  is the development placeholder, or does not request TLS (`ssl=require` / `sslmode=require`); `DEBUG`
  is on; `API_DOCS_ENABLED` is on; `DB_ECHO` is on, which would write SQL — and therefore data — into
  the logs; or `CORS_ALLOWED_ORIGINS` is non-empty. All violations are reported in one message, so a
  misconfigured deployment is fixed in one pass rather than one restart at a time. These guards are
  unit-tested individually.
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
