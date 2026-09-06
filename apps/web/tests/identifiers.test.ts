import { describe, expect, it } from 'vitest';

import { digitsOnly, isValidIsraeliId, israeliIdChecksumValid } from '@/lib/identifiers';

describe('Israeli ID checksum (client mirror)', () => {
  it('accepts a known-valid number', () => {
    expect(isValidIsraeliId('123456782')).toBe(true);
  });

  it('accepts spaces and dashes', () => {
    expect(isValidIsraeliId('123-456-782')).toBe(true);
    expect(digitsOnly('123-456-782')).toBe('123456782');
  });

  it('rejects a wrong check digit', () => {
    expect(israeliIdChecksumValid('123456780')).toBe(false);
  });

  it('rejects a short number', () => {
    expect(isValidIsraeliId('12345678')).toBe(false);
  });
});
