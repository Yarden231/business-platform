import { afterEach, describe, expect, it } from 'vitest';

import { CSRF_COOKIE_NAME, readCsrfToken } from '@/lib/api/csrf';

afterEach(() => {
  document.cookie = `${CSRF_COOKIE_NAME}=; path=/; max-age=0`;
});

describe('readCsrfToken', () => {
  it('returns null when the cookie is absent', () => {
    expect(readCsrfToken()).toBeNull();
  });

  it('reads the csrf_token cookie', () => {
    document.cookie = `${CSRF_COOKIE_NAME}=abc.def; path=/`;
    expect(readCsrfToken()).toBe('abc.def');
  });

  it('does not treat a similarly named cookie as the token', () => {
    document.cookie = `not_${CSRF_COOKIE_NAME}=wrong; path=/`;
    expect(readCsrfToken()).toBeNull();
  });
});
