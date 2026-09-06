import { describe, expect, it } from 'vitest';

import { t, tDynamic } from '@/messages/t';

describe('t', () => {
  it('returns a catalog string', () => {
    expect(t('auth.login.submit')).toBe('התחברות');
  });

  it('interpolates placeholders', () => {
    expect(t('home.title', { name: 'יעל' })).toBe('שלום, יעל');
  });

  it('leaves an unknown placeholder in place', () => {
    expect(t('home.title')).toBe('שלום, {name}');
  });
});

describe('tDynamic', () => {
  it('resolves a key assembled from an API value', () => {
    expect(tDynamic('shell.roles.ADMIN', 'ADMIN')).toBe('מנהל מערכת');
  });

  it('returns the fallback when the key is missing', () => {
    expect(tDynamic('shell.roles.UNKNOWN', 'UNKNOWN')).toBe('UNKNOWN');
  });
});
