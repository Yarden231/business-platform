/**
 * The typed same-origin API client (docs/api.md §6, ADR-0005, ADR-0017).
 *
 * The browser only ever talks to `/api/v1/*` on the web origin. Next.js
 * rewrites that path to the API, so the session cookie stays first-party and
 * `SameSite=Lax` can do its job. Nothing here addresses port 8000.
 *
 * Unsafe methods echo the `csrf_token` cookie in `X-CSRF-Token`. The token is
 * read from the cookie on every call, never cached, and never written to web
 * storage (docs/security.md §3).
 */
import { API_PREFIX } from '@/lib/constants';
import { CSRF_HEADER_NAME, readCsrfToken } from '@/lib/api/csrf';
import { ApiError, apiErrorFromResponse, NetworkError } from '@/lib/api/errors';
import type { CurrentUser, LoginBody, PasswordChangeBody } from '@/lib/api/types';

const UNSAFE_METHODS = new Set(['POST', 'PATCH', 'PUT', 'DELETE']);

export type ApiRequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal | undefined;
};

/**
 * Low-level fetch against `/api/v1`. Returns the parsed JSON body, or
 * `undefined` for a `204`.
 *
 * Callers should prefer the named helpers below. This exists so a later
 * feature can add one function without inventing a second client.
 */
export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers = new Headers();
  headers.set('Accept', 'application/json');

  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }

  if (UNSAFE_METHODS.has(method)) {
    const csrf = readCsrfToken();
    if (csrf !== null) {
      headers.set(CSRF_HEADER_NAME, csrf);
    }
  }

  const init: RequestInit = {
    method,
    headers,
    credentials: 'same-origin',
    cache: 'no-store',
  };
  if (options.body !== undefined) {
    init.body = JSON.stringify(options.body);
  }
  if (options.signal !== undefined) {
    init.signal = options.signal;
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, init);
  } catch (cause) {
    throw new NetworkError(cause);
  }

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

/** `POST /auth/login` — `204` plus the two cookies. No CSRF: there is no session yet. */
export function login(body: LoginBody): Promise<void> {
  return apiRequest<void>('/auth/login', { method: 'POST', body });
}

/** `POST /auth/logout` — revokes this session and clears both cookies. */
export function logout(): Promise<void> {
  return apiRequest<void>('/auth/logout', { method: 'POST' });
}

/** `GET /auth/me` — who the cookie belongs to, and whether they must rotate first. */
export function getCurrentUser(signal?: AbortSignal): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/auth/me', { signal });
}

/** `POST /auth/password` — rotates the password and re-issues both cookies. */
export function changePassword(body: PasswordChangeBody): Promise<void> {
  return apiRequest<void>('/auth/password', { method: 'POST', body });
}

/** `GET /healthz` through the same-origin proxy. */
export function getHealth(signal?: AbortSignal): Promise<{ status: 'ok' }> {
  return apiRequest<{ status: 'ok' }>('/healthz', { signal });
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}

export function isUnauthenticated(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 401 ||
      error.code === 'AUTH_REQUIRED' ||
      error.code === 'AUTH_SESSION_EXPIRED' ||
      error.code === 'AUTH_ACCOUNT_INACTIVE')
  );
}

export function isPasswordChangeRequired(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'PASSWORD_CHANGE_REQUIRED';
}
