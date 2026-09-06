/**
 * Reading the CSRF token the API issued (docs/security.md §3, ADR-0005).
 *
 * The API sets two cookies on login. `session` is `HttpOnly` and this code can
 * never see it — which is the point. `csrf_token` is deliberately readable from
 * JavaScript, because echoing it back in `X-CSRF-Token` on every unsafe method
 * is the browser's whole part in the double-submit check.
 *
 * The cookie is the *only* place the token is kept. It is never copied into
 * browser web storage, a module variable or a React state value: a copy would
 * outlive the cookie the API rotates on every password change, and
 * `tests/no-web-storage.test.ts` fails the build if any file under `src/`
 * names those storage APIs.
 */
export const CSRF_COOKIE_NAME = 'csrf_token';
export const CSRF_HEADER_NAME = 'X-CSRF-Token';

/**
 * The current CSRF token, or `null` when there is no session.
 *
 * Read fresh on every call rather than cached, because the API replaces both
 * cookies when a password change re-issues the session.
 */
export function readCsrfToken(): string | null {
  if (typeof document === 'undefined') {
    return null;
  }
  for (const entry of document.cookie.split(';')) {
    const separator = entry.indexOf('=');
    if (separator === -1) {
      continue;
    }
    if (entry.slice(0, separator).trim() === CSRF_COOKIE_NAME) {
      return decodeURIComponent(entry.slice(separator + 1)) || null;
    }
  }
  return null;
}
