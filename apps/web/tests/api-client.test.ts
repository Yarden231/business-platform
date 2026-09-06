import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  changePassword,
  getCurrentUser,
  isPasswordChangeRequired,
  isUnauthenticated,
  login,
  logout,
} from '@/lib/api/client';
import { CSRF_COOKIE_NAME, CSRF_HEADER_NAME } from '@/lib/api/csrf';
import { ApiError, NetworkError } from '@/lib/api/errors';

function stubFetch(implementation: typeof fetch): ReturnType<typeof vi.fn<typeof fetch>> {
  const fetchMock = vi.fn<typeof fetch>(implementation);
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = `${CSRF_COOKIE_NAME}=; path=/; max-age=0`;
});

describe('api client', () => {
  it('posts login to the same-origin prefix without a CSRF header', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })));

    await login({ email: 'admin@example.test', password: 'secret-password' });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe('/api/v1/auth/login');
    expect(init).toMatchObject({
      method: 'POST',
      credentials: 'same-origin',
    });
    const headers = new Headers(init?.headers);
    expect(headers.get(CSRF_HEADER_NAME)).toBeNull();
  });

  it('sends X-CSRF-Token on logout when the cookie is present', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-from-login; path=/`;
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })));

    await logout();

    const [, init] = fetchMock.mock.calls[0] ?? [];
    const headers = new Headers(init?.headers);
    expect(headers.get(CSRF_HEADER_NAME)).toBe('csrf-from-login');
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/auth/logout');
  });

  it('sends X-CSRF-Token on password change', async () => {
    document.cookie = `${CSRF_COOKIE_NAME}=csrf-from-login; path=/`;
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })));

    await changePassword({ current_password: 'old-password-12', new_password: 'new-password-12' });

    const headers = new Headers(fetchMock.mock.calls[0]?.[1]?.headers);
    expect(headers.get(CSRF_HEADER_NAME)).toBe('csrf-from-login');
  });

  it('parses GET /auth/me into a typed user', async () => {
    stubFetch(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            id: '11111111-1111-4111-8111-111111111111',
            email: 'admin@example.test',
            full_name: 'Admin',
            role: 'ADMIN',
            must_change_password: false,
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );

    await expect(getCurrentUser()).resolves.toMatchObject({
      email: 'admin@example.test',
      role: 'ADMIN',
    });
  });

  it('turns an error envelope into an ApiError', async () => {
    stubFetch(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            error: {
              code: 'AUTH_INVALID_CREDENTIALS',
              message: 'Those credentials are not valid.',
              details: [],
              request_id: 'req-1',
            },
          }),
          { status: 401, headers: { 'content-type': 'application/json', 'X-Request-ID': 'req-1' } },
        ),
      ),
    );

    await expect(login({ email: 'x@y.z', password: 'nope' })).rejects.toMatchObject({
      name: 'ApiError',
      code: 'AUTH_INVALID_CREDENTIALS',
      status: 401,
      requestId: 'req-1',
    } satisfies Partial<ApiError>);
  });

  it('turns a network failure into a NetworkError', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')));

    await expect(getCurrentUser()).rejects.toBeInstanceOf(NetworkError);
  });

  it('classifies 401 and PASSWORD_CHANGE_REQUIRED', () => {
    expect(
      isUnauthenticated(
        new ApiError({
          status: 401,
          code: 'AUTH_REQUIRED',
          message: 'Authentication is required.',
          details: [],
          requestId: 'r',
        }),
      ),
    ).toBe(true);
    expect(
      isPasswordChangeRequired(
        new ApiError({
          status: 403,
          code: 'PASSWORD_CHANGE_REQUIRED',
          message: 'The password must be changed.',
          details: [],
          requestId: 'r',
        }),
      ),
    ).toBe(true);
  });
});
