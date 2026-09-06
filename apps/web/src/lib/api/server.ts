/**
 * Server-only session lookup (docs/architecture.md §9).
 *
 * The protected layout asks `GET /api/v1/auth/me` before rendering. The
 * browser still only talks to the web origin; this fetch is process-to-process
 * inside the Compose network (or to localhost when Next.js runs on the host)
 * and forwards the incoming `session` cookie. A 401 here is a UX redirect,
 * not an authorization decision — the API enforces everything.
 */
import { cache } from 'react';

import { SESSION_COOKIE_NAME } from '@/lib/constants';
import type { CurrentUser } from '@/lib/api/types';

function apiOrigin(): string {
  return process.env.API_INTERNAL_URL ?? 'http://localhost:8000';
}

async function cookieHeader(): Promise<string | null> {
  const { cookies } = await import('next/headers');
  const store = await cookies();
  if (store.get(SESSION_COOKIE_NAME) === undefined) {
    return null;
  }
  return store
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join('; ');
}

/**
 * The authenticated user for this request, or `null` if there is no usable session.
 *
 * Wrapped in `cache()` so the layout and the page share one round trip.
 */
export const getCurrentUserFromSession = cache(async (): Promise<CurrentUser | null> => {
  const cookie = await cookieHeader();
  if (cookie === null) {
    return null;
  }

  let response: Response;
  try {
    response = await fetch(`${apiOrigin()}/api/v1/auth/me`, {
      headers: { Accept: 'application/json', cookie },
      cache: 'no-store',
    });
  } catch {
    return null;
  }

  if (!response.ok) {
    return null;
  }

  return (await response.json()) as CurrentUser;
});
