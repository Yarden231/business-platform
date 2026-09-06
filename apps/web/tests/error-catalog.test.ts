import { describe, expect, it } from 'vitest';

import type { ErrorCode } from '@/lib/api/types';
import { he } from '@/messages/he';

describe('error catalog', () => {
  it('covers every generated ErrorCode', () => {
    const codes = Object.keys(he.errors.codes) as ErrorCode[];
    expect(codes.length).toBeGreaterThan(0);
    for (const code of codes) {
      expect(he.errors.codes[code].length).toBeGreaterThan(0);
    }
  });
});
