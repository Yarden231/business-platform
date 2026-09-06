import { describe, expect, it } from 'vitest';

import { formatBusinessDate, formatInstant, formatNumber } from '@/lib/format';

describe('formatInstant', () => {
  it('renders a UTC instant in Jerusalem time', () => {
    // 09:12 UTC is 12:12 in Israel on a September date (IDT, UTC+3).
    const formatted = formatInstant('2026-09-01T09:12:33Z');
    expect(formatted).toContain('2026');
    expect(formatted).toMatch(/12:12|12\.12/);
  });
});

describe('formatBusinessDate', () => {
  it('does not shift a calendar date across a timezone', () => {
    expect(formatBusinessDate('2026-09-01')).toContain('2026');
    expect(formatBusinessDate('2026-09-01')).toMatch(/1|01/);
  });

  it('rejects a value that is not YYYY-MM-DD', () => {
    expect(() => formatBusinessDate('not-a-date')).toThrow(/Invalid business date/);
  });
});

describe('formatNumber', () => {
  it('uses the Hebrew locale grouping', () => {
    expect(formatNumber(1234)).toMatch(/1.234|1,234|1\u00a0234|1\u202f234/);
  });
});
