/**
 * Route protection is UX only (docs/architecture.md §9).
 *
 * Next.js 16 names this file `proxy.ts` (the former `middleware` convention).
 * A missing `session` cookie sends the browser to `/login`. The cookie's
 * presence is not a security control: the protected layout still asks
 * `GET /api/v1/auth/me`, and every API endpoint enforces authentication
 * independently. `/login` is reachable without a cookie so a first visit works.
 */
import { NextResponse, type NextRequest } from 'next/server';

import { SESSION_COOKIE_NAME } from '@/lib/constants';

const PUBLIC_PATHS = new Set(['/login']);

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  if (PUBLIC_PATHS.has(pathname)) {
    return NextResponse.next();
  }

  if (request.cookies.get(SESSION_COOKIE_NAME) === undefined) {
    const login = new URL('/login', request.url);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
};
