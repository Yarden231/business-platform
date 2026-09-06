import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC_ROOT = join(import.meta.dirname, '../src');
const WEB_STORAGE = /\b(?:localStorage|sessionStorage)\b/;

function walk(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      return walk(path);
    }
    if (path.endsWith('.ts') || path.endsWith('.tsx')) {
      return [path];
    }
    return [];
  });
}

describe('web storage', () => {
  it('is never mentioned under src/', () => {
    const offenders = walk(SRC_ROOT)
      .filter((path) => WEB_STORAGE.test(readFileSync(path, 'utf8')))
      .map((path) => relative(SRC_ROOT, path));

    expect(offenders).toEqual([]);
  });
});
